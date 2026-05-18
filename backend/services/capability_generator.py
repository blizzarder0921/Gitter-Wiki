"""
异步能力报告生成器模块

为每个项目生成结构化的 Markdown 能力报告，通过 LLM 分析项目材料，
输出标准化的能力描述文档，保存到全局 Wiki sources 目录并触发 ingest。

核心功能：
- 从 settings-storage 读取 LLM 配置
- 读取项目 README.md 和 GRAPH_REPORT.md
- 可选抓取 GitHub Issues/Releases 作为补充材料
- 调用 LLM 生成结构化能力报告
- 保存报告并更新数据库
- 自动触发全局 Wiki ingest

GPLv3 License - Gitter Project
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import httpx

from backend.config import GLOBAL_WIKI_SOURCES_DIR
from backend.services.project_service import get_setting, get_project_by_id, update_project
from backend.services.wiki.llm_client import simple_chat

logger = logging.getLogger(__name__)

# GitHub URL 解析正则：提取 owner 和 repo
_GITHUB_URL_RE = re.compile(
    r"github\.com/([^/]+)/([^/]+?)(?:\.git|/|$)"
)


def _get_llm_config_from_settings() -> dict:
    """从 settings 表中读取 LLM 配置

    从 SQLite settings 表中读取 "settings-storage" 键对应的 JSON 字符串，
    兼容 {"state": {...}, "version": 1} 格式，解析出当前选中的 provider、
    model 以及对应的 apiKey/baseUrl。

    当选中的 provider 没有 API Key 时，会自动回退查找其他已配置 Key 的 provider，
    确保后台自动化任务（能力报告、Wiki 生成等）不会因 provider 未切换而中断。

    Returns:
        LLM 配置字典，包含 provider/model/apiKey/baseUrl 等字段；
        读取失败或未配置时返回空字典
    """
    try:
        raw = get_setting("settings-storage")
        if not raw:
            return {}

        data = json.loads(raw)
        # 兼容 {"state": {...}, "version": 1} 格式
        state = data.get("state", data)

        config = {}

        # 读取当前选中的 provider 和 model
        provider_id = state.get("providerId")
        model_id = state.get("modelId")
        if provider_id:
            config["provider"] = provider_id
        if model_id:
            config["model"] = model_id

        # 从 providersConfig 中读取对应 provider 的 apiKey 和 baseUrl
        providers_config = state.get("providersConfig", {})
        if provider_id and provider_id in providers_config:
            provider_cfg = providers_config[provider_id]
            api_key = provider_cfg.get("apiKey")
            base_url = provider_cfg.get("baseUrl") or provider_cfg.get("defaultBaseUrl")
            if api_key:
                config["apiKey"] = api_key
            if base_url:
                config["baseUrl"] = base_url

        # 回退逻辑：选中的 provider 没有 apiKey 时，查找其他已配置 key 的 provider
        if not config.get("apiKey") and providers_config:
            # 每个 provider 的默认模型（当原 model 不兼容时使用）
            _DEFAULT_MODELS = {
                "openai": "gpt-4o-mini",
                "anthropic": "claude-sonnet-4-20250514",
                "google": "gemini-2.0-flash",
                "glm": "glm-4-flash",
                "qwen": "qwen-plus",
                "deepseek": "deepseek-chat",
                "kimi": "moonshot-v1-8k",
                "minimax": "MiniMax-Text-01",
                "siliconflow": "Qwen/Qwen2.5-7B-Instruct",
                "doubao": "doubao-1-5-pro-32k-250115",
                "openrouter": "openai/gpt-4o-mini",
                "grok": "grok-3-mini",
                "tencent-hunyuan": "hunyuan-lite",
                "xiaomi": "MiMo-7B-RL",
                "ollama": "llama3",
            }
            for pid, pcfg in providers_config.items():
                fallback_key = pcfg.get("apiKey")
                if fallback_key:
                    config["provider"] = pid
                    config["apiKey"] = fallback_key
                    fallback_url = pcfg.get("baseUrl") or pcfg.get("defaultBaseUrl")
                    if fallback_url:
                        config["baseUrl"] = fallback_url
                    # 回退时使用目标 provider 的默认模型，避免模型不兼容
                    config["model"] = _DEFAULT_MODELS.get(pid, "gpt-4o-mini")
                    logger.info(
                        "[LLM Config] 选中 provider %s 无 API Key，回退使用 %s (model=%s)",
                        provider_id, pid, config["model"],
                    )
                    break

        return config
    except Exception as e:
        logger.warning("从 settings 读取 LLM 配置失败: %s", e)
        return {}


def _try_read_file(path: str) -> str:
    """安全读取文件内容

    Args:
        path: 文件绝对路径
    Returns:
        文件内容字符串，读取失败时返回空字符串
    """
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("读取文件失败 %s: %s", path, e)
    return ""


def _parse_github_url(github_url: str) -> tuple[str, str] | None:
    """解析 GitHub URL，提取 owner 和 repo

    Args:
        github_url: GitHub 仓库 URL
    Returns:
        (owner, repo) 元组，解析失败时返回 None
    """
    if not github_url:
        return None
    match = _GITHUB_URL_RE.search(github_url)
    if match:
        return match.group(1), match.group(2)
    return None


# 能力报告 Prompt 模板
_CAPABILITY_PROMPT = """你是一个开源项目分析专家。请根据以下材料，输出一份结构化的【项目能力报告】。

输入材料：
- README.md 内容
- 代码结构报告（GRAPH_REPORT.md，如果有）
- 项目元数据（名称、语言、stars）
- GitHub Issues/Releases 摘要（如果有）

输出格式（Markdown，严格按以下结构）：

### 项目名称
[名称]

### 一句话定位
[一句话说清楚项目是干什么的，面向谁]

### 核心能力（3-5条）
- 能力1：[能力名称] - [具体描述]

### 技术亮点
- [用了什么值得注意的技术/架构/算法]

### 输入与输出（如果适用）
- 输入：[接受什么格式的数据/请求]
- 输出：[产出什么格式的结果]

### 集成方式
- [如何被其他项目调用：CLI/API/库/服务]

### 适用场景
- [列举 2-3 个典型使用场景]

### 潜在风险或缺失信息（如果有）
- [根据图谱中的孤立节点或推断边提出，没有则省略]

要求：
1. 不要复制原文，要提炼。
2. 如果某些信息缺失，写"未明确说明"。
3. 输出内容应适合直接存入 Markdown 文件，供人类阅读。
"""


async def _fetch_github_supplements(github_url: str) -> str:
    """抓取 GitHub Issues 和 Releases 作为补充材料

    当项目有 GitHub URL 时，延迟导入 GitHubFetcher，
    抓取少量 Issues（最多5个）和 Releases（最新3个）。

    Args:
        github_url: GitHub 仓库 URL
    Returns:
        补充材料的文本摘要，抓取失败时返回空字符串
    """
    parsed = _parse_github_url(github_url)
    if not parsed:
        return ""

    owner, repo = parsed
    supplements = []

    try:
        from backend.services.github_fetcher import GitHubFetcher
        fetcher = GitHubFetcher()

        # 抓取最近 Issues（最多5个）
        try:
            issues = await fetcher.fetch_issues(owner, repo)
            if issues:
                issue_lines = []
                for issue in issues[:5]:
                    labels = ", ".join(issue.get("labels", []))
                    label_str = f" [{labels}]" if labels else ""
                    issue_lines.append(
                        f"  - #{issue['number']} {issue['title']} "
                        f"({issue['state']}{label_str})"
                    )
                supplements.append("### 最近 Issues\n" + "\n".join(issue_lines))
        except Exception as e:
            logger.warning("抓取 GitHub Issues 失败: %s", e)

        # 抓取最新 Releases（最多3个）
        try:
            releases = await fetcher.fetch_releases(owner, repo)
            if releases:
                release_lines = []
                for release in releases[:3]:
                    prerelease = " (预发布)" if release.get("prerelease") else ""
                    release_lines.append(
                        f"  - {release.get('tag', '')} {release.get('name', '')}"
                        f" ({release.get('published_at', '')}{prerelease})"
                    )
                supplements.append("### 最新 Releases\n" + "\n".join(release_lines))
        except Exception as e:
            logger.warning("抓取 GitHub Releases 失败: %s", e)

    except Exception as e:
        logger.warning("GitHubFetcher 初始化失败: %s", e)

    return "\n\n".join(supplements)


async def generate_capability_report(
    project_id: int,
    github_url: str = None,
) -> str | None:
    """为项目生成结构化的 Markdown 能力报告

    完整流程：
    1. 从 settings-storage 读取 LLM 配置
    2. 读取项目 README.md 和 GRAPH_REPORT.md
    3. 可选抓取 GitHub Issues/Releases
    4. 调用 LLM 生成结构化报告
    5. 保存到 data/global-wiki/sources/{project_id}.md
    6. 更新数据库 capability_report_path 和 capability_generated_at
    7. 触发全局 Wiki ingest

    Args:
        project_id: 项目 ID
        github_url: GitHub 仓库 URL（可选，提供时抓取补充材料）
    Returns:
        生成的报告内容，失败时返回 None
    """
    try:
        # ── 1. 读取 LLM 配置 ──────────────────────────────────
        llm_config = _get_llm_config_from_settings()
        if not llm_config or not llm_config.get("apiKey"):
            logger.warning(
                "[capability] 项目 %d LLM 配置缺失或无 API Key，跳过能力报告生成", project_id
            )
            return None

        # ── 2. 获取项目信息 ────────────────────────────────────
        project = get_project_by_id(project_id)
        if not project:
            logger.error("[capability] 项目 %d 不存在", project_id)
            return None

        local_path = project.get("local_path", "")

        # ── 3. 读取项目文件 ────────────────────────────────────
        readme_content = ""
        graph_report_content = ""

        if local_path and os.path.isdir(local_path):
            readme_content = _try_read_file(os.path.join(local_path, "README.md"))
            graph_report_content = _try_read_file(
                os.path.join(local_path, "graphify-out", "GRAPH_REPORT.md")
            )

        # ── 4. 可选 GitHub 补充材料 ────────────────────────────
        github_supplements = ""
        effective_github_url = github_url or project.get("github_url", "")
        if effective_github_url:
            github_supplements = await _fetch_github_supplements(effective_github_url)

        # ── 5. 构建用户消息 ────────────────────────────────────
        user_parts = []

        # 项目元数据
        meta_lines = [f"- 名称：{project.get('name', '未知')}"]
        if project.get("description"):
            meta_lines.append(f"- 描述：{project['description']}")
        if effective_github_url:
            meta_lines.append(f"- GitHub：{effective_github_url}")
        user_parts.append("### 项目元数据\n" + "\n".join(meta_lines))

        # README.md
        if readme_content:
            # 截断过长内容
            truncated = readme_content[:30000]
            if len(readme_content) > 30000:
                truncated += "\n\n[...内容已截断...]"
            user_parts.append(f"### README.md\n{truncated}")

        # GRAPH_REPORT.md
        if graph_report_content:
            truncated = graph_report_content[:20000]
            if len(graph_report_content) > 20000:
                truncated += "\n\n[...内容已截断...]"
            user_parts.append(f"### 代码结构报告（GRAPH_REPORT.md）\n{truncated}")

        # GitHub 补充材料
        if github_supplements:
            user_parts.append(github_supplements)

        user_message = "\n\n".join(user_parts)

        if not user_message.strip():
            logger.warning(
                "[capability] 项目 %d 无可用材料，跳过能力报告生成", project_id
            )
            return None

        # ── 6. 调用 LLM 生成报告 ──────────────────────────────
        messages = [
            {"role": "system", "content": _CAPABILITY_PROMPT},
            {"role": "user", "content": user_message},
        ]

        report_content = await simple_chat(config=llm_config, messages=messages)

        if not report_content or not report_content.strip():
            logger.warning("[capability] 项目 %d LLM 生成内容为空", project_id)
            return None

        # ── 7. 保存报告到文件 ──────────────────────────────────
        os.makedirs(GLOBAL_WIKI_SOURCES_DIR, exist_ok=True)
        report_path = os.path.join(GLOBAL_WIKI_SOURCES_DIR, f"{project_id}.md")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        logger.info("[capability] 项目 %d 能力报告已保存: %s", project_id, report_path)

        # ── 8. 更新数据库 ──────────────────────────────────────
        now_iso = datetime.now(timezone.utc).isoformat()
        update_project(project_id, {
            "capability_report_path": report_path,
            "capability_generated_at": now_iso,
        })

        # ── 9. 触发全局 Wiki ingest（仅处理当前报告文件） ───────
        await _trigger_global_wiki_ingest(report_path, llm_config)

        return report_content

    except Exception as e:
        logger.error("[capability] 项目 %d 能力报告生成失败: %s", project_id, e, exc_info=True)
        return None


async def _trigger_global_wiki_ingest(
    source_path: str,
    llm_config: dict | None = None,
) -> None:
    """触发全局 Wiki ingest（仅处理指定的 source 文件）

    报告保存成功后，仅对当前生成的报告文件执行 ingest，
    避免遍历整个 sources 目录导致旧项目残留文件被误处理。

    优先尝试直接调用 ingest 函数，回退到 HTTP API 调用。

    Args:
        source_path: 需要摄入的 source 文件绝对路径
        llm_config: LLM 配置字典，包含 provider/apiKey/baseUrl/model 等字段；
            为 None 时从系统设置自动读取
    """
    if not source_path or not os.path.isfile(source_path):
        logger.warning("[capability] source 文件不存在，跳过 ingest: %s", source_path)
        return

    effective_config = llm_config or _get_llm_config_from_settings()

    # 方式1：直接调用 ingest 模块（同进程，更高效）
    try:
        from backend.services.wiki.ingest import auto_ingest
        from backend.config import GLOBAL_WIKI_DIR

        try:
            await auto_ingest(GLOBAL_WIKI_DIR, source_path, effective_config)
            logger.info("[capability] 全局 Wiki ingest 完成（直接调用: %s）", source_path)
        except Exception as single_err:
            logger.warning("[capability] 文件 %s ingest 失败: %s", source_path, single_err)
        return
    except Exception as e:
        logger.warning("[capability] 直接调用 ingest 失败，回退到 HTTP API: %s", e)

    # 方式2：通过 HTTP API 触发（跨进程兼容）
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("http://localhost:8000/api/wiki/ingest")
            if resp.status_code == 200:
                logger.info("[capability] 全局 Wiki ingest 已触发（HTTP API）")
            else:
                logger.warning(
                    "[capability] 全局 Wiki ingest 触发失败，状态码: %d",
                    resp.status_code,
                )
    except Exception as e:
        logger.warning("[capability] 全局 Wiki ingest HTTP 调用失败: %s", e)
