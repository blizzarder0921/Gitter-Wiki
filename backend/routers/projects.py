"""
项目管理路由模块

对应原 Next.js 的 app/api/projects/ 目录，提供项目 CRUD、
git clone、git pull、版本归档等功能。

端点列表：
- GET    /api/projects          — 获取所有项目列表
- POST   /api/projects          — 创建项目
- DELETE /api/projects          — 批量删除项目（query param id=1,2,3）
- GET    /api/projects/{id}     — 获取单个项目
- DELETE /api/projects/{id}     — 删除单个项目
- PATCH  /api/projects/{id}     — 更新项目
- POST   /api/projects/{id}/clone — git clone 项目到本地
- POST   /api/projects/{id}/pull  — git pull 更新
- GET    /api/projects/{id}/archives — 获取版本归档列表
"""

import os
import re
import sys
import json
import time
import asyncio
import shutil
import zipfile
import subprocess
import httpx
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

# Windows 上 asyncio.create_subprocess_exec 不支持，使用线程池执行同步 subprocess
_executor = ThreadPoolExecutor(max_workers=4)

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from backend.services.project_service import (
    get_all_projects,
    get_project_by_id,
    get_project_by_github_url,
    create_project,
    update_project,
    delete_project,
    parse_github_url,
    update_github_fetch_status,
)
from backend.config import PROJECTS_ROOT, TEMP_DIR

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------

class CloneInput(BaseModel):
    """git clone 请求体"""
    proxy: Optional[str] = None
    archiveFormat: Optional[str] = "zip"
    localStoragePath: Optional[str] = None
    gitPath: Optional[str] = None
    cloneMethod: Optional[str] = "https"
    ghPath: Optional[str] = None
    mirrorUrl: Optional[str] = None


class PullInput(BaseModel):
    """git pull 请求体"""
    proxy: Optional[str] = None
    archiveFormat: Optional[str] = "zip"
    gitPath: Optional[str] = None
    cloneMethod: Optional[str] = "https"
    ghPath: Optional[str] = None
    mirrorUrl: Optional[str] = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _detect_system_proxy() -> Optional[str]:
    """从 Windows 注册表检测系统代理设置

    读取 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings
    中的 ProxyEnable 和 ProxyServer，返回 http://host:port 格式的代理地址。

    Returns:
        代理地址字符串，未启用代理时返回 None
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if server:
                    # ProxyServer 可能是 "host:port" 或 "http=host:port;https=host:port" 格式
                    # 提取第一个有效的 host:port
                    if "=" in server:
                        # 格式: "http=127.0.0.1:7897;https=127.0.0.1:7897"
                        # 优先取 https 对应的地址，其次取 http，最后取第一个
                        for prefix in ("https=", "http=", "socks="):
                            for part in server.split(";"):
                                part = part.strip()
                                if part.startswith(prefix):
                                    return "http://" + part.split("=", 1)[1]
                        # 兜底：取第一个分号前的部分
                        first = server.split(";")[0].strip()
                        if first:
                            return "http://" + first.split("=", 1)[-1]
                    else:
                        return "http://" + server
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return None


def _get_proxy_env(proxy: Optional[str] = None) -> dict:
    """构造 git 命令的代理环境变量

    优先使用显式传入的 proxy 参数；若未提供则自动检测 Windows 系统代理。
    git 不读取 Windows 系统代理注册表，需要通过环境变量 http_proxy/https_proxy 传递。
    同时设置 git 命令行参数跳过 SSL 验证，解决 Windows schannel TLS 握手失败问题。

    Args:
        proxy: 显式代理地址，如 http://127.0.0.1:7890；为 None 时自动检测系统代理
    Returns:
        环境变量字典，无可用代理时返回空字典
    """
    effective_proxy = proxy or _detect_system_proxy()
    env_vars = {}
    if effective_proxy:
        env_vars.update({
            "http_proxy": effective_proxy,
            "https_proxy": effective_proxy,
            "HTTP_PROXY": effective_proxy,
            "HTTPS_PROXY": effective_proxy,
        })
    return env_vars


def _is_network_error(err_msg: str) -> bool:
    """判断错误是否为网络连接类错误

    Args:
        err_msg: 错误信息字符串
    Returns:
        是否为网络错误
    """
    keywords = [
        "Could not connect to server",
        "Failed to connect",
        "timed out",
        "Connection refused",
        "Unable to access",
        "port 443",
        "port 80",
        "Network is unreachable",
        "no route to host",
        "TLS connect error",
        "SSL connect error",
        "gnutls_handshake",
        "OpenSSL SSL_connect",
    ]
    return any(kw in err_msg for kw in keywords)


def _is_permission_error(err_msg: str) -> bool:
    """判断错误是否为权限类错误

    Args:
        err_msg: 错误信息字符串
    Returns:
        是否为权限错误
    """
    keywords = [
        "Permission denied",
        "Access is denied",
        "拒绝访问",
        "EACCES",
        "EPERM",
        "could not create work tree",
    ]
    return any(kw in err_msg for kw in keywords)


def _is_tls_error(err_msg: str) -> bool:
    """判断错误是否为 TLS/SSL 握手类错误

    TLS 握手失败通常由以下原因导致：
    1. 国内网络环境下直连 GitHub 被 TLS 干扰/阻断
    2. Git 的 schannel 后端与 GitHub TLS 不兼容
    3. 代理未配置或配置不正确

    Args:
        err_msg: 错误信息字符串
    Returns:
        是否为 TLS 错误
    """
    keywords = [
        "TLS connect error",
        "SSL connect error",
        "gnutls_handshake",
        "OpenSSL SSL_connect",
        "SSL certificate problem",
        "schannel: next InitializeSecurityContext",
        "schannel: failed to receive handshake",
    ]
    return any(kw in err_msg for kw in keywords)


def _resolve_git_executable(git_path: Optional[str] = None) -> tuple[str, list[str]]:
    """解析 Git 可执行文件路径，并返回绿色版 Git 所需的 PATH 附加目录

    优先使用自定义路径（绿色版 Git），未配置时回退到系统 PATH 中的 git。
    自定义路径需指向 git.exe 的完整路径，如 D:\\Tools\\PortableGit\\bin\\git.exe。

    绿色版 Git 的 git.exe 启动时会 fork git-remote-https.exe 等子进程，
    这些子进程位于 mingw64/bin 和 mingw64/libexec/git-core 目录下，
    必须将这些目录加入 PATH，否则子进程无法找到而报错。

    Args:
        git_path: 用户配置的自定义 Git 可执行文件路径，为 None 或空时使用系统 git
    Returns:
        (git_exe_path, extra_path_dirs) 元组：
        - git_exe_path: Git 可执行文件路径
        - extra_path_dirs: 需要追加到 PATH 的目录列表（绿色版 Git 时非空）
    """
    if git_path and git_path.strip():
        path = git_path.strip()
        if os.path.isfile(path):
            extra_dirs = _get_portable_git_path_dirs(path)
            if extra_dirs:
                print(f"[Git] 绿色版 Git 检测到，追加 PATH 目录: {extra_dirs}")
            return path, extra_dirs
        print(f"[Git] 自定义 Git 路径无效（文件不存在）: {path}，回退到系统 git")
    return "git", []


def _get_portable_git_path_dirs(git_exe_path: str) -> list[str]:
    """根据 git.exe 路径推导绿色版 Git 需要追加到 PATH 的目录

    绿色版 Git 目录结构：
      <root>/bin/git.exe
      <root>/cmd/git.exe
      <root>/mingw64/bin/          (curl, libcrypto 等 DLL)
      <root>/mingw64/libexec/git-core/  (git-remote-https.exe 等子命令)

    Args:
        git_exe_path: git.exe 的完整路径
    Returns:
        需要追加到 PATH 的目录绝对路径列表
    """
    dirs: list[str] = []
    git_dir = os.path.dirname(git_exe_path)
    root_dir = os.path.dirname(git_dir)

    if os.path.basename(git_dir).lower() in ("bin", "cmd"):
        mingw_bin = os.path.join(root_dir, "mingw64", "bin")
        git_core = os.path.join(root_dir, "mingw64", "libexec", "git-core")
        if os.path.isdir(mingw_bin):
            dirs.append(mingw_bin)
        if os.path.isdir(git_core):
            dirs.append(git_core)

    return dirs


def _https_url_to_ssh(https_url: str) -> str:
    """将 GitHub HTTPS URL 转换为 SSH URL

    https://github.com/owner/repo.git → git@github.com:owner/repo.git
    https://github.com/owner/repo      → git@github.com:owner/repo.git

    Args:
        https_url: GitHub HTTPS 格式 URL
    Returns:
        SSH 格式 URL
    """
    url = https_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = url.split("github.com/")
    if len(parts) == 2 and parts[1]:
        return f"git@github.com:{parts[1]}.git"
    return https_url


def _detect_ssh_key() -> Optional[str]:
    """检测用户主目录下是否存在 SSH 密钥

    检查 ~/.ssh/ 目录下是否存在 id_rsa、id_ed25519 等常见密钥文件。

    Returns:
        找到的密钥文件路径，未找到时返回 None
    """
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    if not os.path.isdir(ssh_dir):
        return None
    for name in ("id_ed25519", "id_rsa", "id_ecdsa", "id_ecdsa_sk"):
        key_path = os.path.join(ssh_dir, name)
        if os.path.isfile(key_path):
            return key_path
    return None


def _detect_gh_cli(gh_path: Optional[str] = None) -> Optional[str]:
    """检测 GitHub CLI (gh) 是否可用

    优先使用自定义路径，未配置时回退到系统 PATH 中的 gh。

    Args:
        gh_path: 用户配置的自定义 gh 可执行文件路径
    Returns:
        gh 可执行文件路径，未找到时返回 None
    """
    exe = gh_path and gh_path.strip()
    if exe and os.path.isfile(exe):
        return exe
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            first_line = result.stdout.strip().split("\n")[0]
            print(f"[Git] 检测到系统 GitHub CLI: {first_line}")
            return "gh"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _build_mirror_url(clone_url: str, mirror_url: str) -> str:
    """将 GitHub URL 转换为镜像加速 URL

    支持两种镜像格式：
    - 前缀型：mirror_url + 原始URL，如 https://ghproxy.com/https://github.com/xxx/yyy.git
    - 替换型：将 github.com 替换为镜像域名，如 https://hub.fastgit.xyz/xxx/yyy.git

    Args:
        clone_url: 原始 GitHub HTTPS URL
        mirror_url: 镜像地址（前缀或替换域名）
    Returns:
        转换后的镜像 URL
    """
    mirror = mirror_url.strip().rstrip("/")
    if not mirror:
        return clone_url

    # 前缀型：以 http 开头且包含完整 URL 前缀（如 https://ghproxy.com/）
    if mirror.startswith("http"):
        return f"{mirror}/{clone_url}"

    # 替换型：仅域名（如 hub.fastgit.xyz），替换 github.com
    return clone_url.replace("github.com", mirror)


def _build_clone_cmd(
    clone_method: str,
    git_exe: str,
    clone_url: str,
    temp_dir: str,
    proxy: Optional[str] = None,
    gh_exe: Optional[str] = None,
    mirror_url: Optional[str] = None,
) -> list[str]:
    """根据克隆方式构造不同的 clone 命令

    支持四种克隆方式：
    - https: 使用 git clone + SSL/代理配置（默认）
    - ssh: 将 HTTPS URL 转换为 SSH URL，无需代理和 SSL 配置
    - gh_cli: 使用 gh repo clone，自动处理认证
    - mirror: 通过 GitHub 镜像加速站点克隆，无需代理

    Args:
        clone_method: 克隆方式（https/ssh/gh_cli/mirror）
        git_exe: git 可执行文件路径
        clone_url: 克隆 URL（HTTPS 格式）
        temp_dir: 目标目录
        proxy: 代理地址（仅 https 方式使用）
        gh_exe: gh 可执行文件路径（仅 gh_cli 方式使用）
        mirror_url: 镜像加速地址（仅 mirror 方式使用）
    Returns:
        命令参数列表
    """
    if clone_method == "ssh":
        ssh_url = _https_url_to_ssh(clone_url)
        print(f"[Clone] 使用 SSH 方式克隆: {ssh_url}")
        return [git_exe, "clone", "-c", "core.longPaths=true", "--quiet", ssh_url, temp_dir]

    if clone_method == "gh_cli":
        owner_repo = clone_url.rstrip("/").rstrip(".git").split("github.com/")[-1]
        gh = gh_exe or "gh"
        print(f"[Clone] 使用 GitHub CLI 克隆: {owner_repo} (gh={gh})")
        return [gh, "repo", "clone", owner_repo, temp_dir, "--", "-c", "core.longPaths=true", "--quiet"]

    if clone_method == "mirror":
        effective_mirror = mirror_url or "https://ghproxy.com"
        mirrored_url = _build_mirror_url(clone_url, effective_mirror)
        print(f"[Clone] 使用镜像加速克隆: {mirrored_url}")
        return [git_exe, "clone", "-c", "http.sslVerify=false", "-c", "core.longPaths=true", "--quiet", mirrored_url, temp_dir]

    # 默认 https 方式：加长路径支持 + 强制 OpenSSL 后端
    # Windows 上 Git 默认使用 schannel SSL 后端，通过代理访问 GitHub 时
    # schannel 的 TLS 握手经常失败，强制切换到 openssl 后端解决此问题。
    cmd = [git_exe, "clone", "-c", "core.longPaths=true", "-c", "http.sslBackend=openssl"]
    effective_proxy = proxy or _detect_system_proxy()
    if effective_proxy:
        cmd += ["-c", f"http.proxy={effective_proxy}", "-c", f"https.proxy={effective_proxy}"]
    cmd += ["--quiet", clone_url, temp_dir]
    return cmd


def _kill_proc_tree(proc):
    """杀掉进程及其子进程树（Windows 兼容）

    在 Windows 上，subprocess.Popen.terminate() 只杀父进程，git 会产生
    git-remote-https 等子进程继续运行并锁定文件。需要杀掉整个进程树。

    Args:
        proc: subprocess.Popen 进程对象
    """
    try:
        if os.name == "nt":
            # Windows: 使用 taskkill /T 杀进程树
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                proc.terminate()
    except Exception:
        # 最后兜底：尝试 terminate
        try:
            proc.terminate()
        except Exception:
            pass


def _kill_git_processes_for_dir(dir_path: str):
    """杀掉可能残留的 git 进程，释放对临时目录的文件锁

    当 git clone 因超时或异常中断时，git 子进程可能仍在后台运行并
    锁定临时目录中的文件，导致 _remove_dir 无法删除目录。
    此函数强制终止所有 git 进程以释放文件锁。

    注意：这会杀掉所有 git.exe 进程，但 Gitter 场景下 git 进程
    仅由 clone/pull 操作启动，不存在需要保留的 git 进程。

    Args:
        dir_path: 目标目录路径（用于日志输出）
    """
    if os.name != "nt":
        return

    try:
        # 使用 taskkill 杀掉所有 git 进程（/F 强制，/T 包含子进程树）
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "git.exe"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print(f"[KillGit] 已杀掉残留 git 进程（关联目录: {dir_path}）")
    except Exception:
        pass


def _remove_dir(dir_path: str, max_retries: int = 3, delay_ms: int = 500):
    """递归删除目录（带重试机制，兼容 Windows 隐藏文件）

    Windows 上 git clone 遗留的 .git 目录具有隐藏+只读属性，
    shutil.rmtree 可能无法删除。采用多策略删除：
    1. shutil.rmtree + onerror 清除只读属性
    2. Windows 下调用 attrib 清除隐藏/只读属性后重试
    3. Windows 下调用 rd /s /q 系统命令强制删除

    Args:
        dir_path: 目录路径
        max_retries: 最大重试次数
        delay_ms: 重试间隔毫秒
    """
    if not os.path.exists(dir_path):
        return

    def _on_rm_error(func, path, exc_info):
        """shutil.rmtree onerror 回调：清除只读属性后重试删除"""
        import stat
        import errno
        if exc_info[1].errno in (errno.EACCES, errno.EPERM):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
                return
            except OSError:
                pass
        raise

    for i in range(max_retries):
        # 策略1：shutil.rmtree 清除只读属性
        try:
            shutil.rmtree(dir_path, onerror=_on_rm_error)
            if not os.path.exists(dir_path):
                return
        except OSError:
            pass

        # 策略2（Windows）：用 attrib 递归清除隐藏和只读属性后重试 rmtree
        if os.name == "nt":
            try:
                subprocess.run(
                    ["attrib", "-R", "-H", "-S", f"{dir_path}\\*.*", "/S", "/D"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                shutil.rmtree(dir_path, ignore_errors=True)
                if not os.path.exists(dir_path):
                    return
            except Exception:
                pass

            # 策略3（Windows）：rd /s /q 系统命令强制删除
            try:
                subprocess.run(
                    ["cmd", "/c", "rd", "/s", "/q", dir_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                if not os.path.exists(dir_path):
                    return
            except Exception:
                pass

        if i < max_retries - 1:
            time.sleep(delay_ms / 1000)

    import traceback
    print(f"[RemoveDir] 删除目录失败（已重试 {max_retries} 次）: {dir_path}")
    traceback.print_exc()


def _cleanup_project_dirs(project: dict):
    """删除项目关联的所有磁盘目录

    清理范围：
    1. data/temp/{project_id}/ — clone 临时目录
    2. data/projects/{project_name}/ — 项目缓存目录（sources/wiki/graph 等）
    3. local_path — git clone 目录（如果与项目缓存目录不同）
    4. graph_path — 知识图谱输出目录（如果与上述目录不同）

    Args:
        project: 项目字典，需包含 id、name、local_path、graph_path 字段
    """
    cleaned = set()

    # 1. 清理 clone 临时目录
    project_id = project.get("id")
    if project_id is not None:
        temp_dir = os.path.join(TEMP_DIR, str(project_id))
        if os.path.isdir(temp_dir):
            try:
                _remove_dir(temp_dir)
                cleaned.add(os.path.normpath(temp_dir))
            except Exception as e:
                print(f"[Cleanup] 删除临时目录失败 {temp_dir}: {e}")

    # 2. 清理项目缓存目录（兼容自定义存储路径）
    project_name = project.get("name")
    if project_name:
        # 优先从 local_path 推算存储根目录
        _existing_path = project.get("local_path", "")
        _cleanup_root = os.path.dirname(_existing_path) if _existing_path and os.path.isabs(_existing_path) else PROJECTS_ROOT
        project_cache_dir = os.path.join(_cleanup_root, project_name)
        if os.path.isdir(project_cache_dir):
            norm = os.path.normpath(project_cache_dir)
            if norm not in cleaned:
                try:
                    _remove_dir(project_cache_dir)
                    cleaned.add(norm)
                except Exception as e:
                    print(f"[Cleanup] 删除项目缓存目录失败 {project_cache_dir}: {e}")

    # 3. 清理本地仓库目录
    local_path = project.get("local_path")
    if local_path and os.path.isdir(local_path):
        norm = os.path.normpath(local_path)
        if norm not in cleaned:
            try:
                _remove_dir(local_path)
                cleaned.add(norm)
            except Exception as e:
                print(f"[Cleanup] 删除本地仓库目录失败 {local_path}: {e}")

    # 4. 清理图谱目录
    graph_path = project.get("graph_path")
    if graph_path and os.path.isdir(graph_path):
        norm = os.path.normpath(graph_path)
        if norm not in cleaned:
            try:
                _remove_dir(graph_path)
                cleaned.add(norm)
            except Exception as e:
                print(f"[Cleanup] 删除图谱目录失败 {graph_path}: {e}")

    # 5. 清理全局 Wiki sources 中该项目的报告文件
    if project_id is not None:
        from backend.config import GLOBAL_WIKI_SOURCES_DIR
        _src_file = os.path.join(GLOBAL_WIKI_SOURCES_DIR, f"{project_id}.md")
        if os.path.isfile(_src_file):
            try:
                os.remove(_src_file)
                print(f"[Cleanup] 已删除全局 Wiki source 文件: {_src_file}")
            except Exception as e:
                print(f"[Cleanup] 删除 source 文件失败 {_src_file}: {e}")


def _read_readme_from_dir(dir_path: str) -> Optional[str]:
    """从本地目录读取最新 README

    Args:
        dir_path: 项目目录路径
    Returns:
        README 内容，无则返回 None
    """
    candidates = ["README.md", "readme.md", "README", "readme", "README.zh-CN.md"]
    for name in candidates:
        p = os.path.join(dir_path, name)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return None


def _is_archive_file(filename: str) -> bool:
    """判断文件名是否为压缩包格式

    Args:
        filename: 文件名
    Returns:
        是否为压缩包
    """
    lower = filename.lower()
    return (
        lower.endswith(".zip")
        or lower.endswith(".7z")
        or lower.endswith(".rar")
        or lower.endswith(".tar.gz")
        or lower.endswith(".tgz")
        or lower.endswith(".tar.bz2")
        or lower.endswith(".tbz2")
        or lower.endswith(".tar")
    )


def _ensure_project_dir(project_name: str, projects_root: str = None) -> str:
    """确保项目存储目录存在，返回项目目录路径

    Args:
        project_name: 项目名称
        projects_root: 项目存储根目录，为 None 时使用默认 PROJECTS_ROOT
    Returns:
        项目目录的完整路径
    """
    root = projects_root or PROJECTS_ROOT
    os.makedirs(root, exist_ok=True)
    project_dir = os.path.join(root, project_name)
    os.makedirs(project_dir, exist_ok=True)
    return project_dir


def _resolve_projects_root(localStoragePath: str = None) -> str:
    """解析项目存储根目录

    优先使用前端传入的 localStoragePath（用户在设置中配置的存储路径），
    为空或无效时回退到默认 PROJECTS_ROOT。

    Args:
        localStoragePath: 前端设置的自定义存储路径
    Returns:
        实际使用的项目存储根目录
    """
    if localStoragePath and localStoragePath.strip():
        path = localStoragePath.strip().rstrip(os.sep).rstrip("/")
        if os.path.isabs(path):
            return path
    return PROJECTS_ROOT


def _verify_graphify_output(output_dir: str, max_wait: float = 10.0) -> bool:
    """验证 graphify 输出目录是否包含有效的知识图谱文件

    graphify 进程退出后，输出文件可能因磁盘 IO 缓冲还未完全落盘，
    或者 graphify 构建本身失败未生成完整输出。此函数等待并验证
    graph.json 文件存在且非空，确保知识图谱构建真正成功。

    Args:
        output_dir: graphify 输出目录路径
        max_wait: 最大等待秒数，默认 10 秒
    Returns:
        True 表示 graph.json 存在且非空；False 表示验证失败
    """
    graph_json_path = os.path.join(output_dir, "graph.json")
    deadline = time.time() + max_wait

    while time.time() < deadline:
        if os.path.exists(graph_json_path):
            try:
                size = os.path.getsize(graph_json_path)
                if size > 0:
                    # 验证 JSON 可解析且包含 nodes（graphify 0.7 使用 links 而非 edges）
                    with open(graph_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and ("nodes" in data or "links" in data or "edges" in data):
                        return True
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.5)

    print(f"[Graphify Verify] 输出验证失败: {graph_json_path} 不存在或无效")
    return False


def _run_graphify_cmd(source_dir: str, target_output_dir: str) -> tuple:
    """执行 graphify update 命令并迁移输出到目标目录

    graphify 0.7.x 使用 `update <path>` 子命令，输出固定在
    <source_dir>/graphify-out/ 下。此函数封装了：
    1. 执行 `python -m graphify update <source_dir> --force`
    2. 将 <source_dir>/graphify-out/ 迁移到 target_output_dir
    3. 返回 (success, node_count, edge_count)

    Args:
        source_dir: 源代码目录路径
        target_output_dir: 目标输出目录路径（如 data/projects/<name>/graphify-out）
    Returns:
        (success, node_count, edge_count) 元组
    """
    cmd = [sys.executable, "-m", "backend.graphify", "update", source_dir, "--force"]
    print(f"[Graphify] 执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        print("[Graphify] graphify 模块未安装")
        return (False, 0, 0)
    except subprocess.TimeoutExpired:
        print("[Graphify] 构建超时（600秒）")
        return (False, 0, 0)

    # 打印 graphify 的 stdout 和 stderr 以便排查问题
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"[Graphify stdout] {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines()[:20]:
            print(f"[Graphify stderr] {line}")

    if result.returncode != 0:
        err_msg = (result.stderr or "")[:300]
        print(f"[Graphify] 构建失败: {err_msg}")
        return (False, 0, 0)

    # graphify 0.7 输出在 source_dir/graphify-out/ 下
    gf_output = os.path.join(source_dir, "graphify-out")
    if not os.path.exists(gf_output):
        print(f"[Graphify] 输出目录不存在: {gf_output}")
        return (False, 0, 0)

    # 验证输出
    if not _verify_graphify_output(gf_output):
        print(f"[Graphify] 输出验证失败: {gf_output}")
        return (False, 0, 0)

    # 读取节点和边数
    node_count = 0
    edge_count = 0
    graph_json_path = os.path.join(gf_output, "graph.json")
    try:
        with open(graph_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        node_count = len(data.get("nodes", []))
        # graphify 0.7 使用 "links" 作为边字段名（NetworkX json_graph 格式）
        edge_count = len(data.get("edges", data.get("links", [])))
    except Exception:
        pass

    # 迁移输出到目标目录
    if os.path.exists(target_output_dir):
        shutil.rmtree(target_output_dir, ignore_errors=True)
    try:
        shutil.move(gf_output, target_output_dir)
        print(f"[Graphify] 输出已迁移: {gf_output} -> {target_output_dir}")
    except Exception as move_err:
        # move 失败时回退到 copy
        print(f"[Graphify] 迁移失败({move_err})，尝试复制")
        try:
            shutil.copytree(gf_output, target_output_dir)
        except Exception as copy_err:
            print(f"[Graphify] 复制也失败: {copy_err}")
            return (False, node_count, edge_count)

    return (True, node_count, edge_count)


async def _background_fetch_after_clone(
    project_id: int, github_url: str, project_path: str
):
    """clone 完成后的后台处理任务

    执行顺序：Graphify → 能力报告生成 → 清理 temp
    Graphify 只需源码，放在最前面可立即开始。

    Args:
        project_id: 项目 ID
        github_url: GitHub 仓库 URL
        project_path: 项目本地存储路径
    """
    try:
        # ---- 步骤1：构建知识图谱（只需源码） ----
        graphify_ok = False
        source_dir = os.path.join(TEMP_DIR, str(project_id))
        if os.path.exists(source_dir):
            update_project(project_id, {"workflow_status": "building_graph"})
            try:
                project = get_project_by_id(project_id)
                project_name = project.get("name", "unknown") if project else "unknown"
                # 从 project_path 推算存储根目录，兼容自定义存储路径
                _bg_projects_root = os.path.dirname(project_path) if project_path else PROJECTS_ROOT
                output_dir = os.path.join(_bg_projects_root, project_name, "graphify-out")

                print(f"[Graphify] 项目 {project_id} 开始构建知识图谱，输入: {source_dir}，输出: {output_dir}")

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
                    print(f"[Graphify] 项目 {project_id} 知识图谱构建完成: {output_dir}，节点={node_count}，边={edge_count}")
                else:
                    print(f"[Graphify] 项目 {project_id} 构建失败，保留 temp 目录供重试")
            except asyncio.TimeoutError:
                print(f"[Graphify] 项目 {project_id} 构建超时（非致命）")
            except Exception as gf_err:
                import traceback
                print(f"[Graphify Error] 项目 {project_id} 构建失败（非致命）: {gf_err}")
                print(traceback.format_exc())
        else:
            print(f"[Graphify] 项目 {project_id} 跳过：源码目录不存在 {source_dir}")

        # ---- 步骤1.5：使用 LLM 为社区生成语义标签 ----
        if graphify_ok:
            try:
                from backend.services.community_labeler import generate_community_labels
                from backend.services.capability_generator import _get_llm_config_from_settings
                llm_config = _get_llm_config_from_settings()
                if llm_config.get("apiKey"):
                    update_project(project_id, {"workflow_status": "generating_labels"})
                    loop = asyncio.get_event_loop()
                    labels_ok = await asyncio.wait_for(
                        loop.run_in_executor(_executor, generate_community_labels, output_dir, llm_config),
                        timeout=300,
                    )
                    if labels_ok:
                        print(f"[Labels] 项目 {project_id} LLM 社区标签生成完成")
                    else:
                        print(f"[Labels] 项目 {project_id} LLM 社区标签生成未成功（非致命，使用自动标签兜底）")
                else:
                    print(f"[Labels] 项目 {project_id} 未配置 LLM API Key，跳过标签生成（使用自动标签兜底）")
            except asyncio.TimeoutError:
                print(f"[Labels] 项目 {project_id} LLM 标签生成超时（非致命）")
            except Exception as lbl_err:
                print(f"[Labels Error] 项目 {project_id} LLM 标签生成失败（非致命）: {lbl_err}")

        # ---- 步骤2：生成能力报告 ----
        update_project(project_id, {"workflow_status": "generating_capability"})
        try:
            from backend.services.capability_generator import generate_capability_report
            report_result = await generate_capability_report(project_id, github_url)
            if report_result:
                print(f"[Capability] 项目 {project_id} 能力报告生成完成")
            else:
                print(f"[Capability] 项目 {project_id} 能力报告生成返回空（可能未配置 LLM Key）")
        except Exception as cap_err:
            print(f"[Capability Error] 项目 {project_id} 能力报告生成失败（非致命）: {cap_err}")

        # ---- 步骤2.5：根据自动进化设置决定是否自动摄入 ----
        # 当 evolutionGitAutoIngest 为开时，仅对当前项目的 source 文件执行 ingest；
        # 为关时跳过，用户需在全局知识库中手动点击"刷新知识库"按钮触发摄入。
        try:
            from backend.services.wiki.ingest import auto_ingest
            from backend.config import GLOBAL_WIKI_DIR, GLOBAL_WIKI_SOURCES_DIR
            from backend.services.capability_generator import _get_llm_config_from_settings
            from backend.routers.wiki import _get_wiki_settings

            _llm_cfg = _get_llm_config_from_settings()
            _wiki_cfg = _get_wiki_settings()
            _auto_ingest_enabled = _wiki_cfg.get("evolution", {}).get("gitAutoIngest", True)

            if not _auto_ingest_enabled:
                print(f"[WikiIngest] 项目 {project_id} 跳过自动摄入：Git 变更自动摄入已关闭，请手动刷新知识库")
            elif _llm_cfg.get("apiKey"):
                # 仅处理当前项目的 source 文件，避免旧项目残留文件被误处理
                _src_path = os.path.join(GLOBAL_WIKI_SOURCES_DIR, f"{project_id}.md")
                if os.path.isfile(_src_path):
                    print(f"[WikiIngest] 项目 {project_id} 触发全局 Wiki ingest: {_src_path}")
                    try:
                        written = await auto_ingest(GLOBAL_WIKI_DIR, _src_path, _llm_cfg)
                        print(f"[WikiIngest] 项目 {project_id} 全局 Wiki ingest 完成，共生成 {len(written)} 个页面")
                    except Exception as single_err:
                        print(f"[WikiIngest] 项目 {project_id} ingest 失败: {single_err}")
                else:
                    print(f"[WikiIngest] 项目 {project_id} 跳过：source 文件不存在 {_src_path}")
            else:
                print(f"[WikiIngest] 项目 {project_id} 跳过：未配置 LLM API Key")
        except Exception as ingest_err:
            import traceback as _tb
            print(f"[WikiIngest] 项目 {project_id} Wiki ingest 失败（非致命）: {ingest_err}")
            print(_tb.format_exc())

        # ---- 步骤3：清理 temp 目录 ----
        update_project(project_id, {"workflow_status": "cleaning_up"})
        try:
            temp_dir = os.path.join(TEMP_DIR, str(project_id))
            if os.path.exists(temp_dir):
                if graphify_ok:
                    _remove_dir(temp_dir)
                    print(f"[Cleanup] 项目 {project_id} 后台任务完成，已清理 temp 目录")
                else:
                    print(f"[Cleanup] 项目 {project_id} graphify 未成功，保留 temp 目录 {temp_dir} 供手动重试")
        except Exception as cleanup_err:
            print(f"[Cleanup] 项目 {project_id} 清理 temp 目录失败（非致命）: {cleanup_err}")

        update_project(project_id, {"workflow_status": "done"})

    except Exception as e:
        import traceback
        print(f"[Background Error] 项目 {project_id} 后台任务失败: {e}")
        print(traceback.format_exc())
        update_project(project_id, {"workflow_status": "failed"})


async def _background_fetch_after_pull(
    project_id: int, github_url: str, project_path: str
):
    """pull 完成后的后台处理任务

    执行顺序：Graphify → 能力报告生成 → 清理 temp
    Graphify 只需源码，放在最前面可立即开始。

    Args:
        project_id: 项目 ID
        github_url: GitHub 仓库 URL
        project_path: 项目本地存储路径
    """
    try:
        # ---- 步骤1：构建知识图谱（只需源码） ----
        graphify_ok = False
        source_dir = os.path.join(TEMP_DIR, str(project_id))
        if os.path.exists(source_dir):
            update_project(project_id, {"workflow_status": "building_graph"})
            try:
                project = get_project_by_id(project_id)
                project_name_gf = project.get("name", "unknown") if project else "unknown"
                # 从 project_path 推算存储根目录，兼容自定义存储路径
                _bg_projects_root = os.path.dirname(project_path) if project_path else PROJECTS_ROOT
                output_dir = os.path.join(_bg_projects_root, project_name_gf, "graphify-out")

                print(f"[Graphify] 项目 {project_id} 开始构建知识图谱，输入: {source_dir}，输出: {output_dir}")

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
                    print(f"[Graphify] 项目 {project_id} 知识图谱构建完成: {output_dir}，节点={node_count}，边={edge_count}")
                else:
                    print(f"[Graphify] 项目 {project_id} 构建失败，保留 temp 目录供重试")
            except asyncio.TimeoutError:
                print(f"[Graphify] 项目 {project_id} 构建超时（非致命）")
            except Exception as gf_err:
                import traceback
                print(f"[Graphify Error] 项目 {project_id} 构建失败（非致命）: {gf_err}")
                print(traceback.format_exc())
        else:
            print(f"[Graphify] 项目 {project_id} 跳过：源码目录不存在 {source_dir}")

        # ---- 步骤2：生成能力报告 ----
        update_project(project_id, {"workflow_status": "generating_capability"})
        try:
            from backend.services.capability_generator import generate_capability_report
            report_result = await generate_capability_report(project_id, github_url)
            if report_result:
                print(f"[Capability] 项目 {project_id} 能力报告生成完成")
            else:
                print(f"[Capability] 项目 {project_id} 能力报告生成返回空（可能未配置 LLM Key）")
        except Exception as cap_err:
            print(f"[Capability Error] 项目 {project_id} 能力报告生成失败（非致命）: {cap_err}")

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
                print(f"[WikiIngest] 项目 {project_id} 跳过自动摄入：Git 变更自动摄入已关闭，请手动刷新知识库")
            elif _llm_cfg.get("apiKey"):
                # 仅处理当前项目的 source 文件，避免旧项目残留文件被误处理
                _src_path = os.path.join(GLOBAL_WIKI_SOURCES_DIR, f"{project_id}.md")
                if os.path.isfile(_src_path):
                    print(f"[WikiIngest] 项目 {project_id} 触发全局 Wiki ingest: {_src_path}")
                    try:
                        written = await auto_ingest(GLOBAL_WIKI_DIR, _src_path, _llm_cfg)
                        print(f"[WikiIngest] 项目 {project_id} 全局 Wiki ingest 完成，共生成 {len(written)} 个页面")
                    except Exception as single_err:
                        print(f"[WikiIngest] 项目 {project_id} ingest 失败: {single_err}")
                else:
                    print(f"[WikiIngest] 项目 {project_id} 跳过：source 文件不存在 {_src_path}")
            else:
                print(f"[WikiIngest] 项目 {project_id} 跳过：未配置 LLM API Key")
        except Exception as ingest_err:
            import traceback as _tb
            print(f"[WikiIngest] 项目 {project_id} Wiki ingest 失败（非致命）: {ingest_err}")
            print(_tb.format_exc())

        # ---- 步骤3：清理 temp 目录 ----
        update_project(project_id, {"workflow_status": "cleaning_up"})
        try:
            source_dir = os.path.join(TEMP_DIR, str(project_id))
            if os.path.exists(source_dir):
                if graphify_ok:
                    _remove_dir(source_dir)
                    print(f"[Cleanup] 项目 {project_id} 后台任务完成，已清理 temp 目录")
                else:
                    print(f"[Cleanup] 项目 {project_id} graphify 未成功，保留 temp 目录 {source_dir} 供手动重试")
        except Exception as cleanup_err:
            print(f"[Cleanup] 项目 {project_id} 清理 temp 目录失败（非致命）: {cleanup_err}")

        update_project(project_id, {"workflow_status": "done"})

    except Exception as e:
        import traceback
        print(f"[Background Error] 项目 {project_id} 后台任务失败: {e}")
        print(traceback.format_exc())
        update_project(project_id, {"workflow_status": "failed"})


def _create_version_archive(source_dir: str, projects_root: str, project_name: str,
                            version: Optional[str], archive_format: str = "zip") -> Optional[str]:
    """创建版本压缩包

    Args:
        source_dir: 源代码目录
        projects_root: 项目存储根目录
        project_name: 项目名称
        version: 版本号
        archive_format: 压缩格式（zip 或 7z）
    Returns:
        压缩包路径
    """
    project_dir = os.path.join(projects_root, project_name)
    os.makedirs(project_dir, exist_ok=True)

    # 构造压缩包文件名
    version_suffix = f"-{version}" if version else ""
    if archive_format == "7z":
        archive_name = f"{project_name}{version_suffix}.7z"
    else:
        archive_name = f"{project_name}{version_suffix}.zip"
    archive_path = os.path.join(project_dir, archive_name)

    if archive_format == "zip":
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_dir):
                # 跳过 .git 目录
                dirs[:] = [d for d in dirs if d != ".git"]
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, source_dir)
                    zf.write(file_path, arcname)
    else:
        # 7z 格式需要系统安装 7-Zip
        import subprocess
        sevenz_path = os.path.join(
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            "7-Zip", "7z.exe"
        )
        if not os.path.exists(sevenz_path):
            sevenz_path = "7z"
        subprocess.run(
            [sevenz_path, "a", "-t7z", archive_path, f"{source_dir}\\*"],
            timeout=300000,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )

    return archive_path


# ---------------------------------------------------------------------------
# 路由处理
# ---------------------------------------------------------------------------

@router.get("")
def list_projects():
    """获取所有项目列表

    返回格式：裸数组，前端 page.tsx 直接 setProjects(data) 把整个响应当作数组使用。

    Returns:
        项目列表（裸数组，不包裹在对象中）
    """
    try:
        projects = get_all_projects()
        return projects
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("", status_code=201)
def create_project_endpoint(body: dict):
    """创建新项目

    Args:
        body: 项目创建参数，name 为必填
    Returns:
        新创建的项目对象
    """
    try:
        name = body.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        github_url = body.get("github_url")

        # 有 GitHub URL 时检查重复：若已存在则更新信息并返回已有项目
        if github_url:
            existing = get_project_by_github_url(github_url)
            if existing:
                update_fields = {}
                if body.get("description") and body["description"] != existing.get("description"):
                    update_fields["description"] = body["description"]
                if body.get("readme") and body["readme"] != existing.get("readme"):
                    update_fields["readme"] = body["readme"]
                if body.get("latest_version") and body["latest_version"] != existing.get("latest_version"):
                    update_fields["latest_version"] = body["latest_version"]
                    update_fields["current_version"] = body.get("current_version") or body["latest_version"]
                if body.get("version_type") and body["version_type"] != existing.get("version_type"):
                    update_fields["version_type"] = body["version_type"]
                if body.get("commit_sha") and body["commit_sha"] != existing.get("commit_sha"):
                    update_fields["commit_sha"] = body["commit_sha"]
                if body.get("commit_date") and body["commit_date"] != existing.get("commit_date"):
                    update_fields["commit_date"] = body["commit_date"]
                if body.get("download_url") and body["download_url"] != existing.get("download_url"):
                    update_fields["download_url"] = body["download_url"]
                if update_fields:
                    update_project(existing["id"], update_fields)
                    existing.update(update_fields)
                return existing

        sync_status = body.get("sync_status") or ("synced" if github_url else "local")
        current_version = body.get("current_version") or body.get("latest_version")

        project = create_project({
            "name": name,
            "description": body.get("description"),
            "readme": body.get("readme"),
            "github_url": github_url or None,
            "local_path": body.get("local_path"),
            "version_type": body.get("version_type", "none"),
            "latest_version": body.get("latest_version"),
            "current_version": current_version,
            "download_url": body.get("download_url"),
            "commit_sha": body.get("commit_sha"),
            "commit_date": body.get("commit_date"),
            "sync_status": sync_status,
        })
        return project
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.delete("")
def batch_delete_projects(id: str = Query(..., description="逗号分隔的项目 ID")):
    """批量删除项目

    Args:
        id: 逗号分隔的项目 ID，如 "1,2,3"
    Returns:
        删除结果，包含成功删除的 ID 列表
    """
    try:
        if not id:
            raise HTTPException(status_code=400, detail="id is required")

        ids = [int(i.strip()) for i in id.split(",") if i.strip().isdigit()]
        deleted = []
        for pid in ids:
            project = get_project_by_id(pid)
            if project:
                _cleanup_project_dirs(project)
            if delete_project(pid):
                deleted.append(pid)

        return {"success": True, "deleted": deleted}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/{project_id}")
def get_project(project_id: int):
    """获取单个项目详情

    Args:
        project_id: 项目 ID
    Returns:
        项目对象
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.delete("/{project_id}")
def delete_project_endpoint(project_id: int):
    """删除单个项目

    Args:
        project_id: 项目 ID
    Returns:
        删除结果
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        _cleanup_project_dirs(project)

        success = delete_project(project_id)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.patch("/{project_id}")
def update_project_endpoint(project_id: int, body: dict):
    """更新项目信息

    Args:
        project_id: 项目 ID
        body: 更新字段
    Returns:
        更新后的项目对象
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 构建更新字段，仅包含传入的字段
        allowed = [
            "name", "description", "readme", "github_url", "local_path",
            "version_type", "latest_version", "current_version",
            "download_url", "commit_sha", "commit_date", "sync_status",
            "last_synced_at",
        ]
        updates = {}
        for key in allowed:
            if key in body and body[key] is not None:
                updates[key] = body[key]

        if updates:
            update_project(project_id, updates)

        # 返回更新后的项目（与原 Next.js 版本返回 {success: true} 不同，
        # 这里返回更新后的项目对象以提供更多信息）
        updated = get_project_by_id(project_id)
        return {"success": True, **(updated or {})}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("/{project_id}/clone")
async def clone_project(project_id: int, body: CloneInput = None):
    """执行 git clone 将项目克隆到本地

    流程：
    1. 先 clone 到 data/temp/{projectId}/ 临时目录
    2. 创建版本压缩包到项目文件夹
    3. 删除临时目录

    Args:
        project_id: 项目 ID
        body: clone 参数（proxy、archiveFormat、localStoragePath）
    Returns:
        克隆结果信息
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        if not project.get("github_url"):
            raise HTTPException(status_code=400, detail="该项目无 GitHub 地址，无法克隆")

        body = body or CloneInput()
        proxy = body.proxy or ""
        archive_format = body.archiveFormat or "zip"

        # 获取项目存储目录和临时目录（优先使用用户配置的存储路径）
        projects_root = _resolve_projects_root(body.localStoragePath)
        project_dir = _ensure_project_dir(project["name"], projects_root)
        temp_dir = os.path.join(TEMP_DIR, str(project_id))
        project_name = project.get("name", "unknown")

        # 清理旧的临时目录前，先杀掉可能残留的 git 进程（避免文件锁定）
        _kill_git_processes_for_dir(temp_dir)
        # 等待 OS 释放文件锁
        time.sleep(1)

        # 清理旧的临时目录（强制清理，避免 git clone 目标已存在）
        _remove_dir(temp_dir)
        # 确认目录已被删除，否则 git clone 会报 "already exists" 错误
        if os.path.exists(temp_dir):
            raise HTTPException(
                status_code=500,
                detail=f"无法清理临时目录 {temp_dir}，请手动删除后重试",
            )
        os.makedirs(TEMP_DIR, exist_ok=True)

        print(f"[Clone] 项目 {project_id}({project_name}) 开始 clone 到 {temp_dir}")

        # 构造 clone URL
        clone_url = project["github_url"]
        if not clone_url.endswith(".git"):
            clone_url += ".git"

        # 更新工作流状态：开始克隆
        update_project(project_id, {"workflow_status": "cloning"})

        # 构造 clone 命令环境（自动检测系统代理）
        env = os.environ.copy()
        env.update(_get_proxy_env(proxy))

        # 解析 Git 可执行文件路径（支持绿色版 Git），同时获取 PATH 附加目录
        git_exe, git_extra_dirs = _resolve_git_executable(body.gitPath)
        if git_extra_dirs:
            env["PATH"] = os.pathsep.join(git_extra_dirs + [env.get("PATH", "")])

        # 根据克隆方式构造命令（https/ssh/gh_cli/mirror）
        clone_method = (body.cloneMethod or "https").lower()
        gh_exe = _detect_gh_cli(body.ghPath) if clone_method == "gh_cli" else None
        mirror_url = body.mirrorUrl if clone_method == "mirror" else None
        clone_cmd = _build_clone_cmd(clone_method, git_exe, clone_url, temp_dir, proxy, gh_exe, mirror_url)

        # 执行 git clone（使用线程池在 Windows 上执行同步 subprocess）
        # 使用 Popen 追踪进程，超时/异常时能杀掉 git 子进程，避免文件锁定
        # 注意：--quiet 避免大量进度输出导致 stderr 管道缓冲区满而死锁
        try:
            # 用于在线程间传递 git 进程对象，以便超时时杀掉
            _git_proc_holder: list = []

            def _run_git_clone():
                proc = subprocess.Popen(
                    clone_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                _git_proc_holder.append(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=900)
                    return proc, stderr
                except subprocess.TimeoutExpired:
                    # subprocess 层面超时，杀掉进程树
                    _kill_proc_tree(proc)
                    proc.wait(timeout=10)
                    raise

            loop = asyncio.get_event_loop()
            proc, stderr = await asyncio.wait_for(
                loop.run_in_executor(_executor, _run_git_clone),
                timeout=910,
            )

            if proc.returncode != 0:
                err_msg = stderr or "未知错误"

                # 检查目录是否实际存在且有 .git 目录和文件（checkout failed 场景）
                git_dir = os.path.join(temp_dir, ".git")
                has_files = os.path.isdir(temp_dir) and os.path.isdir(git_dir)
                if has_files:
                    file_count = sum(1 for _ in os.scandir(temp_dir) if _.name != ".git")
                    if file_count > 0:
                        # 数据已下载成功且文件存在，仅 checkout 部分失败，视为成功
                        print(f"[Clone] git 返回非零但目录已存在 {file_count} 个文件，视为克隆成功（忽略 checkout 警告）")
                    else:
                        # .git 存在但没有检出文件，尝试 git restore 恢复
                        print(f"[Clone] .git 存在但无文件，尝试 git restore 恢复: {temp_dir}")
                        try:
                            restore_result = subprocess.run(
                                [git_exe, "restore", "--source=HEAD", ":/"],
                                cwd=temp_dir,
                                capture_output=True,
                                text=True,
                                timeout=120,
                                env=env,
                            )
                            if restore_result.returncode == 0:
                                print(f"[Clone] git restore 恢复成功")
                            else:
                                print(f"[Clone] git restore 也失败: {restore_result.stderr}")
                                try:
                                    _remove_dir(temp_dir)
                                except Exception:
                                    pass
                                update_project(project_id, {"sync_status": "failed"})
                                raise HTTPException(status_code=500, detail=f"克隆失败：检出文件失败，可能存在超长路径或不兼容的符号链接。错误：{err_msg}")
                        except subprocess.TimeoutExpired:
                            try:
                                _remove_dir(temp_dir)
                            except Exception:
                                pass
                            update_project(project_id, {"sync_status": "failed"})
                            raise HTTPException(status_code=500, detail=f"克隆失败：检出文件超时。错误：{err_msg}")
                else:
                    # 真正的克隆失败，没有数据
                    try:
                        _remove_dir(temp_dir)
                    except Exception:
                        pass
                    update_project(project_id, {"sync_status": "failed"})

                    if _is_permission_error(err_msg):
                        raise HTTPException(
                            status_code=500,
                            detail="克隆失败：没有写入权限。请尝试以管理员身份运行 Gitter，或在系统设置中选择有写入权限的存储路径",
                        )
                    if _is_tls_error(err_msg):
                        # schannel 握手失败通常是 Windows Git 使用了不兼容的 SSL 后端
                        schannel_hint = ""
                        if "schannel" in err_msg.lower():
                            schannel_hint = "（已自动切换 OpenSSL 后端，如仍失败请尝试切换克隆方式为 SSH 或镜像加速）"
                        raise HTTPException(
                            status_code=500,
                            detail=f"克隆失败：TLS 连接错误，通常因网络环境无法直连 GitHub 导致{schannel_hint}。请在系统设置中配置 Git 代理（如 http://127.0.0.1:7890），或检查代理软件是否正常运行",
                        )
                    if _is_network_error(err_msg):
                        raise HTTPException(
                            status_code=500,
                            detail="克隆失败：无法连接到 GitHub，请检查网络连接或在系统设置中配置 Git 代理",
                        )
                    raise HTTPException(status_code=500, detail=f"克隆失败：{err_msg}")

        except asyncio.TimeoutError:
            # asyncio 层面超时，杀掉仍在运行的 git 进程树
            if _git_proc_holder:
                _kill_proc_tree(_git_proc_holder[0])
            # 等待文件释放后再删除
            time.sleep(1)
            try:
                _remove_dir(temp_dir)
            except Exception:
                pass
            update_project(project_id, {"sync_status": "failed"})
            raise HTTPException(status_code=500, detail="克隆超时，请检查网络连接是否稳定")
        except HTTPException:
            raise
        except Exception as clone_err:
            # 其他异常，也尝试杀掉 git 进程
            if _git_proc_holder:
                _kill_proc_tree(_git_proc_holder[0])
            time.sleep(1)
            try:
                _remove_dir(temp_dir)
            except Exception:
                pass
            update_project(project_id, {"sync_status": "failed"})
            import traceback
            error_detail = f"克隆失败：{str(clone_err) or '执行 git 命令异常'}"
            print(f"[Clone Error] {error_detail}")
            print(traceback.format_exc())
            raise HTTPException(status_code=500, detail=error_detail)

        # 创建版本压缩包
        version = project.get("latest_version") or project.get("current_version")
        try:
            archive_path = _create_version_archive(
                temp_dir, projects_root, project["name"], version, archive_format
            )
            print(f"[Clone] 项目 {project_id} 版本压缩包创建成功: {archive_path}")
        except Exception as e:
            archive_path = None
            print(f"[Clone] 项目 {project_id} 版本压缩包创建失败（非致命）: {e}")

        # 更新项目状态
        from datetime import datetime, timezone
        update_project(project_id, {
            "local_path": project_dir,
            "sync_status": "synced",
            "current_version": project.get("latest_version"),
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        })

        # clone 成功，保留 temp 源码供 Graphify 使用
        print(f"[Clone] 项目 {project_id}({project_name}) 克隆成功，源码保留在 {temp_dir}")

        # clone 成功后立即将 GitHub 资源状态设为 completed，
        # 后台任务不再重置为 fetching，避免状态长期停留在"正在获取"
        github_url = project.get("github_url")
        if github_url:
            update_github_fetch_status(project_id, "completed")
            try:
                asyncio.create_task(
                    _background_fetch_after_clone(project_id, github_url, project_dir)
                )
                print(f"[Clone] 已触发项目 {project_id} 的 GitHub P0 资源后台抓取")
            except Exception as fetch_trigger_err:
                # 触发失败不影响 clone 结果
                print(f"[Clone] 触发 GitHub 抓取任务失败: {fetch_trigger_err}")

        return {
            "message": "克隆成功",
            "localPath": project_dir,
            "archivePath": archive_path,
        }

    except HTTPException:
        raise
    except Exception as err:
        update_project(project_id, {"sync_status": "failed"})
        import traceback
        error_msg = str(err) or "未知错误"
        print(f"[Clone Outer Error] {error_msg}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"克隆失败：{error_msg}")


@router.post("/{project_id}/pull")
async def pull_project(project_id: int, body: PullInput = None):
    """更新单个项目（git pull + 创建新版本压缩包 + 重建知识图谱）

    流程：
    1. 在 temp/{project_id} 目录执行 git pull 拉取最新代码
    2. 获取最新版本信息（tag/release/commit）
    3. 创建新版本压缩包
    4. 重新构建知识图谱
    5. 后台增量抓取 GitHub 资源

    Args:
        project_id: 项目 ID
        body: pull 参数（proxy、archiveFormat）
    Returns:
        更新结果信息
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        if not project.get("github_url"):
            raise HTTPException(status_code=400, detail="该项目无 GitHub 地址，无法更新")

        body = body or PullInput()
        proxy = body.proxy or ""
        archive_format = body.archiveFormat or "zip"

        # 获取项目存储目录和临时目录（从已有项目的 local_path 推算存储根目录）
        existing_local_path = project.get("local_path", "")
        if existing_local_path and os.path.isabs(existing_local_path):
            # local_path 格式为 {root}/{project_name}，取其父目录作为 projects_root
            projects_root = os.path.dirname(existing_local_path)
        else:
            projects_root = PROJECTS_ROOT
        project_dir = _ensure_project_dir(project["name"], projects_root)
        temp_dir = os.path.join(TEMP_DIR, str(project_id))
        project_name = project.get("name", "unknown")
        github_url = project["github_url"]

        # 构造环境变量（自动检测系统代理）
        env = os.environ.copy()
        env.update(_get_proxy_env(proxy))

        # 解析 Git 可执行文件路径（支持绿色版 Git），同时获取 PATH 附加目录
        pull_git_exe, pull_extra_dirs = _resolve_git_executable(body.gitPath)
        if pull_extra_dirs:
            env["PATH"] = os.pathsep.join(pull_extra_dirs + [env.get("PATH", "")])

        # 根据克隆方式构造命令（https/ssh/gh_cli/mirror）
        pull_clone_method = (body.cloneMethod or "https").lower()
        pull_gh_exe = _detect_gh_cli(body.ghPath) if pull_clone_method == "gh_cli" else None
        pull_mirror_url = body.mirrorUrl if pull_clone_method == "mirror" else None
        clone_url = github_url
        if not clone_url.endswith(".git"):
            clone_url += ".git"
        pull_clone_cmd = _build_clone_cmd(pull_clone_method, pull_git_exe, clone_url, temp_dir, proxy, pull_gh_exe, pull_mirror_url)

        print(f"[Pull] 项目 {project_id}({project_name}) 开始更新，清理旧目录并重新克隆")

        # 更新工作流状态：开始清理
        update_project(project_id, {"workflow_status": "cleaning"})

        # 步骤1：清理旧的临时目录和旧知识图谱（强制清理，保证新版本完整）
        _remove_dir(temp_dir)
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        # 删除旧的 graphify-out 目录
        graphify_out_dir = os.path.join(projects_root, project_name, "graphify-out")
        if os.path.exists(graphify_out_dir):
            try:
                shutil.rmtree(graphify_out_dir, ignore_errors=True)
                print(f"[Pull] 项目 {project_id} 已清理旧知识图谱目录")
            except Exception:
                pass
        os.makedirs(TEMP_DIR, exist_ok=True)

        # 步骤2：重新克隆仓库（和clone接口逻辑统一）
        update_project(project_id, {"workflow_status": "cloning"})

        max_retries = 3
        last_error = ""
        clone_success = False

        for attempt in range(1, max_retries + 1):
            try:
                _git_proc_holder: list = []

                def _run_git_clone():
                    proc = subprocess.Popen(
                        pull_clone_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env,
                    )
                    _git_proc_holder.append(proc)
                    try:
                        _, stderr = proc.communicate(timeout=900)
                        return proc, stderr
                    except subprocess.TimeoutExpired:
                        _kill_proc_tree(proc)
                        proc.wait(timeout=10)
                        raise

                loop = asyncio.get_event_loop()
                proc, stderr = await asyncio.wait_for(
                    loop.run_in_executor(_executor, _run_git_clone),
                    timeout=910,
                )
                if proc.returncode == 0:
                    clone_success = True
                    break
                last_error = stderr or "未知错误"

                # 检查目录是否实际存在且有 .git 目录和文件（checkout failed 场景）
                pull_git_dir = os.path.join(temp_dir, ".git")
                if os.path.isdir(temp_dir) and os.path.isdir(pull_git_dir):
                    pull_file_count = sum(1 for _ in os.scandir(temp_dir) if _.name != ".git")
                    if pull_file_count > 0:
                        print(f"[Pull] git 返回非零但目录已存在 {pull_file_count} 个文件，视为克隆成功（忽略 checkout 警告）")
                        clone_success = True
                        break
                    else:
                        print(f"[Pull] .git 存在但无文件，尝试 git restore 恢复: {temp_dir}")
                        try:
                            restore_result = subprocess.run(
                                [pull_git_exe, "restore", "--source=HEAD", ":/"],
                                cwd=temp_dir,
                                capture_output=True,
                                text=True,
                                timeout=120,
                                env=env,
                            )
                            if restore_result.returncode == 0:
                                print(f"[Pull] git restore 恢复成功")
                                clone_success = True
                                break
                            else:
                                print(f"[Pull] git restore 也失败: {restore_result.stderr}")
                        except subprocess.TimeoutExpired:
                            print(f"[Pull] git restore 超时")
            except asyncio.TimeoutError:
                if _git_proc_holder:
                    _kill_proc_tree(_git_proc_holder[0])
                last_error = "克隆超时"
            except Exception as e:
                if _git_proc_holder:
                    _kill_proc_tree(_git_proc_holder[0])
                last_error = str(e)

            if attempt < max_retries:
                # 重试前先杀残留 git 进程并清理目录
                _kill_git_processes_for_dir(temp_dir)
                time.sleep(1)
                _remove_dir(temp_dir)
                await asyncio.sleep(2)

        if not clone_success:
            update_project(project_id, {"sync_status": "failed"})
            if _is_permission_error(last_error):
                raise HTTPException(
                    status_code=500,
                    detail="更新失败：没有写入权限。请尝试以管理员身份运行 Gitter，或在系统设置中选择有写入权限的存储路径",
                )
            if _is_tls_error(last_error):
                raise HTTPException(
                    status_code=500,
                    detail="更新失败：TLS 连接错误，通常因网络环境无法直连 GitHub 导致。请在系统设置中配置 Git 代理（如 http://127.0.0.1:7890），或检查代理软件是否正常运行",
                )
            if _is_network_error(last_error):
                raise HTTPException(
                    status_code=500,
                    detail="更新失败：无法连接到 GitHub，请检查网络连接或配置 Git 代理",
                )
            raise HTTPException(
                status_code=500,
                detail=f"更新失败（已重试 {max_retries} 次）：{last_error}",
            )

        # 步骤2：获取最新版本信息
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        # 解析 owner/repo
        match = re.match(r"github\.com/([^/]+)/([^/]+)", github_url)
        if not match:
            match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_url)
        owner_repo = match.groups() if match else (None, None)

        version_info = {
            "versionType": "unknown",
            "latestVersion": None,
            "commitSha": None,
            "commitDate": None,
            "downloadUrl": None,
        }
        new_readme = None

        if owner_repo[0] and owner_repo[1]:
            try:
                proxy_url = _detect_system_proxy()
                client_kwargs = {"timeout": 15}
                if proxy_url:
                    client_kwargs["proxy"] = proxy_url
                async with httpx.AsyncClient(**client_kwargs) as client:
                    # 获取最新 release
                    release_resp = await client.get(
                        f"https://api.github.com/repos/{owner_repo[0]}/{owner_repo[1]}/releases/latest",
                        headers=headers,
                    )
                    if release_resp.status_code == 200:
                        release_data = release_resp.json()
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
                            f"https://api.github.com/repos/{owner_repo[0]}/{owner_repo[1]}/tags",
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
                                    "downloadUrl": f"https://github.com/{owner_repo[0]}/{owner_repo[1]}/archive/refs/tags/{tags_data[0]['name']}.zip",
                                }
                        else:
                            # 获取最新 commit
                            commits_resp = await client.get(
                                f"https://api.github.com/repos/{owner_repo[0]}/{owner_repo[1]}/commits?per_page=1",
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
                        f"https://ghfast.top/https://raw.githubusercontent.com/{owner_repo[0]}/{owner_repo[1]}/HEAD/README.md",
                        timeout=10,
                    )
                    if readme_resp.status_code == 200:
                        new_readme = readme_resp.text
            except Exception:
                pass

        # 如果远程获取失败，尝试从 temp 目录读取 README
        if not new_readme:
            new_readme = _read_readme_from_dir(temp_dir)

        # 将 README 中的相对路径图片转换为 GitHub raw URL
        if new_readme and owner_repo[0] and owner_repo[1]:
            from backend.utils.readme_utils import rewrite_readme_image_paths
            new_readme = rewrite_readme_image_paths(new_readme, owner_repo[0], owner_repo[1])

        # 步骤3：创建新版本压缩包
        archive_path = None
        try:
            version = version_info["latestVersion"] or version_info["commitSha"][:7] if version_info["commitSha"] else None
            archive_path = _create_version_archive(
                temp_dir, projects_root, project_name, version, archive_format
            )
            print(f"[Pull] 项目 {project_id} 新版本压缩包创建成功: {archive_path}")
        except Exception as e:
            print(f"[Pull] 项目 {project_id} 版本压缩包创建失败（非致命）: {e}")

        # 步骤4：更新项目记录
        from datetime import datetime, timezone
        updates = {
            "sync_status": "synced",
            "version_type": version_info["versionType"],
            "latest_version": version_info["latestVersion"],
            "current_version": version_info["latestVersion"] or version_info["commitSha"][:7] if version_info["commitSha"] else None,
            "commit_sha": version_info["commitSha"],
            "commit_date": version_info["commitDate"],
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if new_readme:
            updates["readme"] = new_readme
        update_project(project_id, updates)

        # 步骤5：保留 temp 源码供后台 graphify 使用
        print(f"[Pull] 项目 {project_id}({project_name}) 更新成功，源码保留在 {temp_dir}")

        # 步骤6：后台增量抓取 GitHub 资源 + graphify + 桥接 + 编译 + 清理 temp
        if github_url:
            update_github_fetch_status(project_id, "completed")
            try:
                asyncio.create_task(
                    _background_fetch_after_pull(
                        project_id, github_url, project_dir
                    )
                )
                print(f"[Pull] 已触发项目 {project_id} 的后台任务（GitHub 抓取 + Graphify + Wiki）")
            except Exception as fetch_trigger_err:
                print(f"[Pull] 触发后台任务失败: {fetch_trigger_err}")

        return {
            "message": "更新成功",
            "readmeUpdated": new_readme is not None,
            "versionType": version_info["versionType"],
            "latestVersion": version_info["latestVersion"],
            "archivePath": archive_path,
        }

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"更新失败：{str(err)}")


@router.get("/{project_id}/workflow-status")
def get_workflow_status(project_id: int):
    """查询项目工作流进度状态

    返回项目当前的工作流阶段，用于前端展示进度条。

    Args:
        project_id: 项目 ID
    Returns:
        { workflow_status, updated_at } 状态值说明：
        - idle: 无任务
        - cleaning: 清理旧文件
        - cloning: 正在克隆代码
        - building_graph: 正在构建知识图谱
        - generating_capability: 正在生成能力报告
        - cleaning_up: 正在清理临时文件
        - done: 全部完成
        - failed: 任务失败
    """
    project = get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "workflowStatus": project.get("workflow_status", "idle"),
        "updatedAt": project.get("updated_at"),
    }


@router.get("/{project_id}/archives")
def get_archives(project_id: int):
    """获取项目版本归档列表

    扫描项目 local_path 目录下的压缩包文件

    Args:
        project_id: 项目 ID
    Returns:
        归档文件列表
    """
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        local_path = project.get("local_path")
        if not local_path or not os.path.exists(local_path):
            return {"archives": []}

        # 扫描项目目录下的压缩包文件
        archives = []
        for entry in os.listdir(local_path):
            if _is_archive_file(entry):
                file_path = os.path.join(local_path, entry)
                try:
                    stat = os.stat(file_path)
                    archives.append({
                        "name": entry,
                        "size": stat.st_size,
                        "modifiedTime": os.path.getmtime(file_path),
                    })
                except Exception:
                    pass

        # 按修改时间倒序排列
        archives.sort(key=lambda a: a["modifiedTime"], reverse=True)

        # 将时间戳转为 ISO 格式
        for a in archives:
            from datetime import datetime, timezone
            a["modifiedTime"] = datetime.fromtimestamp(
                a["modifiedTime"], tz=timezone.utc
            ).isoformat()

        return {"archives": archives}

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"获取版本归档失败：{str(err)}")
