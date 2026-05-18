"""
GitHub 信息路由模块

提供 GitHub 仓库信息解析和资源抓取功能。

端点列表：
- GET  /api/github-info?url=xxx — 解析 GitHub 仓库信息
- POST /api/github/{projectId}/fetch-resources — 一键抓取所有 GitHub 资源（按优先级分批）
- POST /api/github/{projectId}/fetch-issues — 单独抓取 Issues
- POST /api/github/{projectId}/fetch-releases — 单独抓取 Releases
- POST /api/github/{projectId}/fetch-prs — 单独抓取 PRs
- POST /api/github/{projectId}/fetch-commits — 单独抓取 Commits
- POST /api/github/{projectId}/fetch-community — 单独抓取社区数据（Stargazers/Forks/Watchers）
- POST /api/github/{projectId}/fetch-docs — 单独抓取文档（CONTRIBUTING/LICENSE/CODE_OF_CONDUCT/SECURITY）
- POST /api/github/{projectId}/fetch-branches — 单独抓取 Branches
- GET  /api/github/{projectId}/fetch-status — 获取各资源抓取状态
"""

import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.routers.projects import _detect_system_proxy
from backend.services.github_fetcher import GitHubFetcher
from backend.services.project_service import (
    get_project_by_id,
    parse_github_url,
    get_github_fetch_status,
    update_github_fetch_status,
)
from backend.config import PROJECTS_ROOT

router = APIRouter(tags=["github"])


def _parse_github_url(url: str) -> Optional[dict]:
    """解析 GitHub URL 获取 owner 和 repo

    Args:
        url: GitHub 仓库 URL
    Returns:
        包含 owner 和 repo 的字典，解析失败返回 None
    """
    patterns = [
        r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$",
        r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
        r"^([^/]+)/([^/]+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return {"owner": match.group(1), "repo": match.group(2).replace(".git", "")}
    return None


async def _fetch_github_api(owner: str, repo: str, path: str = "", token: str = ""):
    """调用 GitHub API 获取仓库信息

    优先使用传入的 token，其次读取环境变量 GITHUB_TOKEN。
    配置 Token 后 API 限额从 60 次/小时提升至 5000 次/小时。

    Args:
        owner: 仓库所有者
        repo: 仓库名称
        path: API 路径后缀
        token: 用户配置的 GitHub Personal Access Token
    Returns:
        API 响应 JSON，请求失败返回 None
    """
    effective_token = token or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if effective_token:
        headers["Authorization"] = f"token {effective_token}"

    url = (
        f"https://api.github.com/repos/{owner}/{repo}/{path}"
        if path
        else f"https://api.github.com/repos/{owner}/{repo}"
    )

    try:
        # 自动检测系统代理，确保 httpx 也走代理
        proxy_url = _detect_system_proxy()
        client_kwargs = {"timeout": 15}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                rate_limit = resp.headers.get("X-RateLimit-Remaining", "?")
                print(f"[GitHub API] 403 限流，剩余次数: {rate_limit}")
                return {"_rate_limited": True, "_status": 403}
            if resp.status_code != 200:
                print(f"[GitHub API] 请求失败: {resp.status_code} {url}")
                return None
            return resp.json()
    except Exception as e:
        print(f"[GitHub API] 请求异常: {e}")
        return None


async def _get_readme(owner: str, repo: str) -> Optional[str]:
    """获取仓库 README 内容

    Args:
        owner: 仓库所有者
        repo: 仓库名称
    Returns:
        README 文本内容，获取失败返回 None
    """
    try:
        proxy_url = _detect_system_proxy()
        client_kwargs = {"timeout": 10}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                f"https://ghfast.top/https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
            )
            if resp.status_code == 200:
                return resp.text
    except Exception:
        pass
    return None


@router.get("/api/github-info")
async def get_github_info(url: str = Query(..., description="GitHub 仓库 URL")):
    """解析 GitHub 仓库信息

    使用 GitHub API 获取 stars、forks、description、README、latest release 等信息。

    Args:
        url: GitHub 仓库 URL
    Returns:
        仓库信息对象
    """
    try:
        if not url:
            raise HTTPException(status_code=400, detail="url is required")

        parsed = _parse_github_url(url)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid GitHub URL")

        owner, repo = parsed["owner"], parsed["repo"]

        # 从 settings 中读取用户配置的 GitHub Token
        github_token = ""
        try:
            from backend.services.project_service import get_setting
            import json
            raw = get_setting("settings-storage")
            if raw:
                settings = json.loads(raw)
                state = settings.get("state", settings)
                github_token = state.get("githubToken", "") or ""
        except Exception:
            pass

        # 第1次调用：获取仓库基础信息
        repo_data = await _fetch_github_api(owner, repo, "", token=github_token)

        if not repo_data or (isinstance(repo_data, dict) and repo_data.get("_rate_limited")):
            if isinstance(repo_data, dict) and repo_data.get("_rate_limited"):
                raise HTTPException(
                    status_code=429,
                    detail="GitHub API 请求频率超限，请稍后重试，或在系统设置中配置 GitHub Token 以提高限额",
                )
            raise HTTPException(status_code=404, detail="仓库不存在或无法访问，请检查 GitHub 地址是否正确")

        result = {
            "name": repo_data.get("name", repo),
            "description": repo_data.get("description"),
            "githubUrl": repo_data.get("html_url", url),
            "versionType": "none",
            "latestVersion": None,
            "downloadUrl": None,
            "commitSha": None,
            "commitDate": None,
            "readme": None,
        }

        # 第2次调用：按需获取版本信息（优先 release，其次 tag，最后 commit）
        # 最多只调用1次版本API，避免浪费配额
        releases_data = await _fetch_github_api(owner, repo, "releases/latest", token=github_token)
        if releases_data and releases_data.get("tag_name"):
            result["versionType"] = "release"
            result["latestVersion"] = releases_data["tag_name"]
            result["downloadUrl"] = releases_data.get("zipball_url") or releases_data.get("tarball_url")
            if releases_data.get("target_commitish"):
                result["commitSha"] = releases_data["target_commitish"]
        else:
            tags_data = await _fetch_github_api(owner, repo, "tags", token=github_token)
            if tags_data and isinstance(tags_data, list) and len(tags_data) > 0:
                result["versionType"] = "tag"
                result["latestVersion"] = tags_data[0]["name"]
                result["downloadUrl"] = f"https://github.com/{owner}/{repo}/archive/refs/tags/{tags_data[0]['name']}.zip"
                result["commitSha"] = tags_data[0].get("commit", {}).get("sha")
            else:
                commits_data = await _fetch_github_api(owner, repo, "commits?per_page=1", token=github_token)
                if commits_data and isinstance(commits_data, list) and len(commits_data) > 0:
                    result["versionType"] = "commit"
                    result["commitSha"] = commits_data[0]["sha"]
                    result["commitDate"] = commits_data[0].get("commit", {}).get("author", {}).get("date")

        # 获取 README（raw.githubusercontent.com 不消耗 API 配额）
        readme = await _get_readme(owner, repo)
        if readme:
            from backend.utils.readme_utils import rewrite_readme_image_paths
            result["readme"] = rewrite_readme_image_paths(readme, owner, repo)

        return result

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to fetch GitHub info")


# ================================================================
# 请求体模型
# ================================================================

class FetchResourcesInput(BaseModel):
    """一键抓取资源请求体"""
    priority: str = "P0"


# ================================================================
# 辅助函数
# ================================================================

def _get_project_path(project: dict) -> str:
    """获取项目本地存储路径

    优先使用数据库中已有的 local_path，其次从 PROJECTS_ROOT 推算。

    Args:
        project: 项目字典
    Returns:
        项目本地存储路径
    """
    existing = project.get("local_path")
    if existing and os.path.isabs(existing):
        return existing
    return os.path.join(PROJECTS_ROOT, project["name"])


def _validate_project_and_url(project_id: int) -> tuple[dict, str, str]:
    """验证项目存在且 GitHub URL 有效，返回 (project, owner, repo)

    Args:
        project_id: 项目 ID
    Returns:
        (project, owner, repo) 元组
    Raises:
        HTTPException: 项目不存在或 URL 无效时抛出
    """
    project = get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    github_url = project.get("github_url")
    if not github_url:
        raise HTTPException(status_code=400, detail="该项目未设置 GitHub 地址，无法抓取资源")

    parsed = parse_github_url(github_url)
    if not parsed:
        raise HTTPException(status_code=400, detail=f"GitHub URL 格式无效：{github_url}")

    owner, repo = parsed
    return project, owner, repo


def _create_fetcher() -> GitHubFetcher:
    """创建 GitHubFetcher 实例

    优先从 settings 中读取用户配置的 GitHub Token，
    其次读取环境变量 GITHUB_TOKEN。

    Returns:
        GitHubFetcher 实例
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            from backend.services.project_service import get_setting
            import json as _json
            raw = get_setting("settings-storage")
            if raw:
                settings = _json.loads(raw)
                state = settings.get("state", settings)
                token = state.get("githubToken", "") or None
        except Exception:
            pass
    return GitHubFetcher(token=token)


def _now_iso() -> str:
    """获取当前 UTC 时间的 ISO 8601 格式字符串

    Returns:
        ISO 8601 格式的时间字符串
    """
    return datetime.now(timezone.utc).isoformat()


# ================================================================
# GitHub 资源抓取端点
# ================================================================

@router.post("/api/github/{project_id}/fetch-resources")
async def fetch_all_resources(project_id: int, body: FetchResourcesInput = None):
    """一键抓取所有 GitHub 资源（按优先级分批）

    流程：从项目获取 github_url → 解析 owner/repo → 创建 GitHubFetcher →
    调用 fetch_all_resources → 更新数据库状态

    Args:
        project_id: 项目 ID
        body: 请求体，priority 可选 P0/P1/P2，默认 P0
    Returns:
        抓取结果，包含 status/results/date_dir
    """
    body = body or FetchResourcesInput()
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行一键抓取
        result = await fetcher.fetch_all_resources(
            owner=owner,
            repo=repo,
            project_path=project_path,
            priority=body.priority,
        )

        # 判断整体状态
        results = result.get("results", {})
        has_error = any(v.get("status") == "error" for v in results.values())
        has_ok = any(v.get("status") == "ok" for v in results.values())

        if has_ok and not has_error:
            overall_status = "completed"
        elif has_ok and has_error:
            overall_status = "partial"
        else:
            overall_status = "failed"

        # 更新项目抓取状态和各资源时间戳
        now_iso = _now_iso()
        ts_kwargs = {}
        resource_ts_map = {
            "issues": "github_issues_fetched_at",
            "releases": "github_releases_fetched_at",
            "pull_requests": "github_prs_fetched_at",
            "commits": "github_commits_fetched_at",
            "stargazers": "github_community_fetched_at",
            "forks": "github_community_fetched_at",
            "watchers": "github_community_fetched_at",
            "branches": "github_branches_fetched_at",
            "contributing": "github_docs_fetched_at",
            "code_of_conduct": "github_docs_fetched_at",
            "license": "github_docs_fetched_at",
            "security": "github_docs_fetched_at",
        }
        for resource_name, ts_field in resource_ts_map.items():
            if resource_name in results and results[resource_name].get("status") == "ok":
                ts_kwargs[ts_field] = now_iso

        update_github_fetch_status(project_id, overall_status, **ts_kwargs)

        return {
            "status": overall_status,
            "results": results,
            "date_dir": result.get("date_dir"),
        }

    except Exception as err:
        # 抓取失败，更新状态
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取资源失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-issues")
async def fetch_issues(project_id: int):
    """单独抓取 Issues

    流程：解析 URL → fetch_issues → save_issues_to_sources → 更新 github_issues_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/count/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 获取上次抓取时间用于增量抓取
    fetch_status = get_github_fetch_status(project_id)
    since = fetch_status.get("github_issues_fetched_at") if fetch_status else None

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行抓取
        issues = await fetcher.fetch_issues(owner, repo, since=since)
        # 保存到本地
        date_dir = fetcher.save_issues_to_sources(project_path, issues)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_issues_fetched_at=now_iso
        )

        return {
            "status": "success",
            "count": len(issues),
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取 Issues 失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-releases")
async def fetch_releases(project_id: int):
    """单独抓取 Releases

    流程：解析 URL → fetch_releases → save_releases_to_sources → 更新 github_releases_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/count/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行抓取
        releases = await fetcher.fetch_releases(owner, repo)
        # 保存到本地
        date_dir = fetcher.save_releases_to_sources(project_path, releases)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_releases_fetched_at=now_iso
        )

        return {
            "status": "success",
            "count": len(releases),
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取 Releases 失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-prs")
async def fetch_prs(project_id: int):
    """单独抓取 Pull Requests

    流程：解析 URL → fetch_pull_requests → save_prs_to_sources → 更新 github_prs_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/count/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 获取上次抓取时间用于增量抓取
    fetch_status = get_github_fetch_status(project_id)
    since = fetch_status.get("github_prs_fetched_at") if fetch_status else None

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行抓取
        prs = await fetcher.fetch_pull_requests(owner, repo, since=since)
        # 保存到本地
        date_dir = fetcher.save_prs_to_sources(project_path, prs)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_prs_fetched_at=now_iso
        )

        return {
            "status": "success",
            "count": len(prs),
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取 PRs 失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-commits")
async def fetch_commits(project_id: int):
    """单独抓取 Commits

    流程：解析 URL → fetch_commits → save_commits_to_sources → 更新 github_commits_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/count/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 获取上次抓取时间用于增量抓取
    fetch_status = get_github_fetch_status(project_id)
    since = fetch_status.get("github_commits_fetched_at") if fetch_status else None

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行抓取
        commits = await fetcher.fetch_commits(owner, repo, since=since)
        # 保存到本地
        date_dir = fetcher.save_commits_to_sources(project_path, commits)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_commits_fetched_at=now_iso
        )

        return {
            "status": "success",
            "count": len(commits),
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取 Commits 失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-community")
async def fetch_community(project_id: int):
    """单独抓取社区数据（Stargazers/Forks/Watchers）

    流程：解析 URL → 分别抓取 stargazers/forks/watchers →
    save_community_to_sources → 更新 github_community_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/counts/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 分别抓取三种社区数据
        stargazers = await fetcher.fetch_stargazers(owner, repo)
        forks = await fetcher.fetch_forks(owner, repo)
        watchers = await fetcher.fetch_watchers(owner, repo)

        # 保存到本地
        date_dir = fetcher.save_community_to_sources(
            project_path, stargazers, forks, watchers
        )

        total_count = len(stargazers) + len(forks) + len(watchers)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_community_fetched_at=now_iso
        )

        return {
            "status": "success",
            "counts": {
                "stargazers": len(stargazers),
                "forks": len(forks),
                "watchers": len(watchers),
            },
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取社区数据失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-docs")
async def fetch_docs(project_id: int):
    """单独抓取文档（CONTRIBUTING/LICENSE/CODE_OF_CONDUCT/SECURITY）

    流程：解析 URL → 分别抓取各文档 → save_docs_to_sources → 更新 github_docs_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/found/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 分别抓取各类文档
        contributing = await fetcher.fetch_contributing(owner, repo)
        code_of_conduct = await fetcher.fetch_code_of_conduct(owner, repo)
        license_info = await fetcher.fetch_license(owner, repo)
        security = await fetcher.fetch_security(owner, repo)

        # 保存到本地
        date_dir = fetcher.save_docs_to_sources(
            project_path,
            contributing=contributing,
            code_of_conduct=code_of_conduct,
            license_info=license_info,
            security=security,
        )

        # 统计找到的文档数量
        found = []
        if contributing:
            found.append("CONTRIBUTING")
        if code_of_conduct:
            found.append("CODE_OF_CONDUCT")
        if license_info:
            found.append("LICENSE")
        if security:
            found.append("SECURITY")

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_docs_fetched_at=now_iso
        )

        return {
            "status": "success",
            "found": found,
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取文档失败：{str(err)}")


@router.post("/api/github/{project_id}/fetch-branches")
async def fetch_branches(project_id: int):
    """单独抓取 Branches

    流程：解析 URL → fetch_branches → save_branches_to_sources → 更新 github_branches_fetched_at

    Args:
        project_id: 项目 ID
    Returns:
        抓取结果，包含 status/count/date_dir
    """
    project, owner, repo = _validate_project_and_url(project_id)
    project_path = _get_project_path(project)
    fetcher = _create_fetcher()

    # 更新状态为抓取中
    update_github_fetch_status(project_id, "fetching")

    try:
        # 执行抓取
        branches = await fetcher.fetch_branches(owner, repo)
        # 保存到本地
        date_dir = fetcher.save_branches_to_sources(project_path, branches)

        # 更新状态和时间戳
        now_iso = _now_iso()
        update_github_fetch_status(
            project_id, "completed", github_branches_fetched_at=now_iso
        )

        return {
            "status": "success",
            "count": len(branches),
            "date_dir": date_dir,
        }

    except Exception as err:
        update_github_fetch_status(project_id, "failed")
        raise HTTPException(status_code=500, detail=f"抓取 Branches 失败：{str(err)}")


@router.get("/api/github/{project_id}/fetch-status")
async def get_fetch_status(project_id: int):
    """获取各资源抓取状态

    返回项目的 GitHub 资源抓取状态和各资源最后抓取时间。

    Args:
        project_id: 项目 ID
    Returns:
        抓取状态对象，包含 github_fetch_status 和各资源 fetched_at 时间戳
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        fetch_status = get_github_fetch_status(project_id)
        if not fetch_status:
            return {
                "github_fetch_status": "pending",
                "github_issues_fetched_at": None,
                "github_releases_fetched_at": None,
                "github_prs_fetched_at": None,
                "github_commits_fetched_at": None,
                "github_community_fetched_at": None,
                "github_docs_fetched_at": None,
                "github_branches_fetched_at": None,
            }

        return fetch_status

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"获取抓取状态失败：{str(err)}")
