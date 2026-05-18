"""
Wiki 深度研究模块

从 TypeScript 参考项目 llm_wiki-0.4.9/src/lib/deep-research.ts 移植，
适配 Python FastAPI 环境。

功能：
- 深度研究管线（run_deep_research）：
  1. LLM 生成多个搜索查询
  2. 多查询网络搜索
  3. LLM 综合搜索结果
  4. 保存为 Wiki 页面
  5. 自动摄入生成实体/概念

依赖：
- web_search.py: 网络搜索
- llm_client.py: LLM 流式调用
- ingest.py: 自动摄入
"""

import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Callable

from backend.services.wiki.web_search import web_search
from backend.services.wiki.llm_client import stream_chat


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_language_directive(fallback_text: str = "") -> str:
    """构建语言指令，注入到 LLM 系统提示词中

    根据回退文本自动检测语言，生成强制输出语言指令。

    Args:
        fallback_text: 用于自动检测语言的回退文本
    Returns:
        语言指令字符串
    """
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", fallback_text))
    lang_name = "Chinese" if has_cjk else "English"

    return "\n".join([
        f"## MANDATORY OUTPUT LANGUAGE: {lang_name}",
        "",
        f"You MUST write your entire response (including wiki page titles, content, descriptions, "
        f"summaries, and any generated text) in **{lang_name}**.",
        f"The source material or wiki content may be in a different language, "
        f"but this is IRRELEVANT to your output language.",
        f"Ignore the language of any source content. Generate everything in {lang_name} only.",
        f"Proper nouns should use standard {lang_name} transliteration when appropriate.",
        f"DO NOT use any other language. This overrides all other instructions.",
    ])


def _strip_thinking_blocks(text: str) -> str:
    """剥离 LLM 输出中的思考块标签

    处理 <thinking> 和 <think> 标签（包括未闭合的情况）。

    Args:
        text: 原始文本
    Returns:
        清理后的文本
    """
    # 去除闭合的 <thinking>...</thinking> 或 块
    cleaned = re.sub(
        r"<think(?:ing)?>\s*[\s\S]*?</think(?:ing)?>\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # 去除未闭合的 <thinking> 或 <think> 块（到文本末尾）
    cleaned = re.sub(
        r"<think(?:ing)?>\s*[\s\S]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.lstrip()


def _read_file_safe(path: str) -> str:
    """安全读取文件内容，失败返回空字符串

    Args:
        path: 文件路径
    Returns:
        文件内容字符串
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def _write_file_safe(path: str, content: str) -> bool:
    """安全写入文件，自动创建父目录

    Args:
        path: 文件路径
        content: 要写入的内容
    Returns:
        是否写入成功
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 搜索查询生成
# ---------------------------------------------------------------------------

async def _generate_search_queries(
    topic: str,
    llm_config: dict,
) -> list[str]:
    """使用 LLM 为研究主题生成多个搜索查询

    通过 LLM 分析研究主题，生成多个不同角度的搜索查询，
    以获取更全面的搜索结果。

    Args:
        topic: 研究主题
        llm_config: LLM 配置字典
    Returns:
        搜索查询字符串列表
    """
    prompt = "\n".join([
        f"Generate 3-5 diverse web search queries for researching the topic: \"{topic}\"",
        "",
        "Requirements:",
        "- Each query should approach the topic from a different angle",
        "- Include both broad and specific queries",
        "- Queries should be in the same language as the topic",
        "- Return ONLY a JSON array of query strings, no other text",
        '- Example: ["query 1", "query 2", "query 3"]',
    ])

    raw = ""
    had_error = False

    def on_token(token: str):
        nonlocal raw
        raw += token

    def on_done():
        pass

    def on_error(error: Exception):
        nonlocal had_error
        had_error = True

    await stream_chat(
        llm_config,
        [{"role": "user", "content": prompt}],
        on_token=on_token,
        on_done=on_done,
        on_error=on_error,
    )

    if had_error or not raw.strip():
        return [topic]

    # 尝试从响应中提取 JSON 数组
    try:
        # 去除代码围栏
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        # 查找 JSON 数组
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            queries = json.loads(cleaned[start:end + 1])
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return queries
    except (json.JSONDecodeError, TypeError):
        pass

    # 回退到原始主题
    return [topic]


# ---------------------------------------------------------------------------
# 深度研究主流程
# ---------------------------------------------------------------------------

async def run_deep_research(
    project_path: str,
    topic: str,
    llm_config: dict,
    search_config: dict,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """执行深度研究管线

    完整流程：
    1. LLM 生成多个搜索查询
    2. 多查询网络搜索，合并去重 URL
    3. LLM 综合搜索结果
    4. 保存为 Wiki 页面
    5. 自动摄入生成实体/概念

    Args:
        project_path: 项目根目录路径
        topic: 研究主题
        llm_config: LLM 配置字典
        search_config: 搜索配置字典（提供商、API Key 等）
        on_progress: 进度回调函数，接收进度状态字典
    Returns:
        研究结果字典，包含：
        - taskId: 任务 ID
        - topic: 研究主题
        - status: 任务状态（done / error）
        - report: 综合报告内容
        - findings: 搜索发现列表
        - references: 参考文献列表
    """
    task_id = f"research-{uuid.uuid4().hex[:8]}"

    def _notify(status: str, detail: str = ""):
        """发送进度通知

        Args:
            status: 当前状态
            detail: 状态详情
        """
        if on_progress:
            on_progress({
                "taskId": task_id,
                "topic": topic,
                "status": status,
                "detail": detail,
            })

    try:
        # 步骤 1：LLM 生成搜索查询
        _notify("generating-queries", "Generating search queries...")

        queries = await _generate_search_queries(topic, llm_config)

        # 步骤 2：多查询网络搜索
        _notify("searching", f"Searching with {len(queries)} queries...")

        all_results = []
        seen_urls = set()

        for query in queries:
            try:
                results = await web_search(query, search_config, max_results=5)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
            except Exception:
                # 某个查询失败不影响其他查询
                continue

        if not all_results:
            _notify("done", "No web results found.")
            return {
                "taskId": task_id,
                "topic": topic,
                "status": "done",
                "report": "No web results found.",
                "findings": [],
                "references": [],
            }

        # 步骤 3：LLM 综合搜索结果
        _notify("synthesizing", "Synthesizing research results...")

        # 格式化搜索上下文
        search_context = "\n\n".join(
            f"[{i + 1}] **{r.get('title', 'Untitled')}** ({r.get('source', '')})\n{r.get('snippet', '')}"
            for i, r in enumerate(all_results)
        )

        # 读取现有 wiki/index.md 以启用交叉引用
        wiki_root = os.path.join(project_path, "wiki")
        wiki_index = _read_file_safe(os.path.join(wiki_root, "index.md"))

        # 构建语言指令
        language_directive = _build_language_directive(topic)

        # 构建系统提示词
        system_parts = [
            "You are a research assistant. Synthesize the web search results into a comprehensive wiki page.",
            "",
            language_directive,
            "",
            "## Cross-referencing (IMPORTANT)",
            "- The wiki already has existing pages listed in the Wiki Index below.",
            "- When your synthesis mentions an entity or concept that exists in the wiki, "
            "ALWAYS use [[wikilink]] syntax to link to it.",
            "- For example, if the wiki has an entity 'anthropic', write [[anthropic]] when mentioning it.",
            "- This is critical for connecting new research to existing knowledge in the graph.",
            "",
            "## Writing Rules",
            "- Organize into clear sections with headings",
            "- Cite web sources using [N] notation",
            "- Note contradictions or gaps",
            "- Suggest additional sources worth finding",
            "- Neutral, encyclopedic tone",
        ]

        if wiki_index:
            system_parts.extend([
                "",
                "## Existing Wiki Index (link to these pages with [[wikilink]])",
                wiki_index,
            ])

        system_prompt = "\n".join(system_parts)

        # 调用 LLM 进行综合
        accumulated = ""
        had_error = False

        def on_token(token: str):
            """流式 token 回调：累积综合文本"""
            nonlocal accumulated
            accumulated += token

        def on_done():
            """流式完成回调"""
            pass

        def on_error(error: Exception):
            """流式错误回调"""
            nonlocal had_error
            had_error = True

        await stream_chat(
            llm_config,
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Research topic: **{topic}**\n\n"
                        f"## Web Search Results\n\n{search_context}\n\n"
                        "Synthesize into a wiki page."
                    ),
                },
            ],
            on_token=on_token,
            on_done=on_done,
            on_error=on_error,
        )

        if had_error:
            _notify("error", "LLM synthesis failed.")
            return {
                "taskId": task_id,
                "topic": topic,
                "status": "error",
                "report": "",
                "findings": all_results,
                "references": [],
            }

        # 步骤 4：保存为 Wiki 页面
        _notify("saving", "Saving research page...")

        date = datetime.now().strftime("%Y-%m-%d")
        # 生成 slug：小写化、去除特殊字符、空格转连字符
        slug = re.sub(r"[^a-z0-9\s-]", "", topic.lower()).strip()
        slug = re.sub(r"\s+", "-", slug)[:50]
        file_name = f"research-{slug}-{date}.md"
        file_path = os.path.join(wiki_root, "queries", file_name)

        # 构建参考文献
        references = [
            f"{i + 1}. [{r.get('title', 'Untitled')}]({r.get('url', '')}) — {r.get('source', '')}"
            for i, r in enumerate(all_results)
        ]

        # 剥离思考块后保存
        cleaned_synthesis = _strip_thinking_blocks(accumulated)

        # 构建页面内容
        escaped_topic = topic.replace('"', '\\"')
        page_content = "\n".join([
            "---",
            "type: query",
            f'title: "Research: {escaped_topic}"',
            f"created: {date}",
            "origin: deep-research",
            "tags: [research]",
            "---",
            "",
            f"# Research: {topic}",
            "",
            cleaned_synthesis,
            "",
            "## References",
            "",
            "\n".join(references),
            "",
        ])

        saved = _write_file_safe(file_path, page_content)
        saved_path = f"wiki/queries/{file_name}" if saved else ""

        # 步骤 5：自动摄入
        if saved:
            _notify("ingesting", "Auto-ingesting research page...")
            try:
                from backend.services.wiki.ingest import auto_ingest
                await auto_ingest(project_path, os.path.join(project_path, saved_path), llm_config)
            except Exception:
                # 摄入失败不影响研究结果的返回
                pass

        _notify("done", f"Research completed: {topic}")

        return {
            "taskId": task_id,
            "topic": topic,
            "status": "done",
            "report": cleaned_synthesis,
            "findings": all_results,
            "references": references,
            "savedPath": saved_path,
        }

    except Exception as err:
        error_message = str(err)
        _notify("error", error_message)
        return {
            "taskId": task_id,
            "topic": topic,
            "status": "error",
            "report": "",
            "findings": [],
            "references": [],
            "error": error_message,
        }
