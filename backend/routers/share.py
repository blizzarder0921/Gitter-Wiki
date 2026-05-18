"""
分享文案生成路由模块

提供基于 LLM 的项目分享文案生成功能。

端点列表：
- POST /api/share/generate — 生成项目分享文案
"""

import re
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services.project_service import get_project_by_id
from backend.services.wiki.llm_client import stream_chat

router = APIRouter(tags=["share"])

_logger = logging.getLogger("backend.routers.share")


# ---------------------------------------------------------------------------
# 风格对应的系统提示词模板
# ---------------------------------------------------------------------------

_STYLE_PROMPTS = {
    "tech-review": (
        "请以技术评测的风格撰写分享文案。要求：深度分析项目架构与技术实现，"
        "客观评价优劣势，适合技术社区传播。包含技术栈分析、性能评估、同类对比。"
    ),
    "recommend": (
        "请以种草推荐的风格撰写分享文案。要求：热情洋溢、亮点突出，"
        "用感染力强的语言吸引读者尝试，适合社交媒体传播。多用表情符号和感叹句。"
    ),
    "news-flash": (
        "请以新闻速递的风格撰写分享文案。要求：简洁客观、核心信息优先，"
        "5W1H 结构，适合资讯平台传播。语言正式、信息密度高。"
    ),
    "tutorial": (
        "请以教程指南的风格撰写分享文案。要求：入门友好、步骤清晰，"
        "包含快速上手指南和核心用法示例，适合技术博客传播。"
    ),
    "geek-brief": (
        "请以极客简报的风格撰写分享文案。要求：极简风格、核心数据驱动，"
        "用最少的文字传递最多信息，适合 RSS/Newsletter 传播。"
    ),
}


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------

class ShareGenerateRequest(BaseModel):
    """分享文案生成请求体"""
    projectId: int
    style: str = "tech-review"
    agentPrompt: Optional[str] = None
    providerId: str = "openai"
    modelId: str = "gpt-4o-mini"
    apiKey: str = ""
    baseUrl: str = ""


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract_image_prompt(content: str) -> tuple[str, str]:
    """从 LLM 生成的文案中分离配图提示词

    查找 Markdown 格式的配图提示词段落（## 🎨 配图提示词 / > 提示词内容），
    将其从正文中剥离并单独返回。

    Args:
        content: LLM 生成的完整 Markdown 文案
    Returns:
        (正文内容, 配图提示词) 元组
    """
    image_prompt = ""

    patterns = [
        r"##\s*🎨\s*配图提示词\s*\n+(?:>\s*)(.+?)(?=\n##|\Z)",
        r"##\s*配图提示词\s*\n+(?:>\s*)(.+?)(?=\n##|\Z)",
        r"##\s*🎨\s*Image Prompt\s*\n+(?:>\s*)(.+?)(?=\n##|\Z)",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            image_prompt = match.group(1).strip()
            content = content[:match.start()].strip()
            break

    return content, image_prompt


def _build_project_context(project: dict) -> str:
    """根据项目信息构建上下文描述

    Args:
        project: 项目字典
    Returns:
        项目上下文描述文本
    """
    parts = []

    if project.get("name"):
        parts.append(f"项目名称：{project['name']}")

    if project.get("description"):
        parts.append(f"项目描述：{project['description']}")

    if project.get("github_url"):
        parts.append(f"GitHub 地址：{project['github_url']}")

    if project.get("version_type") and project.get("version_type") != "none":
        parts.append(f"版本类型：{project['version_type']}")

    if project.get("latest_version"):
        parts.append(f"最新版本：{project['latest_version']}")

    if project.get("readme"):
        readme_text = project["readme"]
        if len(readme_text) > 3000:
            readme_text = readme_text[:3000] + "\n...(README 已截断)"
        parts.append(f"README 摘要：\n{readme_text}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 路由处理
# ---------------------------------------------------------------------------

@router.post("/api/share/generate")
async def generate_share_content(body: ShareGenerateRequest):
    """生成项目分享文案

    根据项目信息和用户选择的风格，调用 LLM 生成分享文案和配图提示词。

    Args:
        body: 生成请求体
    Returns:
        包含 content（Markdown 文案）和 imagePrompt（配图提示词）的结果
    """
    try:
        project = get_project_by_id(body.projectId)
        if not project:
            return {"code": 404, "message": "项目不存在", "data": None}

        if not body.apiKey:
            return {"code": 400, "message": "未配置 API Key，请在「设置 → 模型配置」中为当前选中的提供商填写 API Key", "data": None}

        style_prompt = _STYLE_PROMPTS.get(body.style, _STYLE_PROMPTS["tech-review"])

        agent_prompt = body.agentPrompt or ""

        project_context = _build_project_context(project)

        system_message = f"""{agent_prompt}

{style_prompt}

输出要求：
1. 使用 Markdown 格式
2. 文案长度 300-800 字
3. 在文案末尾单独输出配图提示词，格式为：## 🎨 配图提示词
   > [描述一张适合搭配此文案的配图，包含画面主体、风格、色调等]"""

        user_message = f"请为以下项目生成分享文案：\n\n{project_context}"

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]

        config = {
            "provider": body.providerId,
            "apiKey": body.apiKey,
            "baseUrl": body.baseUrl,
            "model": body.modelId,
        }

        full_content = await stream_chat(
            config=config,
            messages=messages,
            on_token=lambda _: None,
        )

        content, image_prompt = _extract_image_prompt(full_content)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "content": content,
                "imagePrompt": image_prompt,
            },
        }

    except Exception as err:
        _logger.error("分享文案生成失败: %s", err, exc_info=True)
        return {"code": 500, "message": f"文案生成失败：{str(err)}", "data": None}
