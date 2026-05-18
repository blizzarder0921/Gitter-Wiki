"""
Wiki 网络搜索模块

从 TypeScript 参考项目 llm_wiki-0.4.9/src/lib/web-search.ts 移植，
适配 Python FastAPI 环境。

功能：
- 多提供商网络搜索：Tavily / SerpApi / SearXNG
- 结果归一化为统一格式
- 使用 httpx 异步 HTTP 客户端

支持的搜索提供商：
- Tavily: POST https://api.tavily.com/search, search_depth=advanced
- SerpApi: GET https://serpapi.com/search
- SearXNG: GET {instance}/search, format=json
"""

import re
from typing import Optional
from urllib.parse import urlparse, urlencode

import httpx


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class WebSearchResult:
    """网络搜索结果

    Attributes:
        title: 页面标题
        url: 页面 URL
        snippet: 内容摘要
        source: 来源标识（通常是域名）
    """

    def __init__(self, title: str, url: str, snippet: str, source: str):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source

    def to_dict(self) -> dict:
        """转换为字典格式

        Returns:
            包含所有字段的字典
        """
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _hostname_from_url(url: str) -> str:
    """从 URL 中提取主机名，去除 www. 前缀

    Args:
        url: 完整 URL 字符串
    Returns:
        主机名字符串，解析失败返回空字符串
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return re.sub(r"^www\.", "", hostname)
    except Exception:
        return ""


def _resolve_search_config(config: dict) -> dict:
    """解析搜索配置，合并提供商特定配置

    将 providerConfigs 中的提供商特定配置合并到顶层配置中，
    确保活跃提供商的 API Key 和参数正确设置。

    Args:
        config: 搜索配置字典，包含 provider、apiKey、providerConfigs 等
    Returns:
        解析后的搜索配置字典
    """
    provider_configs = config.get("providerConfigs") or {}

    # 如果顶层配置有提供商和 API Key，但没有对应的 providerConfig，自动创建
    provider = config.get("provider", "none")
    if provider != "none" and config.get("apiKey") and provider not in provider_configs:
        provider_configs[provider] = {
            "apiKey": config["apiKey"],
            "serpApiEngine": config.get("serpApiEngine"),
            "searXngUrl": config.get("searXngUrl"),
            "searXngCategories": config.get("searXngCategories"),
        }

    # SearXNG 特殊处理：如果有 searXngUrl，确保 providerConfigs 中有 searxng 配置
    if provider == "searxng" and config.get("searXngUrl"):
        if "searxng" not in provider_configs:
            provider_configs["searxng"] = {
                "searXngUrl": config["searXngUrl"],
                "searXngCategories": config.get("searXngCategories"),
            }

    if provider == "none":
        return {
            **config,
            "provider": "none",
            "apiKey": "",
            "serpApiEngine": config.get("serpApiEngine")
                or (provider_configs.get("serpapi") or {}).get("serpApiEngine")
                or "google",
            "searXngUrl": config.get("searXngUrl")
                or (provider_configs.get("searxng") or {}).get("searXngUrl")
                or "",
            "searXngCategories": config.get("searXngCategories")
                or (provider_configs.get("searxng") or {}).get("searXngCategories")
                or ["general"],
            "providerConfigs": provider_configs,
        }

    # 使用活跃提供商的覆盖配置
    active_override = provider_configs.get(provider, {})
    return {
        **config,
        "provider": provider,
        "apiKey": active_override.get("apiKey") or config.get("apiKey") or "",
        "serpApiEngine": active_override.get("serpApiEngine")
            or config.get("serpApiEngine")
            or "google",
        "searXngUrl": active_override.get("searXngUrl")
            or config.get("searXngUrl")
            or "",
        "searXngCategories": active_override.get("searXngCategories")
            or config.get("searXngCategories")
            or ["general"],
        "providerConfigs": provider_configs,
    }


# ---------------------------------------------------------------------------
# Tavily 搜索
# ---------------------------------------------------------------------------

async def _tavily_search(
    query: str,
    api_key: str,
    max_results: int,
) -> list[WebSearchResult]:
    """使用 Tavily API 执行搜索

    POST https://api.tavily.com/search
    使用 advanced 搜索深度以获取更详细的结果。

    Args:
        query: 搜索查询
        api_key: Tavily API Key
        max_results: 最大返回结果数
    Returns:
        搜索结果列表
    Raises:
        Exception: 网络错误或 API 错误
    """
    request_body = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": False,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json=request_body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.ConnectError:
            raise Exception(
                "Network error reaching api.tavily.com. "
                "Check your connectivity and whether the Tavily API key is still valid."
            )
        except httpx.TimeoutException:
            raise Exception("Tavily search request timed out.")

    if response.status_code != 200:
        error_text = response.text or "Unknown error"
        raise Exception(f"Tavily search failed ({response.status_code}): {error_text}")

    data = response.json()
    results = data.get("results") or []

    return [
        WebSearchResult(
            title=r.get("title") or "Untitled",
            url=r.get("url") or "",
            snippet=r.get("content") or "",
            source=_hostname_from_url(r.get("url") or ""),
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# SerpApi 搜索
# ---------------------------------------------------------------------------

async def _serp_api_search(
    query: str,
    api_key: str,
    max_results: int,
    engine: str = "google",
) -> list[WebSearchResult]:
    """使用 SerpApi 执行搜索

    GET https://serpapi.com/search
    支持多种搜索引擎（google、google_news、google_scholar 等）。

    Args:
        query: 搜索查询
        api_key: SerpApi API Key
        max_results: 最大返回结果数
        engine: 搜索引擎类型，默认 "google"
    Returns:
        搜索结果列表
    Raises:
        Exception: 网络错误或 API 错误
    """
    params = urlencode({
        "engine": engine,
        "q": query,
        "api_key": api_key,
        "num": str(max_results),
    })

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"https://serpapi.com/search?{params}",
                headers={"Accept": "application/json"},
            )
        except httpx.ConnectError:
            raise Exception(
                "Network error reaching serpapi.com. "
                "Check your connectivity and whether the SerpApi API key is still valid."
            )
        except httpx.TimeoutException:
            raise Exception("SerpApi search request timed out.")

    if response.status_code != 200:
        error_text = response.text or "Unknown error"
        raise Exception(f"SerpApi search failed ({response.status_code}): {error_text}")

    data = response.json()

    # 检查 SerpApi 返回的错误
    if isinstance(data.get("error"), str) and data["error"].strip():
        raise Exception(f"SerpApi search failed: {data['error']}")

    return _normalize_serp_api_results(data, max_results)


def _normalize_serp_api_results(data: dict, max_results: int) -> list[WebSearchResult]:
    """归一化 SerpApi 搜索结果

    SerpApi 根据搜索引擎类型返回不同的结果字段：
    - organic_results: 通用搜索结果
    - news_results: 新闻搜索结果
    - images_results: 图片搜索结果
    - video_results / videos_results: 视频搜索结果
    - shopping_results: 购物搜索结果

    Args:
        data: SerpApi 原始响应数据
        max_results: 最大返回结果数
    Returns:
        归一化后的搜索结果列表
    """
    raw_results = (
        data.get("organic_results")
        or data.get("news_results")
        or data.get("images_results")
        or data.get("video_results")
        or data.get("videos_results")
        or data.get("shopping_results")
        or []
    )

    results = []
    for item in raw_results[:max_results]:
        url = (
            item.get("link")
            or item.get("url")
            or item.get("original")
            or item.get("thumbnail")
            or ""
        )
        results.append(WebSearchResult(
            title=item.get("title") or "Untitled",
            url=url,
            snippet=(
                item.get("snippet")
                or item.get("summary")
                or item.get("description")
                or ""
            ),
            source=(
                _hostname_from_url(url)
                or item.get("source")
                or item.get("displayed_link")
                or ""
            ),
        ))

    return results


# ---------------------------------------------------------------------------
# SearXNG 搜索
# ---------------------------------------------------------------------------

def _sear_xng_search_url(instance_url: str) -> str:
    """构建 SearXNG 搜索端点 URL

    处理逻辑：
    - 自动补全 https:// 协议前缀
    - 确保路径以 /search 结尾

    Args:
        instance_url: SearXNG 实例 URL
    Returns:
        搜索端点 URL 字符串
    Raises:
        Exception: URL 格式无效
    """
    trimmed = instance_url.strip()
    if not re.match(r"^https?://", trimmed, re.IGNORECASE):
        trimmed = f"https://{trimmed}"

    try:
        parsed = urlparse(trimmed)
    except Exception:
        raise Exception(
            "Invalid SearXNG instance URL. Use a valid http(s) URL, "
            "for example https://search.example.com."
        )

    path = parsed.path.rstrip("/")
    if not path.endswith("/search") and path != "/search":
        path = f"{path}/search"

    # 重建 URL（去除 query 和 fragment）
    return f"{parsed.scheme}://{parsed.netloc}{path}"


async def _sear_xng_search(
    query: str,
    instance_url: str,
    max_results: int,
    categories: Optional[list[str]] = None,
) -> list[WebSearchResult]:
    """使用 SearXNG 实例执行搜索

    GET {instance}/search?format=json
    需要实例启用 JSON 搜索格式。

    Args:
        query: 搜索查询
        instance_url: SearXNG 实例 URL
        max_results: 最大返回结果数
        categories: 搜索分类列表，默认 ["general"]
    Returns:
        搜索结果列表
    Raises:
        Exception: URL 无效、网络错误或 API 错误
    """
    try:
        endpoint = _sear_xng_search_url(instance_url)
    except Exception as e:
        raise Exception(str(e))

    # 构建查询参数
    cats = categories or ["general"]
    params = urlencode({
        "q": query,
        "format": "json",
        "categories": ",".join(cats),
    })

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{endpoint}?{params}",
                headers={"Accept": "application/json"},
            )
        except httpx.ConnectError:
            raise Exception(
                "Network error reaching the SearXNG instance. "
                "Check the instance URL and whether JSON search is enabled."
            )
        except httpx.TimeoutException:
            raise Exception("SearXNG search request timed out.")

    if response.status_code != 200:
        error_text = response.text or "Unknown error"
        raise Exception(f"SearXNG search failed ({response.status_code}): {error_text}")

    data = response.json()
    return _normalize_sear_xng_results(data, max_results)


def _normalize_sear_xng_results(data: dict, max_results: int) -> list[WebSearchResult]:
    """归一化 SearXNG 搜索结果

    Args:
        data: SearXNG 原始响应数据
        max_results: 最大返回结果数
    Returns:
        归一化后的搜索结果列表
    """
    raw_results = data.get("results") or []

    results = []
    for item in raw_results[:max_results]:
        url = item.get("url") or ""
        if not url:
            continue
        results.append(WebSearchResult(
            title=item.get("title") or "Untitled",
            url=url,
            snippet=item.get("content") or "",
            source=(
                _hostname_from_url(url)
                or item.get("engine")
                or item.get("category")
                or ""
            ),
        ))

    return results


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def web_search(
    query: str,
    config: dict,
    max_results: int = 8,
) -> list[dict]:
    """多提供商网络搜索

    根据配置选择搜索提供商（Tavily / SerpApi / SearXNG），
    执行搜索并返回归一化的结果列表。

    Args:
        query: 搜索查询字符串
        config: 搜索配置字典，包含：
            - provider: 提供商名称（tavily / serpapi / searxng / none）
            - apiKey: API Key（Tavily / SerpApi 需要）
            - searXngUrl: SearXNG 实例 URL
            - searXngCategories: SearXNG 搜索分类
            - serpApiEngine: SerpApi 搜索引擎类型
            - providerConfigs: 各提供商的特定配置
        max_results: 最大返回结果数，默认 8
    Returns:
        搜索结果列表，每项为 {"title", "url", "snippet", "source"}
    Raises:
        Exception: 搜索未配置或搜索失败
    """
    resolved = _resolve_search_config(config)

    provider = resolved.get("provider", "none")

    if provider == "none":
        raise Exception(
            "Web search not configured. Select a search provider in Settings."
        )

    if provider in ("tavily", "serpapi") and not resolved.get("apiKey"):
        raise Exception(
            "Web search not configured. Add a Tavily or SerpApi API key in Settings."
        )

    if provider == "searxng" and not (resolved.get("searXngUrl") or "").strip():
        raise Exception(
            "Web search not configured. Add a SearXNG instance URL in Settings."
        )

    if provider == "tavily":
        results = await _tavily_search(
            query, resolved["apiKey"], max_results
        )
    elif provider == "serpapi":
        results = await _serp_api_search(
            query,
            resolved["apiKey"],
            max_results,
            resolved.get("serpApiEngine") or "google",
        )
    elif provider == "searxng":
        results = await _sear_xng_search(
            query,
            resolved.get("searXngUrl") or "",
            max_results,
            resolved.get("searXngCategories") or ["general"],
        )
    else:
        raise Exception(f"Unknown search provider: {provider}")

    return [r.to_dict() for r in results]
