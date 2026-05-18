"""
翻译路由模块

提供 LLM 翻译、一键更新所有项目等功能。

端点列表：
- POST /api/translate       — LLM 翻译
- POST /api/update-all      — 一键更新所有项目
"""

import os
import re
import shutil
import asyncio
from typing import Optional, List

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.project_service import get_all_projects, get_project_by_id, update_project
from backend.config import TEMP_DIR

router = APIRouter(tags=["translate"])

# 各 LLM 提供商的默认 API 端点
PROVIDER_BASE_URLS = {
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


def _strip_thinking_tags(text: str) -> str:
    """清除模型返回中的思考标签内容

    Args:
        text: 模型返回的文本
    Returns:
        清除思考标签后的文本
    """
    return re.sub(r"<think[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def _get_system_prompt(target_lang: str) -> str:
    """根据目标语言生成对应的 system prompt

    Args:
        target_lang: 目标语言代码 'zh' | 'en'
    Returns:
        系统提示词
    """
    if target_lang == "en":
        return "你是一个专业的翻译助手。将用户提供的中文内容翻译成英文。保持原有的Markdown格式和代码块不变，只翻译自然语言文字部分。直接输出翻译结果，不要添加任何解释或说明。不要输出思考过程。"
    return "你是一个专业的翻译助手。将用户提供的英文内容翻译成中文。保持原有的Markdown格式和代码块不变，只翻译自然语言文字部分。直接输出翻译结果，不要添加任何解释或说明。不要输出思考过程。"


def _get_user_prompt(target_lang: str, text: str) -> str:
    """根据目标语言生成对应的 user prompt

    Args:
        target_lang: 目标语言代码
        text: 待翻译文本
    Returns:
        用户提示词
    """
    if target_lang == "en":
        return f"请将以下中文内容翻译成英文，保持原有格式不变：\n\n{text}"
    return f"请将以下英文内容翻译成中文，保持原有格式不变：\n\n{text}"


# ---------------------------------------------------------------------------
# 翻译端点
# ---------------------------------------------------------------------------

class TranslateInput(BaseModel):
    """翻译请求体"""
    text: str
    targetLang: str = "zh-CN"
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None


@router.post("/api/translate")
async def translate(body: TranslateInput):
    """LLM 翻译

    根据提供商调用对应的 LLM API 进行翻译。

    Args:
        body: 翻译请求参数
    Returns:
        翻译结果
    """
    try:
        resolved_base_url = body.baseUrl or PROVIDER_BASE_URLS.get(body.providerId or "", "")
        target = "en" if body.targetLang == "en" else "zh"

        headers = {"Content-Type": "application/json"}
        if body.apiKey:
            headers["Authorization"] = f"Bearer {body.apiKey}"

        payload = {
            "model": body.modelId,
            "messages": [
                {"role": "system", "content": _get_system_prompt(target)},
                {"role": "user", "content": _get_user_prompt(target, body.text)},
            ],
            "max_tokens": 8192,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{resolved_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Translation failed")

        data = response.json()
        translated_text = (
            data.get("choices", [{}])[0].get("message", {}).get("content")
            or data.get("message", {}).get("content")
        )

        if translated_text:
            translated_text = _strip_thinking_tags(translated_text)

        if not translated_text or not translated_text.strip():
            raise HTTPException(status_code=500, detail="翻译结果为空")

        return {
            "translatedText": translated_text,
            "originalText": body.text,
        }

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail="Translation failed")


# ---------------------------------------------------------------------------
# 一键更新所有项目
# ---------------------------------------------------------------------------

class UpdateAllInput(BaseModel):
    """一键更新请求体"""
    model: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None


@router.post("/api/update-all")
async def update_all(body: UpdateAllInput):
    """一键更新所有项目

    串行处理每个项目：检查版本 -> git pull -> 更新 README

    Args:
        body: 更新参数（model、apiKey、baseUrl）
    Returns:
        更新结果统计
    """
    try:
        projects = get_all_projects()
        success = 0
        failed = 0
        failed_details = []

        for project in projects:
            try:
                # 无 GitHub URL 的本地项目跳过
                if not project.get("github_url"):
                    continue

                github_url = project.get("github_url", "")
                match = re.match(r"github\.com/([^/]+)/([^/]+)", github_url)
                if not match:
                    # 尝试 https 格式
                    match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", github_url)
                if not match:
                    failed += 1
                    failed_details.append({"name": project["name"], "error": "无法解析 GitHub URL"})
                    continue

                owner, repo = match.group(1), match.group(2)

                # 检查最新版本
                token = os.environ.get("GITHUB_TOKEN")
                headers = {"Accept": "application/vnd.github.v3+json"}
                if token:
                    headers["Authorization"] = f"token {token}"

                repo_data = None
                try:
                    from backend.routers.projects import _detect_system_proxy
                    _proxy = _detect_system_proxy()
                    _ck = {"timeout": 15}
                    if _proxy:
                        _ck["proxy"] = _proxy
                    async with httpx.AsyncClient(**_ck) as client:
                        repo_resp = await client.get(
                            f"https://api.github.com/repos/{owner}/{repo}",
                            headers=headers,
                        )
                        if repo_resp.status_code == 200:
                            repo_data = repo_resp.json()
                except Exception:
                    pass

                if not repo_data:
                    failed += 1
                    failed_details.append({"name": project["name"], "error": "GitHub 仓库不存在"})
                    continue

                # 检测是否有新版本（对比 pushed_at 和 last_synced_at）
                pushed_at = repo_data.get("pushed_at")
                last_synced = project.get("last_synced_at")
                has_update = False
                if pushed_at and last_synced and pushed_at > last_synced:
                    has_update = True

                # 注意：temp目录保留给graphify构建知识图谱使用
                # 清理逻辑在clone前处理（projects.py中的clone接口）

                # 更新项目状态
                updates = {
                    "sync_status": "synced",
                    "last_synced_at": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                }
                if repo_data.get("description"):
                    updates["description"] = repo_data["description"]
                update_project(project["id"], updates)
                success += 1

            except Exception as err:
                failed += 1
                failed_details.append({"name": project["name"], "error": str(err)})
                update_project(project["id"], {"sync_status": "failed"})

        return {"success": success, "failed": failed, "failedDetails": failed_details}

    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to update projects")
