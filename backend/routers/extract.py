"""
文件提取路由模块

提供压缩包上传解析、确认添加/覆盖项目、批量提取 GitHub 链接等功能。

端点列表：
- POST /api/extract-zip       — 上传压缩包解析
- POST /api/extract-zip/apply — 确认添加/覆盖项目
- POST /api/extract/batch     — 批量提取 GitHub 链接
"""

import os
import re
import json
import shutil
import asyncio
import logging
import zipfile
import tempfile
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from pydantic import BaseModel

from backend.services.project_service import (
    create_project,
    update_project,
    get_project_by_id,
    get_project_by_normalized_github_url,
    update_github_fetch_status,
)
from backend.config import TEMP_DIR, PROJECTS_ROOT, MAX_UPLOAD_SIZE

router = APIRouter(tags=["extract"])

_executor = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _parse_git_config(config_content: str) -> dict:
    """解析 .git/config 文件，提取 remote URL

    Args:
        config_content: .git/config 文件内容
    Returns:
        包含 originUrl 和 allRemotes 的字典
    """
    remotes = []
    current_remote = None

    for line in config_content.split("\n"):
        remote_match = re.match(r'^\s*\[remote\s+"([^"]+)"\]\s*$', line)
        if remote_match:
            current_remote = remote_match.group(1)
            continue
        if current_remote:
            url_match = re.match(r'^\s*url\s*=\s*(.+)$', line)
            if url_match:
                remotes.append({"name": current_remote, "url": url_match.group(1).strip()})

    origin_url = next((r["url"] for r in remotes if r["name"] == "origin"), None)
    return {"originUrl": origin_url, "allRemotes": remotes}


def _normalize_to_https_url(url: str) -> str:
    """将 git remote URL 标准化为 https 格式

    Args:
        url: 原始 git remote URL
    Returns:
        https 格式的 URL
    """
    if url.startswith("git@github.com:"):
        return url.replace("git@github.com:", "https://github.com/")
    if url.startswith("git://"):
        return url.replace("git://", "https://")
    if not url.startswith("http"):
        return f"https://{url}"
    return url


def _parse_git_head(head_content: str, extract_dir: str) -> Optional[str]:
    """解析 .git/HEAD 文件，获取当前 commit SHA

    Args:
        head_content: .git/HEAD 文件内容
        extract_dir: 解压目录路径
    Returns:
        commit SHA，解析失败返回 None
    """
    trimmed = head_content.strip()
    # detached HEAD：直接指向 commit SHA
    if re.match(r"^[0-9a-f]{40}$", trimmed):
        return trimmed
    # HEAD 指向引用
    ref_match = re.match(r"^ref:\s*(.+)$", trimmed)
    if ref_match:
        ref_path = ref_match.group(1)
        ref_file_path = os.path.join(extract_dir, ".git", ref_path)
        if os.path.exists(ref_file_path):
            ref_content = open(ref_file_path, "r", encoding="utf-8").read().strip()
            if re.match(r"^[0-9a-f]{40}$", ref_content):
                return ref_content
        # 尝试从 packed-refs 读取
        packed_refs_path = os.path.join(extract_dir, ".git", "packed-refs")
        if os.path.exists(packed_refs_path):
            packed_refs = open(packed_refs_path, "r", encoding="utf-8").read()
            for line in packed_refs.split("\n"):
                if line.endswith(ref_path):
                    sha = line.split()[0]
                    if re.match(r"^[0-9a-f]{40}$", sha):
                        return sha
    return None


def _get_tags(extract_dir: str) -> List[str]:
    """获取 .git/refs/tags/ 下的所有 tag

    Args:
        extract_dir: 解压目录路径
    Returns:
        tag 名称列表
    """
    tags_dir = os.path.join(extract_dir, ".git", "refs", "tags")
    if not os.path.exists(tags_dir):
        return []
    try:
        return [f for f in os.listdir(tags_dir) if not f.startswith(".")]
    except Exception:
        return []


def _find_git_dir(root_dir: str) -> Optional[str]:
    """递归查找 .git 目录

    Args:
        root_dir: 搜索根目录
    Returns:
        包含 .git 目录的路径，未找到返回 None
    """
    git_dir = os.path.join(root_dir, ".git")
    if os.path.exists(git_dir):
        return root_dir
    try:
        for entry in os.listdir(root_dir):
            entry_path = os.path.join(root_dir, entry)
            if os.path.isdir(entry_path) and not entry.startswith(".") and entry != "node_modules":
                found = _find_git_dir(entry_path)
                if found:
                    return found
    except Exception:
        pass
    return None


def _extract_description_from_readme(content: str) -> Optional[str]:
    """从 README 内容中提取项目描述

    取第一个非标题、非空行、非图片链接的段落，截断至 200 字符

    Args:
        content: README 文件全文
    Returns:
        提取的描述文本，无有效内容时返回 None
    """
    if not content or not content.strip():
        return None
    for line in content.split("\n"):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#") or trimmed.startswith("![") or trimmed.startswith("[!["):
            continue
        if trimmed.startswith("---") or trimmed.startswith("```") or trimmed.startswith("|"):
            continue
        if re.match(r"^<[a-zA-Z]", trimmed):
            continue
        if trimmed.startswith("> "):
            sub = trimmed[2:].strip()
            if 0 < len(sub) <= 200:
                return sub
            if len(sub) > 200:
                return sub[:200] + "..."
            continue
        # 清理 Markdown 语法
        cleaned = re.sub(r"<[^>]+>", "", trimmed)
        cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
        cleaned = re.sub(r"\*([^*]*)\*", r"\1", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        if len(cleaned) <= 200:
            return cleaned
        return cleaned[:200] + "..."
    return None


def _parse_github_url(url: str) -> Optional[dict]:
    """解析 GitHub URL 获取 owner 和 repo

    Args:
        url: GitHub 仓库 URL
    Returns:
        包含 owner 和 repo 的字典，解析失败返回 None
    """
    patterns = [
        r"^https?://github\.com/([^/]+)/([^/?]+?)(?:\.git)?(?:/.*)?$",
        r"^git@github\.com:([^/]+)/([^/?]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return {"owner": match.group(1), "repo": match.group(2).replace(".git", "")}
    return None


# ---------------------------------------------------------------------------
# 路由处理
# ---------------------------------------------------------------------------

@router.post("/api/extract-zip")
async def extract_zip(file: UploadFile = File(...)):
    """上传压缩包解析

    接收 .zip 或 .7z 文件，解压到临时目录，查找 .git 目录提取信息，
    返回解析结果。

    Args:
        file: 上传的压缩包文件
    Returns:
        解析结果，包含项目信息、版本信息、重复检测等
    """
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="未选择文件")

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail="压缩包超过 1GB 限制")

        is_zip = file.filename.endswith(".zip")
        is_7z = file.filename.endswith(".7z")
        if not is_zip and not is_7z:
            raise HTTPException(status_code=400, detail="仅支持 .zip 和 .7z 格式的压缩包")

        import time as _time
        import random as _random
        temp_id = f"upload-{int(_time.time())}-{_random.randint(0, 0xFFFFFF):08x}"
        temp_dir = os.path.join(TEMP_DIR, temp_id)
        os.makedirs(temp_dir, exist_ok=True)

        # 保存上传文件
        ext = ".7z" if is_7z else ".zip"
        temp_archive_path = os.path.join(temp_dir, f"upload{ext}")
        with open(temp_archive_path, "wb") as f:
            f.write(content)

        # 解压
        try:
            if is_zip:
                with zipfile.ZipFile(temp_archive_path, "r") as zf:
                    zf.extractall(temp_dir)
            else:
                # 7z 格式需要系统安装 7-Zip
                sevenz_path = os.path.join(
                    os.environ.get("ProgramFiles", "C:\\Program Files"),
                    "7-Zip", "7z.exe"
                )
                if not os.path.exists(sevenz_path):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise HTTPException(status_code=400, detail="7z 格式需要系统安装 7-Zip")
                import subprocess
                subprocess.run(
                    [sevenz_path, "x", temp_archive_path, f"-o{temp_dir}", "-y"],
                    timeout=300000,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=True,
                )
            # 删除压缩包文件
            os.unlink(temp_archive_path)
        except HTTPException:
            raise
        except Exception as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"解压失败：{str(err)}")

        git_dir = _find_git_dir(temp_dir)
        project_root = git_dir or temp_dir
        try:
            temp_entries = [e for e in os.listdir(temp_dir) if not e.startswith(".")]
            if len(temp_entries) == 1:
                entry_path = os.path.join(temp_dir, temp_entries[0])
                if os.path.isdir(entry_path):
                    project_root = entry_path
        except Exception:
            pass

        # 提取信息
        github_url = None
        commit_sha = None
        tags = []
        package_version = None
        package_description = None
        readme_url = None

        if git_dir:
            # 解析 .git/config
            git_config_path = os.path.join(git_dir, ".git", "config")
            if os.path.exists(git_config_path):
                config_content = open(git_config_path, "r", encoding="utf-8").read()
                result = _parse_git_config(config_content)
                origin_url = result["originUrl"]
                if origin_url:
                    github_url = _normalize_to_https_url(origin_url)
                elif result["allRemotes"]:
                    for remote in result["allRemotes"]:
                        if "github.com" in remote["url"]:
                            github_url = _normalize_to_https_url(remote["url"])
                            break

            # 解析 .git/HEAD
            git_head_path = os.path.join(git_dir, ".git", "HEAD")
            if os.path.exists(git_head_path):
                head_content = open(git_head_path, "r", encoding="utf-8").read()
                commit_sha = _parse_git_head(head_content, git_dir)

            # 获取 tags
            tags = _get_tags(git_dir)

        # 解析 package.json（在项目根目录中查找，不依赖 .git 目录）
        pkg_path = os.path.join(project_root, "package.json")
        if os.path.exists(pkg_path):
            try:
                pkg = json.load(open(pkg_path, "r", encoding="utf-8"))
                package_version = pkg.get("version")
                package_description = pkg.get("description")
            except Exception:
                pass

        # 确定版本类型
        version_type = "unknown"
        version_info_str = None
        if tags:
            version_type = "tag"
            version_info_str = tags[-1]
        elif commit_sha:
            version_type = "commit"
            version_info_str = commit_sha[:7]
        elif package_version:
            version_info_str = f"v{package_version}"

        # 清理 GitHub URL
        if github_url and github_url.endswith(".git"):
            github_url = github_url[:-4]

        # 解析 GitHub URL 获取远程信息
        repo_info = None
        version_info = {
            "versionType": "unknown",
            "latestVersion": None,
            "commitSha": None,
            "commitDate": None,
            "downloadUrl": None,
        }
        readme_content = None
        existing_project = None
        project_name = None

        if github_url:
            parsed = _parse_github_url(github_url)
            if parsed:
                owner, repo_name = parsed["owner"], parsed["repo"]
                project_name = repo_name

                # 调用 GitHub API 补全信息
                token = os.environ.get("GITHUB_TOKEN")
                headers = {"Accept": "application/vnd.github.v3+json"}
                if token:
                    headers["Authorization"] = f"token {token}"

                try:
                    from backend.routers.projects import _detect_system_proxy
                    _proxy = _detect_system_proxy()
                    _ck = {"timeout": 15}
                    if _proxy:
                        _ck["proxy"] = _proxy
                    async with httpx.AsyncClient(**_ck) as client:
                        # 获取仓库信息
                        repo_resp = await client.get(
                            f"https://api.github.com/repos/{owner}/{repo_name}",
                            headers=headers,
                        )
                        if repo_resp.status_code == 200:
                            repo_info = repo_resp.json()

                        # 获取最新 release
                        release_resp = await client.get(
                            f"https://api.github.com/repos/{owner}/{repo_name}/releases/latest",
                            headers=headers,
                        )
                        if release_resp.status_code == 200:
                            release_data = release_resp.json()
                            if release_data.get("tag_name"):
                                version_info = {
                                    "versionType": "release",
                                    "latestVersion": release_data["tag_name"],
                                    "commitSha": release_data.get("target_commitish"),
                                    "commitDate": None,
                                    "downloadUrl": release_data.get("zipball_url") or release_data.get("tarball_url"),
                                }
                        else:
                            # 获取 tags
                            tags_resp = await client.get(
                                f"https://api.github.com/repos/{owner}/{repo_name}/tags",
                                headers=headers,
                            )
                            if tags_resp.status_code == 200:
                                tags_data = tags_resp.json()
                                if isinstance(tags_data, list) and tags_data:
                                    version_info = {
                                        "versionType": "tag",
                                        "latestVersion": tags_data[0]["name"],
                                        "commitSha": tags_data[0].get("commit", {}).get("sha"),
                                        "commitDate": None,
                                        "downloadUrl": f"https://github.com/{owner}/{repo_name}/archive/refs/tags/{tags_data[0]['name']}.zip",
                                    }
                            else:
                                # 获取最新 commit
                                commits_resp = await client.get(
                                    f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=1",
                                    headers=headers,
                                )
                                if commits_resp.status_code == 200:
                                    commits_data = commits_resp.json()
                                    if isinstance(commits_data, list) and commits_data:
                                        version_info = {
                                            "versionType": "commit",
                                            "latestVersion": None,
                                            "commitSha": commits_data[0]["sha"],
                                            "commitDate": commits_data[0].get("commit", {}).get("author", {}).get("date"),
                                            "downloadUrl": None,
                                        }

                        # 获取 README
                        readme_resp = await client.get(
                            f"https://ghfast.top/https://raw.githubusercontent.com/{owner}/{repo_name}/HEAD/README.md",
                            timeout=10,
                        )
                        if readme_resp.status_code == 200:
                            readme_content = readme_resp.text

                    # 查询数据库是否存在重复项目
                    existing_project = get_project_by_normalized_github_url(github_url)

                except Exception:
                    pass

        # 从解压目录读取 README（优先 project_root，回退 temp_dir）
        if not readme_content:
            readme_candidates = ["README.md", "readme.md", "README", "readme"]
            search_dirs = [project_root, temp_dir] if project_root != temp_dir else [temp_dir]
            for d in search_dirs:
                if not d:
                    continue
                for candidate in readme_candidates:
                    readme_path = os.path.join(d, candidate)
                    if os.path.exists(readme_path):
                        try:
                            readme_content = open(readme_path, "r", encoding="utf-8").read()
                            break
                        except Exception:
                            pass
                if readme_content:
                    break

        # 将 README 中的相对路径图片转换为 GitHub raw URL
        if readme_content and owner and repo_name:
            from backend.utils.readme_utils import rewrite_readme_image_paths
            readme_content = rewrite_readme_image_paths(readme_content, owner, repo_name)

        # 如果没有项目名，从文件名推断
        if not project_name:
            project_name = file.filename.replace(".zip", "").replace(".7z", "")

        # 构建返回结果
        result = {
            "success": True,
            "githubUrl": repo_info.get("html_url", github_url) if repo_info else github_url,
            "name": (repo_info.get("name") if repo_info else None) or project_name,
            "description": (
                (repo_info.get("description") if repo_info else None)
                or package_description
                or (_extract_description_from_readme(readme_content) if readme_content else None)
            ),
            "readme": readme_content,
            "versionType": (version_info["versionType"] if github_url and version_info["versionType"] != "unknown" else version_type),
            "versionInfo": version_info_str,
            "commitSha": commit_sha or version_info["commitSha"],
            "commitDate": version_info["commitDate"],
            "latestVersion": version_info["latestVersion"],
            "downloadUrl": version_info["downloadUrl"],
            "tempId": temp_id,
            "duplicate": {
                "exists": existing_project is not None,
                "existingProject": existing_project,
                "versionComparison": None,
            },
        }

        return result

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"解析失败：{str(err)}")


class ApplyRequest(BaseModel):
    """确认添加/覆盖项目请求体"""
    tempId: str
    action: str  # "add" 或 "overwrite"
    projectInfo: dict
    archiveFormat: Optional[str] = "zip"
    existingProjectId: Optional[int] = None
    localStoragePath: Optional[str] = None


async def _background_process_after_upload(
    project_id: int, project_name: str, project_path: str
):
    """上传压缩包确认后的后台处理任务

    执行与 clone/pull 一致的后台流程（无 GitHub 资源抓取步骤）：
    1. 构建知识图谱（graphify）
    2. 生成能力报告
    3. 清理 temp 目录

    Args:
        project_id: 项目 ID
        project_name: 项目名称
        project_path: 项目本地存储路径
    """
    from backend.routers.projects import (
        _run_graphify_cmd,
        _remove_dir,
    )

    graphify_ok = False
    source_dir = os.path.join(TEMP_DIR, str(project_id))

    # ---- 步骤1：构建知识图谱 ----
    if os.path.exists(source_dir):
        update_project(project_id, {"workflow_status": "building_graph"})
        try:
            # 从 project_path 推算存储根目录，兼容自定义存储路径
            _bg_projects_root = os.path.dirname(project_path) if project_path else PROJECTS_ROOT
            output_dir = os.path.join(_bg_projects_root, project_name, "graphify-out")

            print(f"[Upload BG] 项目 {project_id} 开始构建知识图谱，输入: {source_dir}，输出: {output_dir}")

            def _run_graphify_bg():
                return _run_graphify_cmd(source_dir, output_dir)

            loop = asyncio.get_event_loop()
            gf_success, node_count, edge_count = await asyncio.wait_for(
                loop.run_in_executor(_executor, _run_graphify_bg),
                timeout=610,
            )

            if gf_success:
                graphify_ok = True
                update_project(project_id, {"graph_path": output_dir})
                print(f"[Upload BG] 项目 {project_id} 知识图谱构建完成: {output_dir}，节点={node_count}，边={edge_count}")
            else:
                print(f"[Upload BG] 项目 {project_id} 知识图谱构建失败，保留 temp 目录供重试")
        except asyncio.TimeoutError:
            print(f"[Upload BG] 项目 {project_id} 知识图谱构建超时（非致命）")
        except Exception as gf_err:
            import traceback
            print(f"[Upload BG Error] 项目 {project_id} 知识图谱构建失败（非致命）: {gf_err}")
            print(traceback.format_exc())
    else:
        print(f"[Upload BG] 项目 {project_id} 跳过知识图谱构建：源码目录不存在 {source_dir}")

    # ---- 步骤2：生成能力报告（upload 没有 github_url） ----
    update_project(project_id, {"workflow_status": "generating_capability"})
    try:
        from backend.services.capability_generator import generate_capability_report
        report_result = await generate_capability_report(project_id)
        if report_result:
            print(f"[Upload BG] 项目 {project_id} 能力报告生成完成")
        else:
            print(f"[Upload BG] 项目 {project_id} 能力报告生成返回空（可能未配置 LLM Key）")
    except Exception as cap_err:
        print(f"[Upload BG Error] 项目 {project_id} 能力报告生成失败（非致命）: {cap_err}")

    # ---- 步骤2.5：根据自动进化设置决定是否自动摄入 ----
    try:
        from backend.services.wiki.ingest import auto_ingest
        from backend.config import GLOBAL_WIKI_DIR, GLOBAL_WIKI_SOURCES_DIR
        from backend.services.capability_generator import _get_llm_config_from_settings
        from backend.routers.wiki import _get_wiki_settings

        _llm_cfg = _get_llm_config_from_settings()
        _wiki_cfg = _get_wiki_settings()
        _auto_ingest_enabled = _wiki_cfg.get("evolution", {}).get("gitAutoIngest", True)

        if not _auto_ingest_enabled:
            print(f"[Upload BG WikiIngest] 项目 {project_id} 跳过自动摄入：Git 变更自动摄入已关闭，请手动刷新知识库")
        elif _llm_cfg.get("apiKey"):
            # 仅处理当前项目的 source 文件，避免旧项目残留文件被误处理
            _src_path = os.path.join(GLOBAL_WIKI_SOURCES_DIR, f"{project_id}.md")
            if os.path.isfile(_src_path):
                print(f"[Upload BG WikiIngest] 项目 {project_id} 触发全局 Wiki ingest: {_src_path}")
                try:
                    written = await auto_ingest(GLOBAL_WIKI_DIR, _src_path, _llm_cfg)
                    print(f"[Upload BG WikiIngest] 项目 {project_id} 全局 Wiki ingest 完成，共生成 {len(written)} 个页面")
                except Exception as single_err:
                    print(f"[Upload BG WikiIngest] 项目 {project_id} ingest 失败: {single_err}")
            else:
                print(f"[Upload BG WikiIngest] 项目 {project_id} 跳过：source 文件不存在 {_src_path}")
        else:
            print(f"[Upload BG WikiIngest] 项目 {project_id} 跳过：未配置 LLM API Key")
    except Exception as ingest_err:
        import traceback as _tb
        print(f"[Upload BG WikiIngest] 项目 {project_id} Wiki ingest 失败（非致命）: {ingest_err}")
        print(_tb.format_exc())

    # ---- 步骤3：清理 temp 目录 ----
    update_project(project_id, {"workflow_status": "cleaning_up"})
    try:
        if os.path.exists(source_dir):
            if graphify_ok:
                _remove_dir(source_dir)
                print(f"[Upload BG] 项目 {project_id} 后台任务完成，已清理 temp 目录")
            else:
                print(f"[Upload BG] 项目 {project_id} graphify 未成功，保留 temp 目录 {source_dir} 供手动重试")
    except Exception as cleanup_err:
        print(f"[Upload BG] 项目 {project_id} 清理 temp 目录失败（非致命）: {cleanup_err}")

    update_project(project_id, {"workflow_status": "done"})


@router.post("/api/extract-zip/apply")
async def apply_extract(body: ApplyRequest):
    """确认添加/覆盖项目

    将临时目录 rename 为 TEMP_DIR/{project_id}/，创建版本压缩包，
    然后触发后台任务：构建知识图谱 → 桥接 → 编译 Wiki → 清理临时文件。
    流程与 clone/pull 一致，但无 GitHub 资源抓取步骤。

    Args:
        body: 包含 tempId、action、projectInfo 等的请求体
    Returns:
        操作结果
    """
    try:
        temp_id = body.tempId
        action = body.action
        project_info = body.projectInfo

        if not temp_id or not action or not project_info:
            raise HTTPException(status_code=400, detail="参数不完整")

        project_name_from_info = project_info.get("name")
        if not project_name_from_info or not project_name_from_info.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")

        temp_dir = os.path.join(TEMP_DIR, temp_id)
        if not os.path.exists(temp_dir):
            raise HTTPException(status_code=400, detail="临时文件已过期，请重新上传")

        projects_root = PROJECTS_ROOT
        # 优先使用用户配置的存储路径
        if body.localStoragePath and body.localStoragePath.strip():
            custom_path = body.localStoragePath.strip().rstrip(os.sep).rstrip("/")
            if os.path.isabs(custom_path):
                projects_root = custom_path

        if action == "add":
            project_dir = os.path.join(projects_root, project_name_from_info)
            os.makedirs(project_dir, exist_ok=True)

            github_url = project_info.get("githubUrl")
            project = create_project({
                "name": project_name_from_info,
                "description": project_info.get("description"),
                "readme": project_info.get("readme"),
                "github_url": github_url or None,
                "local_path": project_dir,
                "version_type": project_info.get("versionType", "unknown"),
                "latest_version": project_info.get("latestVersion"),
                "current_version": project_info.get("versionInfo") or project_info.get("latestVersion"),
                "download_url": project_info.get("downloadUrl"),
                "commit_sha": project_info.get("commitSha"),
                "commit_date": project_info.get("commitDate"),
                "sync_status": "synced" if github_url else "local",
            })

            project_id = project["id"]
            project_name = project_name_from_info

            # 查找项目根目录（优先含 .git 的目录，其次单层子目录）
            git_dir = _find_git_dir(temp_dir)
            source_dir = git_dir or temp_dir
            try:
                temp_entries = [e for e in os.listdir(temp_dir) if not e.startswith(".")]
                if len(temp_entries) == 1:
                    entry_path = os.path.join(temp_dir, temp_entries[0])
                    if os.path.isdir(entry_path):
                        source_dir = entry_path
            except Exception:
                pass

            # 创建版本压缩包
            try:
                version = project_info.get("versionInfo") or project_info.get("latestVersion")
                archive_format = body.archiveFormat or "zip"
                _create_version_archive_simple(source_dir, projects_root, project_name, version, archive_format)
            except Exception as archive_err:
                print(f"[Upload] 创建版本压缩包失败（非致命）: {archive_err}")

            try:
                update_github_fetch_status(project_id, "completed")
            except Exception as fetch_err:
                print(f"[Upload] 更新 GitHub 抓取状态失败（非致命）: {fetch_err}")

            # 将临时目录 rename 为 TEMP_DIR/{project_id}/，供后台 graphify 使用
            graphify_temp_dir = os.path.join(TEMP_DIR, str(project_id))
            try:
                if os.path.exists(graphify_temp_dir):
                    shutil.rmtree(graphify_temp_dir, ignore_errors=True)
                os.rename(temp_dir, graphify_temp_dir)
                print(f"[Upload] 项目 {project_id} 临时目录已重命名为 {graphify_temp_dir}")
            except OSError:
                try:
                    shutil.copytree(temp_dir, graphify_temp_dir)
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"[Upload] 项目 {project_id} 临时目录已复制到 {graphify_temp_dir}（rename 失败，回退 copy）")
                except Exception as copy_err:
                    print(f"[Upload] 移动临时目录失败: {copy_err}")

            # 触发后台任务：graphify → bridge → wiki 编译 → 清理 temp
            try:
                asyncio.create_task(
                    _background_process_after_upload(project_id, project_name, project_dir)
                )
                print(f"[Upload] 已触发项目 {project_id} 的后台知识图谱构建任务")
            except Exception as trigger_err:
                print(f"[Upload] 触发后台任务失败: {trigger_err}")

            return {"success": True, "project": project}

        elif action == "overwrite":
            existing_project_id = body.existingProjectId
            if not existing_project_id:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise HTTPException(status_code=400, detail="缺少已有项目 ID")

            existing_project = get_project_by_id(existing_project_id)
            if not existing_project:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise HTTPException(status_code=404, detail="已有项目不存在")

            project_name = existing_project.get("name", "unknown")
            project_dir = os.path.join(projects_root, project_name)

            # 查找项目根目录
            git_dir = _find_git_dir(temp_dir)
            source_dir = git_dir or temp_dir
            try:
                temp_entries = [e for e in os.listdir(temp_dir) if not e.startswith(".")]
                if len(temp_entries) == 1:
                    entry_path = os.path.join(temp_dir, temp_entries[0])
                    if os.path.isdir(entry_path):
                        source_dir = entry_path
            except Exception:
                pass

            # 创建新版本压缩包
            try:
                version = project_info.get("versionInfo") or project_info.get("latestVersion")
                archive_format = body.archiveFormat or "zip"
                _create_version_archive_simple(source_dir, projects_root, project_name, version, archive_format)
            except Exception as archive_err:
                print(f"[Upload] 创建版本压缩包失败（非致命）: {archive_err}")

            update_project(existing_project_id, {
                "version_type": project_info.get("versionType", "unknown"),
                "latest_version": project_info.get("latestVersion"),
                "current_version": project_info.get("versionInfo") or project_info.get("latestVersion"),
                "commit_sha": project_info.get("commitSha"),
                "commit_date": project_info.get("commitDate"),
                "sync_status": "synced",
                "readme": project_info.get("readme"),
            })

            try:
                update_github_fetch_status(existing_project_id, "completed")
            except Exception as fetch_err:
                print(f"[Upload] 更新 GitHub 抓取状态失败（非致命）: {fetch_err}")

            # 将临时目录 rename 为 TEMP_DIR/{project_id}/
            graphify_temp_dir = os.path.join(TEMP_DIR, str(existing_project_id))
            try:
                if os.path.exists(graphify_temp_dir):
                    shutil.rmtree(graphify_temp_dir, ignore_errors=True)
                os.rename(temp_dir, graphify_temp_dir)
                print(f"[Upload] 项目 {existing_project_id} 临时目录已重命名为 {graphify_temp_dir}")
            except OSError:
                try:
                    shutil.copytree(temp_dir, graphify_temp_dir)
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"[Upload] 项目 {existing_project_id} 临时目录已复制到 {graphify_temp_dir}（rename 失败，回退 copy）")
                except Exception as copy_err:
                    print(f"[Upload] 移动临时目录失败: {copy_err}")

            # 触发后台任务：graphify → bridge → wiki 编译 → 清理 temp
            try:
                asyncio.create_task(
                    _background_process_after_upload(existing_project_id, project_name, project_dir)
                )
                print(f"[Upload] 已触发项目 {existing_project_id} 的后台知识图谱构建任务")
            except Exception as trigger_err:
                print(f"[Upload] 触发后台任务失败: {trigger_err}")

            return {"success": True, "projectId": existing_project_id}

        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="无效的操作类型")

    except HTTPException:
        raise
    except Exception as err:
        import traceback
        print(f"[Apply Error] 操作失败: {err}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"操作失败：{str(err)}")


def _create_version_archive_simple(source_dir: str, projects_root: str,
                                   project_name: str, version: Optional[str],
                                   archive_format: str = "zip") -> Optional[str]:
    """创建版本压缩包（简化版，不依赖 projects 模块的函数）

    Args:
        source_dir: 源代码目录
        projects_root: 项目存储根目录
        project_name: 项目名称
        version: 版本号
        archive_format: 压缩格式
    Returns:
        压缩包路径
    """
    project_dir = os.path.join(projects_root, project_name)
    os.makedirs(project_dir, exist_ok=True)

    version_suffix = f"-{version}" if version else ""
    archive_name = f"{project_name}{version_suffix}.zip"
    archive_path = os.path.join(project_dir, archive_name)

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d != ".git"]
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zf.write(file_path, arcname)

    return archive_path


class BatchExtractRequest(BaseModel):
    """批量提取请求体"""
    urls: Optional[List[str]] = None
    files: Optional[List[dict]] = None
    githubUrls: Optional[List[str]] = None
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None


async def _extract_github_urls_from_image(
    file_data: str,
    file_name: str,
    provider_id: str | None,
    model_id: str | None,
    api_key: str | None,
    base_url: str | None,
) -> tuple[List[str], str]:
    """使用 LLM 视觉能力从图片中提取 GitHub URL

    将图片以 base64 编码发送给多模态 LLM，让其识别并返回图片中的
    GitHub 仓库地址。

    Args:
        file_data: base64 编码的图片 Data URL
        file_name: 图片文件名
        provider_id: LLM 提供商 ID
        model_id: LLM 模型 ID
        api_key: LLM API 密钥
        base_url: LLM API 基础 URL
    Returns:
        (GitHub URL 列表, 错误信息) 元组；成功时错误信息为空字符串
    """
    if not api_key:
        return [], "未配置 LLM API Key，无法识别图片内容。请在「设置 → 模型配置」中为当前选中的提供商填写 API Key。"

    config = {
        "provider": provider_id or "openai",
        "apiKey": api_key,
        "baseUrl": base_url or "",
        "model": model_id or "gpt-4o-mini",
    }

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "请仔细识别这张图片中包含的所有 GitHub 仓库地址（格式如 "
                        "https://github.com/owner/repo 或 github.com/owner/repo）。"
                        "仅返回识别到的 GitHub URL，每行一个，不要输出其他内容。"
                        "如果没有识别到任何 GitHub 地址，请回复：无"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": file_data},
                },
            ],
        },
    ]

    try:
        from backend.services.wiki.llm_client import stream_chat
        result = await stream_chat(
            config=config,
            messages=messages,
            on_token=lambda _: None,
        )

        github_urls = []
        for line in result.strip().split("\n"):
            line = line.strip()
            if not line or line == "无":
                continue
            match = re.search(r'https?://github\.com/[^/\s"\']+\/[^/\s"\']+', line)
            if match:
                github_urls.append(match.group(0))
            elif "github.com/" in line:
                match2 = re.search(r'github\.com/[^/\s"\']+\/[^/\s"\']+', line)
                if match2:
                    github_urls.append(f"https://{match2.group(0)}")

        return github_urls, ""
    except Exception as err:
        err_msg = str(err).lower()
        _logger.error("图片 OCR 提取失败: %s", err, exc_info=True)
        if any(kw in err_msg for kw in ["vision", "image", "multimodal", "visual", "不支持图片", "does not support"]):
            return [], (
                f"当前模型「{model_id or 'gpt-4o-mini'}」不支持图片识别（视觉能力）。"
                "请在「设置 → 模型配置」中切换到支持视觉能力的模型，"
                "如 GPT-4o、Claude 3.5 Sonnet、Gemini Pro 等多模态模型。"
            )
        return [], f"图片识别失败：{str(err)}"


_logger = logging.getLogger("backend.routers.extract")


@router.post("/api/extract/batch")
async def batch_extract(body: BatchExtractRequest):
    """批量提取 GitHub 链接

    统一处理多种输入类型的 GitHub 链接提取：
    - 文章链接（HTTP 抓取）
    - 直接 GitHub URL（解析验证）
    - 图片 OCR 识别（LLM 视觉能力）

    Args:
        body: 批量提取请求体
    Returns:
        统一格式的批量提取结果
    """
    try:
        urls = body.urls or []
        github_urls = body.githubUrls or []
        files = body.files or []

        total_inputs = len(urls) + len(github_urls) + len(files)
        if total_inputs == 0:
            raise HTTPException(status_code=400, detail="未提供任何输入")

        if total_inputs > 50:
            raise HTTPException(status_code=400, detail="输入数量超过限制（最大 50 项）")

        all_results = []
        all_github_urls = []

        # 处理直接 GitHub URL
        for url in github_urls:
            normalized = _normalize_to_https_url(url)
            if "github.com" in normalized:
                all_github_urls.append(normalized)
                all_results.append({
                    "input": url,
                    "type": "github-url",
                    "githubUrls": [normalized],
                    "status": "success",
                })

        # 处理文章链接（简化版：仅提取 URL 中的 GitHub 链接）
        for url in urls:
            github_match = re.search(r'https?://github\.com/[^/\s"\']+\/[^/\s"\']+', url)
            if github_match:
                found_url = github_match.group(0)
                all_github_urls.append(found_url)
                all_results.append({
                    "input": url,
                    "type": "article-url",
                    "githubUrls": [found_url],
                    "status": "success",
                })
            else:
                all_results.append({
                    "input": url,
                    "type": "article-url",
                    "githubUrls": [],
                    "status": "failed",
                    "error": "未找到 GitHub URL",
                })

        # 处理图片文件（LLM 视觉能力 OCR 提取）
        for file_info in files:
            file_data = file_info.get("data", "")
            file_name = file_info.get("name", "image")

            if not file_data:
                all_results.append({
                    "input": file_name,
                    "type": "image",
                    "githubUrls": [],
                    "status": "failed",
                    "error": "图片数据为空",
                })
                continue

            extracted_urls, ocr_error = await _extract_github_urls_from_image(
                file_data=file_data,
                file_name=file_name,
                provider_id=body.providerId,
                model_id=body.modelId,
                api_key=body.apiKey,
                base_url=body.baseUrl,
            )

            if ocr_error:
                all_results.append({
                    "input": file_name,
                    "type": "image",
                    "githubUrls": [],
                    "status": "failed",
                    "error": ocr_error,
                })
            elif extracted_urls:
                all_github_urls.extend(extracted_urls)
                all_results.append({
                    "input": file_name,
                    "type": "image",
                    "githubUrls": extracted_urls,
                    "status": "success",
                })
            else:
                all_results.append({
                    "input": file_name,
                    "type": "image",
                    "githubUrls": [],
                    "status": "failed",
                    "error": "未识别到 GitHub 地址",
                })

        # 去重
        unique_urls = list(dict.fromkeys(all_github_urls))

        # 串行验证 GitHub 仓库
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        verified_repos = []
        for i, url in enumerate(unique_urls):
            parsed = _parse_github_url(url)
            if not parsed:
                continue

            owner, repo = parsed["owner"], parsed["repo"]

            # 限流延迟
            if i > 0:
                await asyncio.sleep(0.5)

            try:
                from backend.routers.projects import _detect_system_proxy
                _proxy2 = _detect_system_proxy()
                _ck2 = {"timeout": 15}
                if _proxy2:
                    _ck2["proxy"] = _proxy2
                async with httpx.AsyncClient(**_ck2) as client:
                    repo_resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}",
                        headers=headers,
                    )
                    if repo_resp.status_code != 200:
                        continue
                    repo_data = repo_resp.json()

                # 检查数据库重复
                existing_project = get_project_by_normalized_github_url(url)

                verified_repos.append({
                    "url": repo_data.get("html_url", url),
                    "name": repo_data.get("name", repo),
                    "description": repo_data.get("description"),
                    "existsInDb": existing_project is not None,
                    "existingProjectId": existing_project.get("id") if existing_project else None,
                    "sources": [],
                })
            except Exception:
                continue

        failed_count = len(unique_urls) - len(verified_repos)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "total": len(unique_urls),
                "success": len(verified_repos),
                "failed": failed_count,
                "results": all_results,
                "repos": verified_repos,
            },
        }

    except HTTPException:
        raise
    except Exception as err:
        return {"code": 500, "message": f"批量提取失败：{str(err)}", "data": None}
