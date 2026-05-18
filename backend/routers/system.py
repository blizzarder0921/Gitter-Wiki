"""
系统工具路由模块

提供 LLM 模型验证、文件夹打开、文件夹选择对话框、清空缓存等系统工具接口。

端点列表：
- POST /api/verify-model  — 验证 LLM 模型可用性
- POST /api/open-folder   — 打开本地文件夹
- POST /api/folder-dialog — Windows 文件夹选择对话框
- POST /api/clear-cache   — 清空所有本地缓存数据
"""

import os
import shutil
import subprocess
import tempfile

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from backend.config import DATA_DIR, GLOBAL_WIKI_DIR, GRAPHIFY_DIR

router = APIRouter(tags=["system"])

# 各 LLM 提供商的默认 API 端点
DEFAULT_BASE_URLS = {
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimaxi.com/anthropic/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "openrouter": "https://openrouter.ai/api/v1",
    "grok": "https://api.x.ai/v1",
    "tencent": "https://hunyuan.tencentcloudapi.com/v1",
    "xiaomi": "https://api.maiml.com/v1",
    "ollama": "http://localhost:11434/v1",
}


class VerifyModelInput(BaseModel):
    """验证模型请求体"""
    model: str
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    providerType: Optional[str] = None


class OpenFolderInput(BaseModel):
    """打开文件夹请求体"""
    path: str


@router.post("/api/verify-model")
async def verify_model(body: VerifyModelInput):
    """验证 LLM 模型可用性

    根据 providerId 选择对应的 API 端点，发送简单请求验证模型可用性。

    Args:
        body: 验证参数，包含 model（格式 providerId:modelId）、apiKey、baseUrl
    Returns:
        验证结果
    """
    try:
        model_str = body.model
        if not model_str:
            raise HTTPException(status_code=400, detail="Missing provider or model")

        # 解析 model 格式：providerId:modelId
        parts = model_str.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise HTTPException(status_code=400, detail="Invalid model format")

        provider_id, model_id = parts[0], parts[1]
        resolved_base_url = body.baseUrl or DEFAULT_BASE_URLS.get(provider_id, "")

        if not resolved_base_url:
            raise HTTPException(status_code=400, detail="Missing base URL")

        # 发送验证请求
        headers = {"Content-Type": "application/json"}
        if body.apiKey:
            headers["Authorization"] = f"Bearer {body.apiKey}"

        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{resolved_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )

        if response.status_code == 200:
            return {"success": True}
        else:
            error_text = response.text
            raise HTTPException(
                status_code=400,
                detail=f"API error: {response.status_code} - {error_text}",
            )

    except httpx.HTTPError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request")


@router.post("/api/open-folder")
async def open_folder(body: OpenFolderInput):
    """打开本地文件夹（Windows 资源管理器）

    Args:
        body: 包含 path 字段的请求体
    Returns:
        操作结果
    """
    try:
        folder_path = body.path
        if not folder_path:
            raise HTTPException(status_code=400, detail="路径不能为空")

        # 去除末尾反斜杠，避免 explorer 打开"此电脑"而非目标目录
        normalized_path = folder_path.rstrip("\\/") or folder_path

        if not os.path.exists(normalized_path):
            raise HTTPException(status_code=404, detail=f"路径不存在：{normalized_path}")

        # Windows 下使用 explorer 命令打开文件夹
        explorer_path = os.path.join(
            os.environ.get("SystemRoot", "C:\\Windows"), "explorer.exe"
        )
        # explorer 在已有实例运行时返回非零退出码，需忽略错误
        subprocess.Popen(
            [explorer_path, normalized_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{str(err)}")


@router.post("/api/folder-dialog")
async def folder_dialog():
    """Windows 文件夹选择对话框

    使用 PowerShell 脚本弹出文件夹选择对话框，返回用户选择的路径。
    采用临时文件传递结果，避免 stdout 编码问题。

    Returns:
        用户选择的路径，或取消标记
    """
    tmp_dir = tempfile.gettempdir()
    script_path = os.path.join(tmp_dir, "gitter-folder-dialog.ps1")
    result_path = os.path.join(tmp_dir, "gitter-folder-result.txt")

    try:
        # PowerShell 脚本：弹出文件夹选择对话框
        ps_script = f"""
$shell = New-Object -ComObject Shell.Application
$folder = $shell.BrowseForFolder(0, '选择项目存储目录', 0)
if ($folder) {{
    $result = $folder.Self.Path
}} else {{
    $result = '__CANCELLED__'
}}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('{result_path}', $result, $utf8)
""".strip()

        # 写入 UTF-8 BOM，确保 PowerShell 正确识别脚本编码
        with open(script_path, "wb") as f:
            f.write(b"\xef\xbb\xbf")
            f.write(ps_script.encode("utf-8"))

        # 执行 PowerShell 脚本（CREATE_NO_WINDOW 隐藏控制台窗口，避免弹出黑色窗口）
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            timeout=120000,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )

        # 从临时文件读取结果
        with open(result_path, "r", encoding="utf-8") as f:
            output = f.read().strip()

        if output == "__CANCELLED__":
            return {"cancelled": True}

        return {"path": output}

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"选择文件夹失败：{str(err)}")
    finally:
        # 清理临时文件
        for p in [script_path, result_path]:
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


@router.get("/api/detect-proxy")
async def detect_system_proxy():
    """检测系统代理设置

    从 Windows 注册表读取系统代理（Clash/V2Ray 等设置的 IE 代理），
    返回代理地址供前端展示，让用户知道无需手动配置。

    Returns:
        proxy: 检测到的代理地址（如 http://127.0.0.1:7897），无代理时为 null
        source: 代理来源描述
    """
    from backend.routers.projects import _detect_system_proxy

    proxy = _detect_system_proxy()
    return {
        "proxy": proxy,
        "source": "系统代理（注册表）" if proxy else None,
    }


@router.post("/api/validate-git-path")
async def validate_git_path(request: Request):
    """验证自定义 Git 可执行文件路径是否有效

    检查指定路径是否存在、是否为可执行文件、是否能正常运行 git --version。
    用于前端设置页面验证用户输入的绿色版 Git 路径。

    Returns:
        valid: 路径是否有效
        version: Git 版本号（有效时返回）
        sslBackend: SSL 后端信息（有效时返回）
        error: 错误信息（无效时返回）
    """
    body = await request.json()
    git_path = body.get("gitPath", "").strip()

    if not git_path:
        return {"valid": False, "error": "路径为空"}

    if not os.path.exists(git_path):
        return {"valid": False, "error": f"文件不存在: {git_path}"}

    if not os.path.isfile(git_path):
        return {"valid": False, "error": f"路径不是文件: {git_path}"}

    try:
        result = subprocess.run(
            [git_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"valid": False, "error": f"执行失败: {result.stderr.strip()}"}

        version = result.stdout.strip()

        ssl_info = ""
        try:
            ssl_result = subprocess.run(
                [git_path, "config", "--get", "http.sslBackend"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if ssl_result.returncode == 0 and ssl_result.stdout.strip():
                ssl_info = ssl_result.stdout.strip()
        except Exception:
            pass

        return {
            "valid": True,
            "version": version,
            "sslBackend": ssl_info or "未配置（将使用 openssl）",
        }
    except subprocess.TimeoutExpired:
        return {"valid": False, "error": "执行超时，可能不是有效的 Git 可执行文件"}
    except Exception as e:
        return {"valid": False, "error": f"执行异常: {str(e)}"}


@router.get("/api/detect-git")
async def detect_system_git():
    """检测系统 PATH 中的 Git 信息

    检查系统 PATH 中是否存在可用的 git 命令，返回版本和路径信息。
    用于前端设置页面展示当前系统 Git 状态。

    Returns:
        available: 系统 Git 是否可用
        version: Git 版本号
        path: Git 可执行文件路径
    """
    try:
        which_result = subprocess.run(
            ["where", "git"] if os.name == "nt" else ["which", "git"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_path = ""
        if which_result.returncode == 0:
            git_path = which_result.stdout.strip().split("\n")[0].strip()

        version_result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if version_result.returncode != 0:
            return {"available": False, "version": None, "path": None}

        return {
            "available": True,
            "version": version_result.stdout.strip(),
            "path": git_path or None,
        }
    except Exception:
        return {"available": False, "version": None, "path": None}


@router.get("/api/detect-clone-methods")
async def detect_clone_methods(ghPath: Optional[str] = None):
    """检测可用的克隆方式

    检测 SSH 密钥和 GitHub CLI (gh) 是否可用，
    供前端设置页面展示各克隆方式的状态。

    Args:
        ghPath: 自定义 gh 可执行文件路径（可选）
    Returns:
        ssh: SSH 密钥是否可用（key_path 有值时可用）
        sshKeyPath: 找到的 SSH 密钥路径
        ghCli: GitHub CLI 是否可用
        ghVersion: GitHub CLI 版本号
    """
    ssh_key_path = None
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    if os.path.isdir(ssh_dir):
        for name in ("id_ed25519", "id_rsa", "id_ecdsa", "id_ecdsa_sk"):
            key_path = os.path.join(ssh_dir, name)
            if os.path.isfile(key_path):
                ssh_key_path = key_path
                break

    gh_available = False
    gh_version = None
    gh_exe = ghPath and ghPath.strip()
    if gh_exe and os.path.isfile(gh_exe):
        try:
            result = subprocess.run(
                [gh_exe, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gh_available = True
                gh_version = result.stdout.strip().split("\n")[0]
        except (subprocess.TimeoutExpired, Exception):
            pass
    else:
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gh_available = True
                gh_version = result.stdout.strip().split("\n")[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return {
        "ssh": ssh_key_path is not None,
        "sshKeyPath": ssh_key_path,
        "ghCli": gh_available,
        "ghVersion": gh_version,
    }


@router.post("/api/validate-gh-path")
async def validate_gh_path(request: Request):
    """验证自定义 GitHub CLI 可执行文件路径是否有效

    检查指定路径是否存在、是否为可执行文件、是否能正常运行 gh --version。

    Returns:
        valid: 路径是否有效
        version: gh 版本号（有效时返回）
        error: 错误信息（无效时返回）
    """
    body = await request.json()
    gh_path = body.get("ghPath", "").strip()

    if not gh_path:
        return {"valid": False, "error": "路径为空"}

    if not os.path.exists(gh_path):
        return {"valid": False, "error": f"文件不存在: {gh_path}"}

    if not os.path.isfile(gh_path):
        return {"valid": False, "error": f"路径不是文件: {gh_path}"}

    try:
        result = subprocess.run(
            [gh_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"valid": False, "error": f"执行失败: {result.stderr.strip()}"}

        version = result.stdout.strip().split("\n")[0]
        return {"valid": True, "version": version}
    except subprocess.TimeoutExpired:
        return {"valid": False, "error": "执行超时，可能不是有效的 GitHub CLI"}
    except Exception as e:
        return {"valid": False, "error": f"执行异常: {str(e)}"}


@router.post("/api/clear-cache")
async def clear_cache():
    """清空所有本地缓存数据

    执行以下清理操作：
      1. 清空 SQLite 中所有业务数据表（wiki_chats、wiki_chat_messages、
         wiki_research_tasks、wiki_review_items、projects、settings）
      2. 删除全局 Wiki 向量索引目录（.llm-wiki/vector-index/）
      3. 删除 graphify 缓存目录（data/graphify/）
      4. 删除临时文件目录（data/temp/）

    注意：不删除 Wiki 源文件和生成的 Wiki 页面（data/global-wiki/sources/、
    data/global-wiki/wiki/），因为这些是用户的知识资产，不属于缓存范畴。

    Returns:
        清理结果统计
    """
    from backend.services.database import get_db

    results = {"tables_cleared": [], "dirs_removed": [], "errors": []}

    try:
        db = get_db()

        # 清空各业务数据表
        tables_to_clear = [
            "wiki_chat_messages",
            "wiki_chats",
            "wiki_research_tasks",
            "wiki_review_items",
            "projects",
            "settings",
        ]
        for table in tables_to_clear:
            try:
                db.execute(f"DELETE FROM {table}")
                results["tables_cleared"].append(table)
            except Exception as err:
                results["errors"].append(f"清空表 {table} 失败: {str(err)}")

        db.commit()
    except Exception as err:
        results["errors"].append(f"数据库操作失败: {str(err)}")

    # 删除向量索引目录
    vector_index_dir = os.path.join(GLOBAL_WIKI_DIR, ".llm-wiki", "vector-index")
    if os.path.isdir(vector_index_dir):
        try:
            shutil.rmtree(vector_index_dir)
            results["dirs_removed"].append(vector_index_dir)
        except Exception as err:
            results["errors"].append(f"删除向量索引失败: {str(err)}")

    # 删除 graphify 缓存目录
    if os.path.isdir(GRAPHIFY_DIR):
        try:
            shutil.rmtree(GRAPHIFY_DIR)
            results["dirs_removed"].append(GRAPHIFY_DIR)
        except Exception as err:
            results["errors"].append(f"删除 graphify 缓存失败: {str(err)}")

    # 删除临时文件目录
    temp_dir = os.path.join(DATA_DIR, "temp")
    if os.path.isdir(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            results["dirs_removed"].append(temp_dir)
        except Exception as err:
            results["errors"].append(f"删除临时文件失败: {str(err)}")

    return {"success": len(results["errors"]) == 0, "results": results}
