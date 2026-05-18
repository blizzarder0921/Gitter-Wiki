"""
GitHub 资源抓取服务模块

提供 GitHub 仓库资源的异步抓取与本地持久化功能，包括：
- Issues / Issue Comments / Releases / Pull Requests 等 P0/P1 资源
- Commits / Stargazers / Forks / Watchers / Branches 等 P2 资源
- CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / LICENSE 等项目文档
- 一键按优先级抓取所有资源的 fetch_all_resources 入口

抓取结果以 Markdown（含 YAML Front Matter）或 JSON 格式
写入项目 sources/{date}/ 目录，供后续 Ingest 流程消费。

GPLv3 License - Gitter Project
"""

import asyncio
import base64
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from backend.utils.rate_limiter import get_github_rate_limiter


class GitHubFetcher:
    """GitHub 资源抓取服务

    封装 GitHub REST API v3 的异步调用，支持：
    - 分页列表自动遍历
    - 增量抓取（since 参数）
    - 速率限制令牌桶控制
    - 抓取结果写入本地 sources 目录

    使用示例::

        fetcher = GitHubFetcher(token="ghp_xxx")
        issues = await fetcher.fetch_issues("owner", "repo")
        date_dir = fetcher.save_issues_to_sources("/path/to/project", issues)
    """

    # GitHub API 基础 URL
    GITHUB_API_BASE = "https://api.github.com"

    # 每页请求数量上限
    PER_PAGE = 100

    # 分页请求间休眠时间（秒），避免触发次级速率限制
    PAGE_SLEEP = 0.5

    def __init__(self, token: str = None):
        """初始化 GitHub 抓取器

        Args:
            token: GitHub 个人访问令牌，为 None 时使用未认证模式（低配额）
        """
        self.token = token
        # 自动检测系统代理（Clash/V2Ray 等）
        try:
            from backend.routers.projects import _detect_system_proxy
            self._proxy = _detect_system_proxy()
        except Exception:
            self._proxy = None
        # 构建请求头
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Gitter-App",
        }
        # 有 token 时附加 Authorization 头
        if token:
            self.headers["Authorization"] = f"token {token}"
        # 根据是否认证选择对应的速率限制器
        self.rate_limiter = get_github_rate_limiter(token)

    # ================================================================
    # 通用辅助方法
    # ================================================================

    async def _fetch_paginated_list(
        self,
        owner: str,
        repo: str,
        endpoint: str,
        params: dict = None,
    ) -> list[dict]:
        """通用分页列表抓取

        自动遍历 GitHub API 分页链接，收集所有页面的数据。
        每次请求前获取速率限制令牌，页间休眠避免次级限制。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            endpoint: API 端点路径（如 "issues"、"releases"）
            params: 额外查询参数字典

        Returns:
            所有页面的数据列表（合并后）
        """
        # 合并默认参数与自定义参数
        query_params: dict = {"per_page": self.PER_PAGE, "page": 1}
        if params:
            query_params.update(params)

        all_items: list[dict] = []
        url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/{endpoint}"

        async with httpx.AsyncClient(timeout=30, headers=self.headers, proxy=self._proxy) as client:
            while url:
                # 获取速率限制令牌（阻塞等待）
                self.rate_limiter.wait_and_acquire()

                try:
                    resp = await client.get(url, params=query_params if url.endswith(endpoint) else None)
                except httpx.RequestError as exc:
                    # 网络异常时中断分页
                    break

                # 非 2xx 响应时中断分页
                if resp.status_code < 200 or resp.status_code >= 300:
                    break

                # 解析当前页数据
                try:
                    page_data = resp.json()
                except json.JSONDecodeError:
                    break

                # 如果返回的不是列表（如单对象），包装为列表后返回
                if isinstance(page_data, dict):
                    return [page_data]

                all_items.extend(page_data)

                # 如果返回数据少于每页数量，说明已到末页
                if len(page_data) < self.PER_PAGE:
                    break

                # 解析 Link 头获取下一页 URL
                url = self._parse_next_link(resp.headers.get("link", ""))
                # 首次请求后不再传 params（next URL 已包含参数）
                query_params = None

                # 页间休眠，避免触发次级速率限制
                await asyncio.sleep(self.PAGE_SLEEP)

        return all_items

    @staticmethod
    def _parse_next_link(link_header: str) -> Optional[str]:
        """解析 GitHub API Link 头中的下一页 URL

        GitHub API 在 Link 头中使用 rel="next" 标记下一页地址。

        Args:
            link_header: HTTP Link 头的值
        Returns:
            下一页 URL 字符串，不存在时返回 None
        """
        if not link_header:
            return None
        # 匹配 <url>; rel="next" 模式
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        return match.group(1) if match else None

    async def _fetch_repo_file(self, owner: str, repo: str, filename: str) -> Optional[str]:
        """通过 Contents API 获取仓库文件内容

        使用 GitHub Contents API 获取指定文件，自动 base64 解码。
        文件不存在或请求失败时返回 None。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            filename: 文件名（如 "CONTRIBUTING.md"）
        Returns:
            文件文本内容，获取失败返回 None
        """
        # 获取速率限制令牌
        self.rate_limiter.wait_and_acquire()

        url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{filename}"
        async with httpx.AsyncClient(timeout=15, headers=self.headers, proxy=self._proxy) as client:
            try:
                resp = await client.get(url)
            except httpx.RequestError:
                return None

            if resp.status_code != 200:
                return None

            try:
                data = resp.json()
                # Contents API 返回 base64 编码的内容
                content_b64 = data.get("content", "")
                # 去除 base64 中的换行符后解码
                return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
            except (KeyError, json.JSONDecodeError, Exception):
                return None

    # ================================================================
    # P0 抓取方法
    # ================================================================

    async def fetch_issues(
        self, owner: str, repo: str, since: str = None
    ) -> list[dict]:
        """抓取 Issues，支持增量抓取，自动过滤 PR

        GitHub API 的 issues 端点同时返回 Issues 和 Pull Requests，
        需要通过 pull_request 字段过滤掉 PR。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            since: 增量抓取起始时间（ISO 8601 格式），仅返回此时间之后更新的 Issue
        Returns:
            Issue 字典列表，每个字典包含 number/title/body/labels/state/
            created_at/updated_at/html_url/comments_count
        """
        params: dict = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            params["since"] = since

        raw_issues = await self._fetch_paginated_list(owner, repo, "issues", params)

        # 过滤掉 PR（GitHub API 中 PR 也出现在 issues 端点）
        issues = [item for item in raw_issues if "pull_request" not in item]

        # 提取所需字段
        result: list[dict] = []
        for issue in issues:
            result.append({
                "number": issue.get("number"),
                "title": issue.get("title", ""),
                "body": issue.get("body") or "",
                "labels": [label.get("name", "") for label in issue.get("labels", [])],
                "state": issue.get("state", ""),
                "created_at": issue.get("created_at", ""),
                "updated_at": issue.get("updated_at", ""),
                "html_url": issue.get("html_url", ""),
                "comments_count": issue.get("comments", 0),
            })

        return result

    async def fetch_issue_comments(
        self, owner: str, repo: str, issue_number: int
    ) -> list[dict]:
        """抓取单个 Issue 的评论列表

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            issue_number: Issue 编号
        Returns:
            评论字典列表，每个字典包含 id/body/user/created_at/updated_at/html_url
        """
        raw_comments = await self._fetch_paginated_list(
            owner, repo, f"issues/{issue_number}/comments"
        )

        result: list[dict] = []
        for comment in raw_comments:
            result.append({
                "id": comment.get("id"),
                "body": comment.get("body") or "",
                "user": (comment.get("user") or {}).get("login", ""),
                "created_at": comment.get("created_at", ""),
                "updated_at": comment.get("updated_at", ""),
                "html_url": comment.get("html_url", ""),
            })

        return result

    async def fetch_releases(
        self, owner: str, repo: str
    ) -> list[dict]:
        """抓取 Releases

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            Release 字典列表，每个字典包含 tag/name/body/published_at/
            prerelease/html_url
        """
        raw_releases = await self._fetch_paginated_list(owner, repo, "releases")

        result: list[dict] = []
        for release in raw_releases:
            result.append({
                "tag": release.get("tag_name", ""),
                "name": release.get("name") or "",
                "body": release.get("body") or "",
                "published_at": release.get("published_at", ""),
                "prerelease": release.get("prerelease", False),
                "html_url": release.get("html_url", ""),
            })

        return result

    # ================================================================
    # P1 抓取方法
    # ================================================================

    async def fetch_pull_requests(
        self, owner: str, repo: str, since: str = None
    ) -> list[dict]:
        """抓取 Pull Requests，支持增量抓取

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            since: 增量抓取起始时间（ISO 8601 格式）
        Returns:
            PR 字典列表，每个字典包含 number/title/body/labels/state/
            created_at/updated_at/merged_at/html_url/user
        """
        params: dict = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            params["since"] = since

        raw_prs = await self._fetch_paginated_list(owner, repo, "pulls", params)

        result: list[dict] = []
        for pr in raw_prs:
            result.append({
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "body": pr.get("body") or "",
                "labels": [label.get("name", "") for label in pr.get("labels", [])],
                "state": pr.get("state", ""),
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "merged_at": pr.get("merged_at"),
                "html_url": pr.get("html_url", ""),
                "user": (pr.get("user") or {}).get("login", ""),
            })

        return result

    async def fetch_contributing(self, owner: str, repo: str) -> Optional[str]:
        """抓取 CONTRIBUTING.md

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            CONTRIBUTING.md 文本内容，不存在时返回 None
        """
        return await self._fetch_repo_file(owner, repo, "CONTRIBUTING.md")

    async def fetch_code_of_conduct(self, owner: str, repo: str) -> Optional[str]:
        """抓取 CODE_OF_CONDUCT.md

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            CODE_OF_CONDUCT.md 文本内容，不存在时返回 None
        """
        return await self._fetch_repo_file(owner, repo, "CODE_OF_CONDUCT.md")

    async def fetch_license(self, owner: str, repo: str) -> Optional[dict]:
        """抓取许可证信息

        使用 GitHub License API 获取许可证详情。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            许可证字典（spdx_id/name/html_url），获取失败返回 None
        """
        # 获取速率限制令牌
        self.rate_limiter.wait_and_acquire()

        url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/license"
        async with httpx.AsyncClient(timeout=15, headers=self.headers, proxy=self._proxy) as client:
            try:
                resp = await client.get(url)
            except httpx.RequestError:
                return None

            if resp.status_code != 200:
                return None

            try:
                data = resp.json()
                license_info = data.get("license") or {}
                return {
                    "spdx_id": license_info.get("spdx_id", ""),
                    "name": license_info.get("name", ""),
                    "html_url": license_info.get("html_url", ""),
                }
            except (KeyError, json.JSONDecodeError):
                return None

    # ================================================================
    # P2 抓取方法
    # ================================================================

    async def fetch_security(self, owner: str, repo: str) -> Optional[str]:
        """抓取 SECURITY.md

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            SECURITY.md 文本内容，不存在时返回 None
        """
        return await self._fetch_repo_file(owner, repo, "SECURITY.md")

    async def fetch_commits(
        self, owner: str, repo: str, since: str = None
    ) -> list[dict]:
        """抓取 Commits，支持增量抓取

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            since: 增量抓取起始时间（ISO 8601 格式）
        Returns:
            Commit 字典列表，每个字典包含 sha/message/author/date/html_url
        """
        params: dict = {"per_page": self.PER_PAGE}
        if since:
            params["since"] = since

        raw_commits = await self._fetch_paginated_list(owner, repo, "commits", params)

        result: list[dict] = []
        for commit in raw_commits:
            commit_data = commit.get("commit") or {}
            author_data = commit_data.get("author") or {}
            result.append({
                "sha": commit.get("sha", ""),
                "message": commit_data.get("message", ""),
                "author": author_data.get("name", ""),
                "date": author_data.get("date", ""),
                "html_url": commit.get("html_url", ""),
            })

        return result

    async def fetch_stargazers(self, owner: str, repo: str) -> list[dict]:
        """抓取 Stargazers

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            Stargazer 字典列表，每个字典包含 user/starred_at
        """
        # 使用带时间戳的 Accept 头以获取 starred_at
        headers = {**self.headers, "Accept": "application/vnd.github.v3.star+json"}
        url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/stargazers"

        all_items: list[dict] = []
        page = 1

        async with httpx.AsyncClient(timeout=30, headers=headers, proxy=self._proxy) as client:
            while True:
                self.rate_limiter.wait_and_acquire()
                try:
                    resp = await client.get(url, params={"per_page": self.PER_PAGE, "page": page})
                except httpx.RequestError:
                    break

                if resp.status_code < 200 or resp.status_code >= 300:
                    break

                try:
                    page_data = resp.json()
                except json.JSONDecodeError:
                    break

                if not page_data:
                    break

                for item in page_data:
                    user_info = item.get("user") or {}
                    all_items.append({
                        "user": user_info.get("login", ""),
                        "starred_at": item.get("starred_at", ""),
                    })

                if len(page_data) < self.PER_PAGE:
                    break

                page += 1
                await asyncio.sleep(self.PAGE_SLEEP)

        return all_items

    async def fetch_forks(self, owner: str, repo: str) -> list[dict]:
        """抓取 Forks

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            Fork 字典列表，每个字典包含 full_name/html_url/stars/created_at
        """
        raw_forks = await self._fetch_paginated_list(
            owner, repo, "forks", {"sort": "newest"}
        )

        result: list[dict] = []
        for fork in raw_forks:
            result.append({
                "full_name": fork.get("full_name", ""),
                "html_url": fork.get("html_url", ""),
                "stars": fork.get("stargazers_count", 0),
                "created_at": fork.get("created_at", ""),
            })

        return result

    async def fetch_watchers(self, owner: str, repo: str) -> list[dict]:
        """抓取 Watchers（使用 subscribers 端点）

        GitHub API 中 watchers 和 subscribers 是不同概念，
        此处使用 subscribers 端点获取真正关注仓库的用户。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            Watcher 字典列表，每个字典包含 login/html_url
        """
        raw_watchers = await self._fetch_paginated_list(
            owner, repo, "subscribers"
        )

        result: list[dict] = []
        for watcher in raw_watchers:
            result.append({
                "login": watcher.get("login", ""),
                "html_url": watcher.get("html_url", ""),
            })

        return result

    async def fetch_branches(self, owner: str, repo: str) -> list[dict]:
        """抓取 Branches

        Args:
            owner: 仓库所有者
            repo: 仓库名称
        Returns:
            Branch 字典列表，每个字典包含 name/protected/sha
        """
        raw_branches = await self._fetch_paginated_list(owner, repo, "branches")

        result: list[dict] = []
        for branch in raw_branches:
            commit_info = branch.get("commit") or {}
            result.append({
                "name": branch.get("name", ""),
                "protected": branch.get("protected", False),
                "sha": commit_info.get("sha", ""),
            })

        return result

    # ================================================================
    # 存储方法
    # ================================================================

    @staticmethod
    def _get_date_dir() -> str:
        """获取当前日期目录名

        Returns:
            YYYY-MM-DD 格式的日期字符串
        """
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符

        将 Windows 文件名中不允许的字符替换为下划线或移除。

        Args:
            name: 原始文件名
        Returns:
            清理后的安全文件名
        """
        # 替换 Windows 不允许的字符
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        # 移除首尾空白和点号
        name = name.strip(" .")
        # 截断过长文件名
        if len(name) > 200:
            name = name[:200]
        return name or "untitled"

    @staticmethod
    def _build_frontmatter_yaml(fields: dict) -> str:
        """构建 YAML Front Matter 文本块

        将字典转换为 YAML 格式的 Front Matter 块。
        列表值使用 YAML 行内数组格式，字符串值自动加引号。

        Args:
            fields: Front Matter 字段字典
        Returns:
            包含 --- 分隔符的 YAML Front Matter 文本
        """
        lines = ["---"]
        for key, value in fields.items():
            if isinstance(value, list):
                # 列表使用行内数组格式
                items = ", ".join(f'"{v}"' for v in value)
                lines.append(f'{key}: [{items}]')
            elif isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key}: {value}")
            elif value is None:
                lines.append(f"{key}: null")
            else:
                # 字符串值加引号
                escaped = str(value).replace('"', '\\"')
                lines.append(f'{key}: "{escaped}"')
        lines.append("---")
        return "\n".join(lines)

    def save_issues_to_sources(self, project_path: str, issues: list[dict]) -> str:
        """将 Issues 写入 sources/{date}/issues/ 目录

        每个 Issue 保存为一个 Markdown 文件，文件名格式为
        {编号}-{标题}.md（如 001-install-error.md）。
        文件包含 YAML Front Matter 和 Issue 正文。

        Args:
            project_path: 项目本地路径
            issues: Issue 字典列表
        Returns:
            写入的日期目录名（如 "2026-05-14"）
        """
        date_dir = self._get_date_dir()
        issues_dir = os.path.join(project_path, "sources", date_dir, "issues")
        os.makedirs(issues_dir, exist_ok=True)

        for issue in issues:
            number = issue.get("number", 0)
            title = issue.get("title", "untitled")
            # 构建文件名：编号-标题.md
            safe_title = self._sanitize_filename(title)
            filename = f"{number:03d}-{safe_title}.md"
            filepath = os.path.join(issues_dir, filename)

            # 构建 Front Matter
            frontmatter = self._build_frontmatter_yaml({
                "number": number,
                "title": title,
                "labels": issue.get("labels", []),
                "state": issue.get("state", ""),
                "created_at": issue.get("created_at", ""),
                "updated_at": issue.get("updated_at", ""),
                "html_url": issue.get("html_url", ""),
                "comments_count": issue.get("comments_count", 0),
            })

            # 组合完整内容
            body = issue.get("body", "")
            content = f"{frontmatter}\n\n{body}"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return date_dir

    def save_releases_to_sources(self, project_path: str, releases: list[dict]) -> str:
        """将 Releases 写入 sources/{date}/releases/ 目录

        每个 Release 保存为一个 Markdown 文件，文件名格式为
        {tag}-{name}.md。

        Args:
            project_path: 项目本地路径
            releases: Release 字典列表
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        releases_dir = os.path.join(project_path, "sources", date_dir, "releases")
        os.makedirs(releases_dir, exist_ok=True)

        for release in releases:
            tag = release.get("tag", "untagged")
            name = release.get("name") or tag
            # 构建文件名：tag-name.md
            safe_tag = self._sanitize_filename(tag)
            safe_name = self._sanitize_filename(name)
            filename = f"{safe_tag}-{safe_name}.md"
            filepath = os.path.join(releases_dir, filename)

            # 构建 Front Matter
            frontmatter = self._build_frontmatter_yaml({
                "tag": tag,
                "name": name,
                "published_at": release.get("published_at", ""),
                "prerelease": release.get("prerelease", False),
                "html_url": release.get("html_url", ""),
            })

            # 组合完整内容
            body = release.get("body", "")
            content = f"{frontmatter}\n\n{body}"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return date_dir

    def save_prs_to_sources(self, project_path: str, prs: list[dict]) -> str:
        """将 PRs 写入 sources/{date}/pull-requests/ 目录

        每个 PR 保存为一个 Markdown 文件，文件名格式为
        {编号}-{标题}.md。

        Args:
            project_path: 项目本地路径
            prs: PR 字典列表
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        prs_dir = os.path.join(project_path, "sources", date_dir, "pull-requests")
        os.makedirs(prs_dir, exist_ok=True)

        for pr in prs:
            number = pr.get("number", 0)
            title = pr.get("title", "untitled")
            # 构建文件名：编号-标题.md
            safe_title = self._sanitize_filename(title)
            filename = f"{number:03d}-{safe_title}.md"
            filepath = os.path.join(prs_dir, filename)

            # 构建 Front Matter
            frontmatter = self._build_frontmatter_yaml({
                "number": number,
                "title": title,
                "labels": pr.get("labels", []),
                "state": pr.get("state", ""),
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "merged_at": pr.get("merged_at"),
                "html_url": pr.get("html_url", ""),
                "user": pr.get("user", ""),
            })

            # 组合完整内容
            body = pr.get("body", "")
            content = f"{frontmatter}\n\n{body}"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return date_dir

    def save_commits_to_sources(self, project_path: str, commits: list[dict]) -> str:
        """将 Commits 写入 sources/{date}/commits/ 目录

        每个 Commit 保存为一个 Markdown 文件，文件名格式为
        {短sha}-{消息首行}.md。

        Args:
            project_path: 项目本地路径
            commits: Commit 字典列表
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        commits_dir = os.path.join(project_path, "sources", date_dir, "commits")
        os.makedirs(commits_dir, exist_ok=True)

        for commit in commits:
            sha = commit.get("sha", "")
            message = commit.get("message", "")
            # 取消息首行作为标题
            first_line = message.split("\n")[0] if message else "no-message"
            # 构建文件名：短sha-消息首行.md
            short_sha = sha[:7] if sha else "unknown"
            safe_msg = self._sanitize_filename(first_line)
            filename = f"{short_sha}-{safe_msg}.md"
            filepath = os.path.join(commits_dir, filename)

            # 构建 Front Matter
            frontmatter = self._build_frontmatter_yaml({
                "sha": sha,
                "author": commit.get("author", ""),
                "date": commit.get("date", ""),
                "html_url": commit.get("html_url", ""),
            })

            # 组合完整内容（消息全文作为正文）
            content = f"{frontmatter}\n\n{message}"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return date_dir

    def save_community_to_sources(
        self,
        project_path: str,
        stargazers: list[dict],
        forks: list[dict],
        watchers: list[dict],
    ) -> str:
        """将社区数据写入 sources/{date}/community/ 目录（JSON 格式）

        分别保存 stargazers.json、forks.json、watchers.json。

        Args:
            project_path: 项目本地路径
            stargazers: Stargazer 字典列表
            forks: Fork 字典列表
            watchers: Watcher 字典列表
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        community_dir = os.path.join(project_path, "sources", date_dir, "community")
        os.makedirs(community_dir, exist_ok=True)

        # 保存 stargazers
        sg_path = os.path.join(community_dir, "stargazers.json")
        with open(sg_path, "w", encoding="utf-8") as f:
            json.dump(stargazers, f, ensure_ascii=False, indent=2)

        # 保存 forks
        forks_path = os.path.join(community_dir, "forks.json")
        with open(forks_path, "w", encoding="utf-8") as f:
            json.dump(forks, f, ensure_ascii=False, indent=2)

        # 保存 watchers
        wt_path = os.path.join(community_dir, "watchers.json")
        with open(wt_path, "w", encoding="utf-8") as f:
            json.dump(watchers, f, ensure_ascii=False, indent=2)

        return date_dir

    def save_docs_to_sources(
        self,
        project_path: str,
        contributing: str = None,
        code_of_conduct: str = None,
        security: str = None,
        license_info: dict = None,
    ) -> str:
        """将项目文档写入 sources/{date}/ 根目录

        各文档分别保存为对应文件名：
        - CONTRIBUTING.md
        - CODE_OF_CONDUCT.md
        - SECURITY.md
        - LICENSE.json

        Args:
            project_path: 项目本地路径
            contributing: CONTRIBUTING.md 内容，None 时不写入
            code_of_conduct: CODE_OF_CONDUCT.md 内容，None 时不写入
            security: SECURITY.md 内容，None 时不写入
            license_info: 许可证信息字典，None 时不写入
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        sources_dir = os.path.join(project_path, "sources", date_dir)
        os.makedirs(sources_dir, exist_ok=True)

        # 保存 CONTRIBUTING.md
        if contributing:
            filepath = os.path.join(sources_dir, "CONTRIBUTING.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(contributing)

        # 保存 CODE_OF_CONDUCT.md
        if code_of_conduct:
            filepath = os.path.join(sources_dir, "CODE_OF_CONDUCT.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code_of_conduct)

        # 保存 SECURITY.md
        if security:
            filepath = os.path.join(sources_dir, "SECURITY.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(security)

        # 保存 LICENSE.json
        if license_info:
            filepath = os.path.join(sources_dir, "LICENSE.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(license_info, f, ensure_ascii=False, indent=2)

        return date_dir

    def save_branches_to_sources(self, project_path: str, branches: list[dict]) -> str:
        """将分支数据写入 sources/{date}/branches.json

        Args:
            project_path: 项目本地路径
            branches: Branch 字典列表
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        sources_dir = os.path.join(project_path, "sources", date_dir)
        os.makedirs(sources_dir, exist_ok=True)

        filepath = os.path.join(sources_dir, "branches.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(branches, f, ensure_ascii=False, indent=2)

        return date_dir

    def save_readme_to_sources(self, project_path: str, readme_content: str) -> str:
        """将 README 写入 sources/{date}/README.md

        Args:
            project_path: 项目本地路径
            readme_content: README 文本内容
        Returns:
            写入的日期目录名
        """
        date_dir = self._get_date_dir()
        sources_dir = os.path.join(project_path, "sources", date_dir)
        os.makedirs(sources_dir, exist_ok=True)

        filepath = os.path.join(sources_dir, "README.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(readme_content)

        return date_dir

    # ================================================================
    # 一键抓取方法
    # ================================================================

    async def fetch_all_resources(
        self,
        owner: str,
        repo: str,
        project_path: str,
        priority: str = "P0",
    ) -> dict:
        """按优先级一键抓取所有资源

        根据优先级参数决定抓取范围：
        - P0：Issues + Issue Comments + Releases
        - P1：P0 + Pull Requests + CONTRIBUTING + CODE_OF_CONDUCT + License
        - P2：P1 + Security + Commits + Stargazers + Forks + Watchers + Branches

        抓取结果自动写入 sources/{date}/ 目录。
        返回结果字典包含每种资源的 status/count/error 信息。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            project_path: 项目本地路径
            priority: 抓取优先级，"P0"/"P1"/"P2"
        Returns:
            结果字典，格式为::
                {
                    "date_dir": "2026-05-14",
                    "priority": "P0",
                    "results": {
                        "issues": {"status": "ok", "count": 42, "error": null},
                        "releases": {"status": "ok", "count": 5, "error": null},
                        ...
                    }
                }
        """
        results: dict = {}
        priority = priority.upper()

        # ---------- P0 资源 ----------

        # Issues
        issues_result = await self._safe_fetch(
            "issues", self.fetch_issues, owner, repo
        )
        results["issues"] = issues_result
        if issues_result["status"] == "ok" and issues_result["data"]:
            self.save_issues_to_sources(project_path, issues_result["data"])
        # 清理临时数据，减少内存占用
        issues_result.pop("data", None)

        # Releases
        releases_result = await self._safe_fetch(
            "releases", self.fetch_releases, owner, repo
        )
        results["releases"] = releases_result
        if releases_result["status"] == "ok" and releases_result["data"]:
            self.save_releases_to_sources(project_path, releases_result["data"])
        releases_result.pop("data", None)

        # ---------- P1 资源 ----------

        if priority in ("P1", "P2"):
            # Pull Requests
            prs_result = await self._safe_fetch(
                "pull_requests", self.fetch_pull_requests, owner, repo
            )
            results["pull_requests"] = prs_result
            if prs_result["status"] == "ok" and prs_result["data"]:
                self.save_prs_to_sources(project_path, prs_result["data"])
            prs_result.pop("data", None)

            # CONTRIBUTING.md
            contributing_result = await self._safe_fetch_doc(
                "contributing", self.fetch_contributing, owner, repo
            )
            results["contributing"] = contributing_result

            # CODE_OF_CONDUCT.md
            coc_result = await self._safe_fetch_doc(
                "code_of_conduct", self.fetch_code_of_conduct, owner, repo
            )
            results["code_of_conduct"] = coc_result

            # License
            license_result = await self._safe_fetch(
                "license", self.fetch_license, owner, repo
            )
            results["license"] = license_result

            # 保存项目文档
            contributing_data = contributing_result.pop("data", None)
            coc_data = coc_result.pop("data", None)
            license_data = license_result.pop("data", None)
            self.save_docs_to_sources(
                project_path,
                contributing=contributing_data,
                code_of_conduct=coc_data,
                license_info=license_data,
            )

        # ---------- P2 资源 ----------

        if priority == "P2":
            # Security
            security_result = await self._safe_fetch_doc(
                "security", self.fetch_security, owner, repo
            )
            results["security"] = security_result

            # Commits
            commits_result = await self._safe_fetch(
                "commits", self.fetch_commits, owner, repo
            )
            results["commits"] = commits_result
            if commits_result["status"] == "ok" and commits_result["data"]:
                self.save_commits_to_sources(project_path, commits_result["data"])
            commits_result.pop("data", None)

            # Stargazers
            stargazers_result = await self._safe_fetch(
                "stargazers", self.fetch_stargazers, owner, repo
            )
            results["stargazers"] = stargazers_result

            # Forks
            forks_result = await self._safe_fetch(
                "forks", self.fetch_forks, owner, repo
            )
            results["forks"] = forks_result

            # Watchers
            watchers_result = await self._safe_fetch(
                "watchers", self.fetch_watchers, owner, repo
            )
            results["watchers"] = watchers_result

            # Branches
            branches_result = await self._safe_fetch(
                "branches", self.fetch_branches, owner, repo
            )
            results["branches"] = branches_result

            # 保存社区数据
            sg_data = stargazers_result.pop("data", [])
            forks_data = forks_result.pop("data", [])
            wt_data = watchers_result.pop("data", [])
            self.save_community_to_sources(project_path, sg_data, forks_data, wt_data)

            # 保存分支数据
            if branches_result["status"] == "ok":
                branches_data = branches_result.pop("data", [])
                self.save_branches_to_sources(project_path, branches_data)

            # 保存 SECURITY.md 到项目文档
            security_data = security_result.pop("data", None)
            # 需要单独保存，因为 save_docs_to_sources 可能已被 P1 调用
            if security_data:
                date_dir = self._get_date_dir()
                sources_dir = os.path.join(project_path, "sources", date_dir)
                os.makedirs(sources_dir, exist_ok=True)
                filepath = os.path.join(sources_dir, "SECURITY.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(security_data)

        # 获取最终日期目录
        date_dir = self._get_date_dir()

        return {
            "date_dir": date_dir,
            "priority": priority,
            "results": results,
        }

    async def _safe_fetch(self, name: str, fetch_fn, *args, **kwargs) -> dict:
        """安全执行列表类型抓取方法，捕获异常

        统一包装抓取方法的异常处理，确保单个资源抓取失败
        不会影响其他资源的抓取流程。

        Args:
            name: 资源名称（用于日志标识）
            fetch_fn: 抓取方法（异步函数）
            *args: 传递给抓取方法的位置参数
            **kwargs: 传递给抓取方法的关键字参数
        Returns:
            结果字典，包含 status/count/error/data 字段
        """
        try:
            data = await fetch_fn(*args, **kwargs)
            count = len(data) if isinstance(data, list) else (1 if data else 0)
            return {
                "status": "ok",
                "count": count,
                "error": None,
                "data": data,
            }
        except Exception as exc:
            return {
                "status": "error",
                "count": 0,
                "error": str(exc),
                "data": None,
            }

    async def _safe_fetch_doc(self, name: str, fetch_fn, *args, **kwargs) -> dict:
        """安全执行文档类型抓取方法，捕获异常

        与 _safe_fetch 类似，但针对返回字符串或字典的文档抓取方法，
        count 逻辑不同：有内容为 1，无内容为 0。

        Args:
            name: 资源名称（用于日志标识）
            fetch_fn: 抓取方法（异步函数）
            *args: 传递给抓取方法的位置参数
            **kwargs: 传递给抓取方法的关键字参数
        Returns:
            结果字典，包含 status/count/error/data 字段
        """
        try:
            data = await fetch_fn(*args, **kwargs)
            count = 1 if data else 0
            return {
                "status": "ok",
                "count": count,
                "error": None,
                "data": data,
            }
        except Exception as exc:
            return {
                "status": "error",
                "count": 0,
                "error": str(exc),
                "data": None,
            }
