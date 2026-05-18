"""
Wiki 路由模块 — 全局单例架构

所有 Wiki 功能基于全局单例目录（data/global-wiki/），不再按项目隔离。
路由路径已去除 {projectId}，统一使用全局路径常量。

目录结构：
  data/global-wiki/
    sources/     — 摄入源文件（.md）
    wiki/        — 生成的 Wiki 页面
    .llm-wiki/   — 元数据与设置
"""

import os
import json
import asyncio
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.wiki.ingest import auto_ingest
from backend.services.wiki.search import search_wiki
from backend.services.wiki.wiki_graph import build_wiki_graph
from backend.services.wiki.graph_insights import find_surprising_connections, detect_knowledge_gaps
from backend.services.wiki.lint import run_structural_lint, run_semantic_lint
from backend.services.wiki.auto_evolve import run_auto_evolve, detect_git_changes, trigger_incremental_ingest
from backend.services.wiki.deep_research import run_deep_research
from backend.services.wiki.sweep_reviews import sweep_resolved_reviews
from backend.services.wiki.concept_staleness import run_staleness_check
from backend.services.wiki.ingest_queue import get_queue, get_queue_summary, restore_queue
from backend.services.wiki.llm_client import stream_chat
from backend.config import (
    GLOBAL_WIKI_DIR,
    GLOBAL_WIKI_SOURCES_DIR,
    GLOBAL_WIKI_WIKI_DIR,
    GLOBAL_WIKI_META_DIR,
)
from backend.services.project_service import (
    get_setting,
    create_research_task,
    get_research_tasks_by_project_id,
    update_research_task,
    create_review_item,
    get_review_items_by_project_id,
    resolve_review_item,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

# 全局 Wiki 状态与设置缓存（内存级，无需 projectId 键）
_wiki_status: dict = {}
_wiki_settings: dict = {}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _build_file_tree(directory: str, prefix: str = "") -> list:
    """递归构建目录文件树

    遍历指定目录，生成包含文件和子目录的嵌套列表结构，
    忽略以点号开头的隐藏文件/目录。

    Args:
        directory: 要扫描的目录路径
        prefix: 当前相对路径前缀（递归使用）
    Returns:
        文件树列表，每项包含 name、is_dir、path、children 字段
    """
    result = []
    if not os.path.exists(directory):
        return result
    try:
        entries = sorted(os.listdir(directory))
    except Exception:
        return result
    for entry in entries:
        if entry.startswith("."):
            continue
        full_path = os.path.join(directory, entry)
        rel_path = f"{prefix}/{entry}" if prefix else entry
        if os.path.isdir(full_path):
            result.append({
                "name": entry,
                "is_dir": True,
                "path": rel_path,
                "children": _build_file_tree(full_path, rel_path),
            })
        else:
            result.append({
                "name": entry,
                "is_dir": False,
                "path": rel_path,
            })
    return result


def _build_llm_config(body) -> dict:
    """从请求体提取 LLM 配置字段

    从 Pydantic 模型或请求体中提取 provider/model/apiKey/baseUrl，
    仅收集非空字段。

    Args:
        body: 请求体对象（需有对应属性）
    Returns:
        LLM 配置字典，仅包含非空字段
    """
    if body is None:
        return {}
    config = {}
    if hasattr(body, "providerId") and body.providerId:
        config["provider"] = body.providerId
    if hasattr(body, "modelId") and body.modelId:
        config["model"] = body.modelId
    if hasattr(body, "apiKey") and body.apiKey:
        config["apiKey"] = body.apiKey
    if hasattr(body, "baseUrl") and body.baseUrl:
        config["baseUrl"] = body.baseUrl
    return config


def _ensure_llm_config(llm_config: dict) -> dict:
    """确保 LLM 配置可用，若请求未提供则从系统设置回退

    当请求体未携带 LLM 配置（provider/model/apiKey）时，
    尝试从 settings 表读取用户在系统设置中配置的默认模型信息，
    保证编译和查询操作始终有可用的 LLM 配置。

    如果选中的提供商没有 API Key，自动回退到第一个有 Key 的提供商，
    并使用该提供商的默认模型。

    Args:
        llm_config: 从请求体构建的 LLM 配置字典
    Returns:
        合并后的 LLM 配置字典
    """
    if llm_config and llm_config.get("provider") and llm_config.get("apiKey"):
        return llm_config

    # 各提供商的默认模型
    _DEFAULT_MODELS = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "google": "gemini-2.0-flash",
        "glm": "glm-4-flash",
        "qwen": "qwen-plus",
        "deepseek": "deepseek-chat",
        "kimi": "moonshot-v1-8k",
        "minimax": "MiniMax-Text-01",
        "siliconflow": "deepseek-ai/DeepSeek-V3",
        "doubao": "doubao-pro-4k",
        "openrouter": "openai/gpt-4o-mini",
        "grok": "grok-3-mini",
        "tencent-hunyuan": "hunyuan-lite",
        "xiaomi": " MiMo-7B-RL",
        "ollama": "llama3",
    }

    # 从系统设置回退
    try:
        raw = get_setting("settings-storage")
        if not raw:
            return llm_config

        data = json.loads(raw)
        # settings-storage 的结构为 {"state": {...}, "version": 1}
        # LLM 配置在 state 下
        state = data.get("state", data)
        fallback = {}

        provider_id = state.get("providerId")
        model_id = state.get("modelId")
        if provider_id:
            fallback["provider"] = provider_id
        if model_id:
            fallback["model"] = model_id

        providers_config = state.get("providersConfig", {})
        if provider_id and provider_id in providers_config:
            provider_cfg = providers_config[provider_id]
            api_key = provider_cfg.get("apiKey")
            base_url = provider_cfg.get("baseUrl") or provider_cfg.get("defaultBaseUrl")
            if api_key:
                fallback["apiKey"] = api_key
            if base_url:
                fallback["baseUrl"] = base_url

        # 如果选中的提供商没有 API Key，回退到第一个有 Key 的提供商
        if not fallback.get("apiKey") and providers_config:
            for pid, pcfg in providers_config.items():
                fallback_key = pcfg.get("apiKey")
                if fallback_key:
                    fallback["provider"] = pid
                    fallback["apiKey"] = fallback_key
                    fallback["model"] = pcfg.get("modelId") or _DEFAULT_MODELS.get(pid, "gpt-4o-mini")
                    base_url = pcfg.get("baseUrl") or pcfg.get("defaultBaseUrl")
                    if base_url:
                        fallback["baseUrl"] = base_url
                    break

        # 请求体配置优先，回退配置补缺
        merged = {**fallback, **llm_config}
        return merged
    except Exception as e:
        print(f"[Wiki] 从 settings 读取 LLM 配置失败: {e}")
        return llm_config


def _get_wiki_settings() -> dict:
    """从 settings-storage 读取 Wiki 专用配置

    解析前端设置面板存储的 Wiki 相关参数，包括：
    - 向量检索配置（wikiVectorEnabled/wikiEmbeddingModel/wikiEmbeddingEndpoint/wikiEmbeddingApiKey）
    - 输出语言（wikiLanguage）
    - 上下文窗口（wikiContextWindow）
    - 深度研究搜索配置（researchSearchProvider/researchApiKey/researchMaxConcurrent）
    - 自动进化配置（evolutionGitAutoIngest/evolutionLintSchedule/evolutionStalenessCheck/evolutionCrossProject）
    - 存储配置（storageVectorPath/storageChatRetention/storageAutoCleanup）

    Returns:
        Wiki 设置字典，结构：
        {
            "vector": {"enabled": bool, "model": str, "endpoint": str, "apiKey": str},
            "language": str,
            "contextWindow": int,
            "search": {"provider": str, "apiKey": str, "maxConcurrent": int},
            "evolution": {"gitAutoIngest": bool, "lintSchedule": str, "stalenessCheck": bool, "crossProject": bool},
            "storage": {"vectorPath": str, "chatRetention": str, "autoCleanup": bool},
        }
    """
    defaults = {
        "vector": {"enabled": False, "model": "", "endpoint": "", "apiKey": ""},
        "language": "auto",
        "contextWindow": 8000,
        "search": {"provider": "none", "apiKey": "", "maxConcurrent": 3},
        "evolution": {"gitAutoIngest": True, "lintSchedule": "off", "stalenessCheck": False, "crossProject": False},
        "storage": {"vectorPath": "", "chatRetention": "90d", "autoCleanup": False},
    }

    try:
        raw = get_setting("settings-storage")
        if not raw:
            return defaults

        data = json.loads(raw)
        state = data.get("state", data)

        return {
            "vector": {
                "enabled": bool(state.get("wikiVectorEnabled", False)),
                "model": str(state.get("wikiEmbeddingModel", "")),
                "endpoint": str(state.get("wikiEmbeddingEndpoint", "")),
                "apiKey": str(state.get("wikiEmbeddingApiKey", "")),
            },
            "language": str(state.get("wikiLanguage", "auto")),
            "contextWindow": int(state.get("wikiContextWindow", 8000)),
            "search": {
                "provider": str(state.get("researchSearchProvider", "none")),
                "apiKey": str(state.get("researchApiKey", "")),
                "maxConcurrent": int(state.get("researchMaxConcurrent", 3)),
            },
            "evolution": {
                "gitAutoIngest": bool(state.get("evolutionGitAutoIngest", True)),
                "lintSchedule": str(state.get("evolutionLintSchedule", "off")),
                "stalenessCheck": bool(state.get("evolutionStalenessCheck", False)),
                "crossProject": bool(state.get("evolutionCrossProject", False)),
            },
            "storage": {
                "vectorPath": str(state.get("storageVectorPath", "")),
                "chatRetention": str(state.get("storageChatRetention", "90d")),
                "autoCleanup": bool(state.get("storageAutoCleanup", False)),
            },
        }
    except Exception as e:
        print(f"[Wiki] 从 settings 读取 Wiki 配置失败: {e}")
        return defaults


def _try_read_file(path: str) -> str:
    """尝试读取文件内容，失败返回空字符串

    Args:
        path: 文件绝对路径
    Returns:
        文件内容字符串，读取失败时返回空字符串
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _read_global_wiki_settings() -> dict:
    """从全局 Wiki 元数据目录读取设置文件

    读取 GLOBAL_WIKI_META_DIR/settings.json，不存在则返回空字典。

    Returns:
        设置字典
    """
    settings_path = os.path.join(GLOBAL_WIKI_META_DIR, "settings.json")
    content = _try_read_file(settings_path)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
    return {}


def _write_global_wiki_settings(settings: dict) -> None:
    """将设置写入全局 Wiki 元数据目录

    确保 GLOBAL_WIKI_META_DIR 存在后写入 settings.json。

    Args:
        settings: 要写入的设置字典
    """
    os.makedirs(GLOBAL_WIKI_META_DIR, exist_ok=True)
    settings_path = os.path.join(GLOBAL_WIKI_META_DIR, "settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 路由：摄入队列
# ---------------------------------------------------------------------------


@router.get("/queue")
def get_ingest_queue():
    """获取全局摄入队列状态

    返回当前摄入队列中的所有任务及其状态摘要。
    全局单例模式下，队列不再按项目区分。

    Returns:
        队列任务列表和状态摘要（pending/processing/completed/failed 计数）
    """
    try:
        restore_queue("global", GLOBAL_WIKI_DIR)
        tasks = get_queue()
        summary = get_queue_summary()
        return {
            "queue": [asdict(t) for t in tasks],
            "summary": summary,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：文件树
# ---------------------------------------------------------------------------


@router.get("/filetree")
def get_filetree():
    """获取全局 Wiki 文件树

    扫描 GLOBAL_WIKI_WIKI_DIR 目录，返回嵌套的文件树结构。

    Returns:
        文件树列表
    """
    try:
        tree = _build_file_tree(GLOBAL_WIKI_WIKI_DIR)
        return tree
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：全局 Wiki 设置
# ---------------------------------------------------------------------------


@router.get("/settings")
def get_wiki_settings():
    """获取全局 Wiki 设置

    从 GLOBAL_WIKI_META_DIR/settings.json 读取设置，
    不存在时返回默认值。

    Returns:
        Wiki 设置字典
    """
    try:
        saved = _read_global_wiki_settings()
        if saved:
            return saved
        # 默认设置
        return {
            "autoIndex": False,
            "indexOnGitChange": True,
            "maxFileSize": 1024 * 1024,
            "excludePatterns": ["node_modules", ".git", "__pycache__", ".next"],
            "chunkSize": 1000,
            "chunkOverlap": 200,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.put("/settings")
async def update_wiki_settings(request: Request):
    """更新全局 Wiki 设置

    将请求体 JSON 写入 GLOBAL_WIKI_META_DIR/settings.json。

    Args:
        request: FastAPI 请求对象
    Returns:
        操作结果
    """
    try:
        body = await request.json()
        _wiki_settings.update(body)
        _write_global_wiki_settings(body)
        return {"success": True}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：Wiki 状态
# ---------------------------------------------------------------------------


@router.get("/status")
def get_wiki_status():
    """获取全局 Wiki 状态

    返回当前 Wiki 引擎的运行状态，包括摄入进度、健康评分等。
    全局单例模式下不再关联特定项目。

    Returns:
        状态字典，包含 status、progress、message 等字段
    """
    try:
        # 读取全局 Wiki 目录基本信息
        wiki_exists = os.path.exists(GLOBAL_WIKI_WIKI_DIR)
        sources_exist = os.path.exists(GLOBAL_WIKI_SOURCES_DIR)

        # 统计 Wiki 页面数量
        page_count = 0
        if wiki_exists:
            for root, _dirs, files in os.walk(GLOBAL_WIKI_WIKI_DIR):
                page_count += sum(1 for f in files if f.endswith(".md"))

        # 统计源文件数量
        source_count = 0
        if sources_exist:
            for root, _dirs, files in os.walk(GLOBAL_WIKI_SOURCES_DIR):
                source_count += sum(1 for f in files if f.endswith(".md"))

        return {
            "wikiExists": wiki_exists,
            "sourcesExist": sources_exist,
            "pageCount": page_count,
            "sourceCount": source_count,
            "status": _wiki_status.get("status", "none"),
            "progress": _wiki_status.get("progress", 0),
            "message": _wiki_status.get("message", ""),
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：摄入
# ---------------------------------------------------------------------------


class IngestInput(BaseModel):
    """摄入请求体"""
    force: bool = False
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    options: Optional[dict] = None


@router.post("/ingest")
async def ingest_wiki(body: IngestInput = None):
    """触发全局 Wiki 摄入

    扫描 GLOBAL_WIKI_SOURCES_DIR 目录下的所有 .md 文件，
    逐个执行两步思维链摄入（分析 -> 生成），输出到 GLOBAL_WIKI_WIKI_DIR。

    Args:
        body: 摄入参数，包含 LLM 配置和 force 标志
    Returns:
        摄入结果，包含写入的文件路径列表
    """
    try:
        # 确保源目录和 Wiki 目录存在
        os.makedirs(GLOBAL_WIKI_SOURCES_DIR, exist_ok=True)
        os.makedirs(GLOBAL_WIKI_WIKI_DIR, exist_ok=True)

        llm_config = _ensure_llm_config(_build_llm_config(body))

        # 读取 Wiki 设置，传递给 auto_ingest
        wiki_cfg = _get_wiki_settings()

        # 扫描 sources 目录下所有 .md 文件
        source_files: list[str] = []
        for entry in sorted(os.listdir(GLOBAL_WIKI_SOURCES_DIR)):
            if entry.endswith(".md") and os.path.isfile(
                os.path.join(GLOBAL_WIKI_SOURCES_DIR, entry)
            ):
                source_files.append(entry)

        if not source_files:
            _wiki_status.update({
                "status": "completed",
                "progress": 100,
                "message": "源目录无 .md 文件可摄入",
            })
            return {
                "status": "completed",
                "filesWritten": [],
                "message": "源目录无 .md 文件可摄入",
            }

        all_written: list[str] = []
        total = len(source_files)

        for idx, source_file in enumerate(source_files):
            source_path = os.path.join(GLOBAL_WIKI_SOURCES_DIR, source_file)

            _wiki_status.update({
                "status": "indexing",
                "progress": int((idx / total) * 100),
                "message": f"正在摄入 {source_file}（{idx + 1}/{total}）...",
            })

            written_files = await auto_ingest(
                GLOBAL_WIKI_DIR, source_path, llm_config, wiki_config=wiki_cfg
            )
            all_written.extend(written_files)

        _wiki_status.update({
            "status": "completed",
            "progress": 100,
            "message": "索引构建完成",
            "indexedFiles": len(all_written),
            "totalFiles": len(all_written),
        })

        return {
            "status": "completed",
            "filesWritten": all_written,
        }
    except Exception as err:
        _wiki_status.update({
            "status": "failed",
            "progress": 0,
            "message": str(err),
        })
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：查询
# ---------------------------------------------------------------------------


class QueryInput(BaseModel):
    """查询请求体"""
    question: str
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    options: Optional[dict] = None
    # 向量检索配置（由前端 settings-store 传入）
    vectorEnabled: Optional[bool] = None
    embeddingModel: Optional[str] = None
    embeddingEndpoint: Optional[str] = None
    embeddingApiKey: Optional[str] = None


@router.post("/query")
async def query_wiki(body: QueryInput):
    """查询全局 Wiki 知识库

    基于全局 Wiki 知识库的搜索结果 + LLM 生成回答。
    不再使用 GraphifyQuery 双源合并和 QueryRouter 智能路由，
    直接搜索全局 Wiki 页面后流式生成回答。

    Args:
        body: 查询请求体，包含 question 和 LLM 配置
    Returns:
        SSE 流式响应，包含来源和回答内容
    """
    try:
        llm_config = _ensure_llm_config(_build_llm_config(body))

        # --- 搜索全局 Wiki 知识库 ---
        wiki_result = None
        wiki_source_paths = []  # Wiki 搜索结果页面路径列表

        try:
            # 读取 Wiki 设置，将 vector 配置映射为 search_wiki 期望的格式
            # 优先使用请求体中的向量配置，未提供时回退到 settings-store
            wiki_cfg = _get_wiki_settings()
            search_config = {
                "vector_enabled": body.vectorEnabled if body.vectorEnabled is not None else wiki_cfg["vector"]["enabled"],
                "embedding_model": body.embeddingModel or wiki_cfg["vector"]["model"],
                "embedding_endpoint": body.embeddingEndpoint or wiki_cfg["vector"]["endpoint"],
                "embedding_api_key": body.embeddingApiKey or wiki_cfg["vector"]["apiKey"],
            }
            search_results = await search_wiki(GLOBAL_WIKI_DIR, body.question, config=search_config)
            if search_results:
                # 读取搜索结果对应的 wiki 页面内容，构建上下文
                wiki_parts = []
                for sr in search_results[:5]:
                    wiki_source_paths.append(sr["path"])
                    page_path = os.path.join(GLOBAL_WIKI_WIKI_DIR, sr["path"])
                    content = _try_read_file(page_path)
                    if content:
                        wiki_parts.append(f"### {sr['title']}\n{content[:2000]}")
                if wiki_parts:
                    wiki_result = "\n\n".join(wiki_parts)
        except Exception:
            wiki_result = None

        has_wiki = bool(wiki_result and wiki_result.strip())

        async def event_generator():
            """SSE 事件生成器，流式输出查询结果"""
            yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"

            # 发送数据源信息
            yield f"data: {json.dumps({'type': 'sources', 'sources': wiki_source_paths[:10] if has_wiki else []}, ensure_ascii=False)}\n\n"

            full_answer = ""

            if has_wiki:
                # 有 Wiki 搜索结果：基于 Wiki 内容流式生成回答
                system_prompt = (
                    "You are a helpful wiki assistant. Answer questions based on the wiki content below. "
                    "Use [[wikilink]] syntax to reference wiki pages when relevant.\n\n"
                    f"## Wiki Content\n{wiki_result[:8000]}"
                )

                async def on_token(token: str):
                    """流式 token 回调，累积完整回答"""
                    nonlocal full_answer
                    full_answer += token

                try:
                    await stream_chat(
                        llm_config,
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": body.question},
                        ],
                        on_token=on_token,
                    )
                except Exception as err:
                    full_answer = f"查询出错: {str(err)}"

            else:
                # 没有搜索结果，回退到 index.md
                index_content = _try_read_file(os.path.join(GLOBAL_WIKI_WIKI_DIR, "index.md"))

                system_prompt = "You are a helpful wiki assistant. Answer questions based on the wiki content below. Use [[wikilink]] syntax to reference wiki pages when relevant."
                if index_content:
                    system_prompt += f"\n\n## Wiki Index\n{index_content[:8000]}"

                async def on_token(token: str):
                    """流式 token 回调，累积完整回答"""
                    nonlocal full_answer
                    full_answer += token

                try:
                    await stream_chat(
                        llm_config,
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": body.question},
                        ],
                        on_token=on_token,
                    )
                except Exception as err:
                    full_answer = f"查询出错: {str(err)}"

            # 流式输出回答内容
            for char in full_answer:
                yield f"data: {json.dumps({'type': 'content', 'content': char}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)

            yield f"data: {json.dumps({'type': 'done', 'answer': full_answer}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：自动进化
# ---------------------------------------------------------------------------


class EvolveInput(BaseModel):
    """自动进化请求体"""
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    options: Optional[dict] = None


@router.post("/evolve")
async def evolve_wiki(body: EvolveInput = None):
    """触发全局 Wiki 自动进化

    根据自动进化配置决定执行哪些步骤：
    - lint + graph 始终执行（基础功能）
    - gitAutoIngest: 执行 Git 变更检测和增量摄入
    - stalenessCheck: 执行概念过时检测
    - crossProject: 执行跨项目关联分析

    Args:
        body: 进化参数，包含 LLM 配置信息
    Returns:
        进化报告，包含 lint 问题数、洞察数、知识缺口数等
    """
    try:
        llm_config = _ensure_llm_config(_build_llm_config(body))
        wiki_cfg = _get_wiki_settings()
        evo = wiki_cfg.get("evolution", {})

        # 基础步骤：lint + graph 始终执行
        lint_results = await run_structural_lint(GLOBAL_WIKI_DIR)

        graph_data = await build_wiki_graph(GLOBAL_WIKI_DIR)
        insights = find_surprising_connections(
            graph_data.get("nodes", []),
            graph_data.get("edges", []),
            graph_data.get("communities", []),
        )
        gaps = detect_knowledge_gaps(
            graph_data.get("nodes", []),
            graph_data.get("edges", []),
            graph_data.get("communities", []),
        )

        new_concepts = [g for g in gaps if g.get("type") == "isolated-node"]
        updated_concepts = [i for i in insights if i.get("score", 0) >= 5]

        report = {
            "lintIssues": len(lint_results),
            "surprisingConnections": len(insights),
            "knowledgeGaps": len(gaps),
        }

        # 可选增强：Git 变更检测和增量摄入
        ingest_result = None
        cleanup_result = None
        if evo.get("gitAutoIngest"):
            try:
                git_changes = detect_git_changes(GLOBAL_WIKI_DIR)
                added_files = git_changes.get("added", [])
                modified_files = git_changes.get("modified", [])
                deleted_files = git_changes.get("deleted", [])

                # 新增 + 修改文件 → 增量摄入
                all_ingest_files = added_files + modified_files
                if all_ingest_files:
                    ingest_result = await trigger_incremental_ingest(
                        GLOBAL_WIKI_DIR, all_ingest_files, llm_config
                    )
                    report["ingestProcessed"] = ingest_result.get("processed", 0)
                    report["ingestFailed"] = ingest_result.get("failed", 0)

                # 删除文件 → 级联清理
                if deleted_files:
                    from backend.services.wiki.auto_evolve import trigger_cascade_cleanup
                    cleanup_result = await trigger_cascade_cleanup(
                        GLOBAL_WIKI_DIR, deleted_files
                    )
                    report["cleanupCleaned"] = cleanup_result.get("cleaned", 0)
                    report["cleanupFailed"] = cleanup_result.get("failed", 0)

                report["gitAdded"] = len(added_files)
                report["gitModified"] = len(modified_files)
                report["gitDeleted"] = len(deleted_files)
            except Exception as err:
                report["ingestError"] = str(err)

        # 可选增强：概念过时检测
        staleness_result = None
        if evo.get("stalenessCheck"):
            try:
                staleness_result = await run_staleness_check(
                    GLOBAL_WIKI_DIR, llm_config, project_id=0
                )
                report["stalenessScanned"] = staleness_result.get("scanned", 0)
                report["stalenessCount"] = staleness_result.get("stale_count", 0)
            except Exception as err:
                report["stalenessError"] = str(err)

        # 可选增强：跨项目关联分析
        cross_project_result = None
        if evo.get("crossProject"):
            try:
                from backend.services.wiki.cross_project import run_cross_project_analysis
                cross_project_result = await run_cross_project_analysis(
                    GLOBAL_WIKI_DIR, llm_config
                )
                report["crossProjectLinks"] = len(cross_project_result.get("links", []))
            except Exception as err:
                report["crossProjectError"] = str(err)

        return {
            "status": "completed",
            "report": report,
            "newConcepts": new_concepts,
            "updatedConcepts": updated_concepts,
            "gaps": gaps,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：知识图谱
# ---------------------------------------------------------------------------


@router.get("/graph")
async def get_wiki_graph():
    """获取全局 Wiki 知识图谱

    从全局 Wiki 页面构建知识图谱，返回节点、边和社区信息。

    Returns:
        知识图谱数据，包含 nodes、edges、communities 字段
    """
    try:
        if not os.path.exists(GLOBAL_WIKI_WIKI_DIR):
            return {"nodes": [], "edges": [], "communities": []}

        graph_data = await build_wiki_graph(GLOBAL_WIKI_DIR)

        return {
            "nodes": graph_data.get("nodes", []),
            "edges": graph_data.get("edges", []),
            "communities": graph_data.get("communities", []),
            "sourceToName": graph_data.get("sourceToName", {}),
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/graph-insights")
async def get_graph_insights():
    """获取全局 Wiki 图谱洞察

    从知识图谱中提取惊喜连接、关键概念和知识缺口。

    Returns:
        洞察数据，包含 insights、keyConcepts、gaps 字段
    """
    try:
        if not os.path.exists(GLOBAL_WIKI_WIKI_DIR):
            return {
                "insights": [],
                "keyConcepts": [],
                "gaps": [],
            }

        graph_data = await build_wiki_graph(GLOBAL_WIKI_DIR)

        insights = find_surprising_connections(
            graph_data.get("nodes", []),
            graph_data.get("edges", []),
            graph_data.get("communities", []),
        )
        gaps = detect_knowledge_gaps(
            graph_data.get("nodes", []),
            graph_data.get("edges", []),
            graph_data.get("communities", []),
        )

        nodes = graph_data.get("nodes", [])
        key_concepts = sorted(nodes, key=lambda n: n.get("linkCount", 0), reverse=True)[:10]

        return {
            "insights": insights,
            "keyConcepts": key_concepts,
            "gaps": gaps,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：Lint 检查
# ---------------------------------------------------------------------------


class LintInput(BaseModel):
    """Lint 检查请求体"""
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    filePath: Optional[str] = None
    options: Optional[dict] = None


@router.get("/lint")
async def get_lint_status():
    """获取全局 Wiki 结构检查结果

    对全局 Wiki 执行结构检查（孤立页面、断链、无出链等）。

    Returns:
        检查结果列表
    """
    try:
        if not os.path.exists(GLOBAL_WIKI_WIKI_DIR):
            return {"status": "none", "results": []}

        results = await run_structural_lint(GLOBAL_WIKI_DIR)

        return {
            "status": "completed",
            "results": results,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("/lint")
async def run_lint(body: LintInput = None):
    """执行全局 Wiki 完整检查（结构 + 语义）

    先执行结构检查，若提供了 LLM 配置则追加语义检查。

    Args:
        body: 检查参数，包含 LLM 配置信息
    Returns:
        合并后的检查结果列表
    """
    try:
        if not os.path.exists(GLOBAL_WIKI_WIKI_DIR):
            return {"status": "none", "results": []}

        structural_results = await run_structural_lint(GLOBAL_WIKI_DIR)

        llm_config = _build_llm_config(body)
        semantic_results = []
        if llm_config:
            try:
                semantic_results = await run_semantic_lint(GLOBAL_WIKI_DIR, llm_config)
            except Exception:
                pass

        all_results = structural_results + semantic_results

        return {
            "status": "completed",
            "results": all_results,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：深度研究
# ---------------------------------------------------------------------------


class ResearchInput(BaseModel):
    """深度研究请求体"""
    topic: str
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    depth: Optional[str] = "standard"
    options: Optional[dict] = None
    # 搜索配置，优先级高于 Wiki 设置中的搜索配置
    searchProvider: Optional[str] = None
    searchApiKey: Optional[str] = None


@router.get("/research")
def get_research_status():
    """获取全局 Wiki 深度研究任务列表

    返回所有研究任务及其状态。
    全局单例模式下，project_id 固定为 0。

    Returns:
        研究任务列表
    """
    try:
        # 全局 Wiki 使用 project_id=0 标识
        tasks = get_research_tasks_by_project_id(0)

        formatted_tasks = []
        for task in tasks:
            formatted_tasks.append({
                "id": task.get("id"),
                "topic": task.get("topic"),
                "status": task.get("status"),
                "progress": task.get("progress"),
                "error": task.get("error"),
                "createdAt": task.get("created_at"),
                "updatedAt": task.get("updated_at"),
            })

        return {"tasks": formatted_tasks}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("/research")
async def run_research(body: ResearchInput):
    """触发全局 Wiki 深度研究

    创建研究任务并在后台执行深度研究管线。

    Args:
        body: 研究参数，包含 topic、LLM 配置和搜索配置
    Returns:
        创建的研究任务信息
    """
    try:
        # 全局 Wiki 使用 project_id=0 标识
        task = create_research_task(0, body.topic)
        task_id = task.get("id")

        llm_config = _build_llm_config(body)

        # 搜索配置：优先使用请求体中的值，回退到 Wiki 设置
        wiki_cfg = _get_wiki_settings()
        search_config = dict(wiki_cfg["search"])
        if body.searchProvider:
            search_config["provider"] = body.searchProvider
        if body.searchApiKey:
            search_config["apiKey"] = body.searchApiKey

        async def _run_research_background():
            """后台执行深度研究任务"""
            try:
                update_research_task(task_id, {"status": "running", "progress": "searching"})
                result = await run_deep_research(
                    GLOBAL_WIKI_DIR,
                    body.topic,
                    llm_config,
                    search_config,
                )
                update_research_task(task_id, {
                    "status": "done" if result.get("status") == "done" else "error",
                    "progress": "completed",
                })
            except Exception as err:
                update_research_task(task_id, {
                    "status": "error",
                    "progress": "failed",
                    "error": str(err),
                })

        asyncio.create_task(_run_research_background())

        return {
            "id": task_id,
            "topic": body.topic,
            "status": "queued",
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：审核
# ---------------------------------------------------------------------------


class ReviewInput(BaseModel):
    """审核请求体"""
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    scope: Optional[str] = "full"
    filePath: Optional[str] = None
    options: Optional[dict] = None


@router.get("/review")
def get_review_status():
    """获取全局 Wiki 未解决的审核项列表

    返回所有未解决的审核项。
    全局单例模式下，project_id 固定为 0。

    Returns:
        审核项列表
    """
    try:
        # 全局 Wiki 使用 project_id=0 标识
        items = get_review_items_by_project_id(0, resolved=False)

        result = []
        for item in items:
            options_json = item.get("options_json")
            options = []
            if options_json:
                try:
                    options = json.loads(options_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            result.append({
                "id": item.get("id"),
                "type": item.get("item_type"),
                "title": item.get("title"),
                "description": item.get("description"),
                "sourcePath": item.get("source_path"),
                "affectedPages": item.get("affected_pages", "").split(",") if item.get("affected_pages") else None,
                "searchQueries": item.get("search_queries", "").split("|") if item.get("search_queries") else None,
                "options": options,
                "resolved": bool(item.get("resolved", 0)),
                "action": item.get("action"),
                "createdAt": item.get("created_at"),
            })

        return result
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("/review")
async def run_review(body: ReviewInput = None):
    """执行全局 Wiki 审核

    对全局 Wiki 执行结构检查，为发现的问题创建审核项，
    并尝试清理已解决的审核项。

    Args:
        body: 审核参数，包含 LLM 配置信息
    Returns:
        新创建的审核项列表
    """
    try:
        if not os.path.exists(GLOBAL_WIKI_WIKI_DIR):
            return []

        llm_config = _build_llm_config(body)

        lint_results = await run_structural_lint(GLOBAL_WIKI_DIR)

        # 全局 Wiki 使用 project_id=0 标识
        global_project_id = 0

        new_items = []
        for lint_item in lint_results:
            if lint_item.get("type") in ("orphan", "broken-link", "no-outlinks"):
                review_type = "missing-page" if lint_item.get("type") == "orphan" else lint_item.get("type")
                created = create_review_item(global_project_id, {
                    "item_type": review_type,
                    "title": f"{lint_item.get('type')}: {lint_item.get('page')}",
                    "description": lint_item.get("detail"),
                    "source_path": lint_item.get("page"),
                    "affected_pages": ",".join(lint_item.get("affectedPages", [])) if lint_item.get("affectedPages") else None,
                    "options": [
                        {"label": "Create Page", "action": "Create Page"},
                        {"label": "Skip", "action": "Skip"},
                    ],
                })
                new_items.append(created)

        existing_items = get_review_items_by_project_id(global_project_id, resolved=False)
        if existing_items and llm_config:
            try:
                await sweep_resolved_reviews(GLOBAL_WIKI_DIR, existing_items, llm_config)
            except Exception:
                pass

        result = []
        for item in new_items:
            options_json = item.get("options_json")
            options = []
            if options_json:
                try:
                    options = json.loads(options_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append({
                "id": item.get("id"),
                "type": item.get("item_type"),
                "title": item.get("title"),
                "description": item.get("description"),
                "sourcePath": item.get("source_path"),
                "affectedPages": item.get("affected_pages", "").split(",") if item.get("affected_pages") else None,
                "searchQueries": item.get("search_queries", "").split("|") if item.get("search_queries") else None,
                "options": options,
                "resolved": bool(item.get("resolved", 0)),
            })

        return result
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


class ReviewFeedbackInput(BaseModel):
    """审核反馈请求体"""
    action: str


@router.post("/review/{reviewId}")
async def submit_review_feedback(reviewId: int, body: ReviewFeedbackInput):
    """提交审核项反馈

    对指定审核项执行操作（如 Create Page、Skip 等）。

    Args:
        reviewId: 审核项 ID
        body: 反馈请求体，包含 action 字段
    Returns:
        操作结果
    """
    try:
        result = resolve_review_item(reviewId, body.action)
        if not result:
            raise HTTPException(status_code=404, detail="审核项不存在")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 路由：概念过时检测
# ---------------------------------------------------------------------------


class StalenessCheckInput(BaseModel):
    """概念过时检测请求体"""
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    options: Optional[dict] = None


@router.post("/staleness-check")
async def staleness_check(body: StalenessCheckInput = None):
    """触发全局 Wiki 概念过时检测

    扫描全局 Wiki wiki/concepts/ 目录下的所有概念页面，
    通过 LLM 判断每个概念是否可能过时，
    并为过时概念生成审核项。

    Args:
        body: 请求体，包含 LLM 配置信息
    Returns:
        检测结果，包含扫描数量、过时数量、审核项数量和过时概念详情
    """
    try:
        llm_config = _build_llm_config(body)

        # 全局 Wiki 使用 project_id=0 标识
        result = await run_staleness_check(GLOBAL_WIKI_DIR, llm_config, project_id=0)

        return {
            "status": "completed",
            **result,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ---------------------------------------------------------------------------
# 后台定时任务：Lint 定时调度
# ---------------------------------------------------------------------------


# 调度间隔映射（秒）
_SCHEDULE_INTERVALS = {
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
}


async def _run_scheduled_lint(schedule: str) -> None:
    """后台定时 Lint 扫描任务

    根据指定调度间隔循环执行 Lint 扫描。每次执行前重新读取设置，
    以响应用户配置变更。当设置变为 off 时自动退出循环。

    Args:
        schedule: 调度频率，"daily" 或 "weekly"
    """
    import logging
    _logger = logging.getLogger("wiki.scheduled_lint")

    while True:
        interval = _SCHEDULE_INTERVALS.get(schedule, 24 * 3600)

        # 等待间隔时间
        await asyncio.sleep(interval)

        # 每次执行前重新读取设置，响应用户配置变更
        try:
            wiki_cfg = _get_wiki_settings()
            current_schedule = wiki_cfg.get("evolution", {}).get("lintSchedule", "off")

            # 设置已改为 off，退出循环
            if current_schedule == "off":
                _logger.info("[定时Lint] lintSchedule 已设为 off，退出定时任务")
                break

            # 调度频率变更，更新间隔
            if current_schedule != schedule:
                schedule = current_schedule
                _logger.info("[定时Lint] 调度频率变更为 %s", schedule)
                continue
        except Exception as err:
            _logger.warning("[定时Lint] 读取设置失败: %s，继续使用当前调度", err)

        # 执行 Lint 扫描
        try:
            _logger.info("[定时Lint] 开始执行定时 Lint 扫描")
            lint_results = await run_structural_lint(GLOBAL_WIKI_DIR)
            _logger.info("[定时Lint] 扫描完成，发现 %d 个问题", len(lint_results))
        except Exception as err:
            _logger.error("[定时Lint] 扫描失败: %s", err)
