"""
LLM 流式调用客户端模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/llm-client.ts + llm-providers.ts + reasoning-detector.ts 移植。
提供统一的 LLM 流式调用客户端，支持多种提供商。

支持的提供商格式：
- OpenAI 兼容格式：OpenAI / DeepSeek / Qwen / Kimi / GLM / SiliconFlow / Doubao / OpenRouter / Grok / Tencent / Xiaomi
- Anthropic 格式
- Google Gemini 格式

核心功能：
- SSE 流式解析
- 推理 token 检测（reasoning_content / reasoning / thought）
- 30 分钟超时兜底
- 空内容诊断：模型只产生推理 token 但无实际回答时报错
"""

import asyncio
import json
import logging
import re
from typing import Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)

# 30 分钟超时兜底（毫秒），为大上下文推理模型预留充足时间
_TIMEOUT_MS = 30 * 60 * 1000

# 推理 token 诊断阈值：超过此长度的推理但无实际内容时报错
_REASONING_DIAGNOSTIC_THRESHOLD = 200

# 推理字段正则：匹配 "reasoning_content" 或 "reasoning"
_REASONING_FIELD_RE = re.compile(
    r'"reasoning(?:_content)?"\s*:\s*"((?:[^"\\]|\\.)*)"'
)

# OpenAI 兼容提供商列表（都使用 /chat/completions 格式）
_OPENAI_COMPATIBLE_PROVIDERS = {
    "openai", "deepseek", "qwen", "kimi", "glm", "siliconflow",
    "doubao", "openrouter", "grok", "tencent", "xiaomi",
}

_PROVIDER_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "openrouter": "https://openrouter.ai/api/v1",
    "grok": "https://api.x.ai/v1",
    "tencent": "https://hunyuan.tencentcloudapi.com/v1",
    "xiaomi": "https://api.maiml.com/v1",
    "ollama": "http://localhost:11434/v1",
}


# ---------------------------------------------------------------------------
# 推理 token 检测（从 reasoning-detector.ts 移植）
# ---------------------------------------------------------------------------

def _count_reasoning_chars_in_line(raw_line: str) -> int:
    """统计 SSE 行中推理字段的字符长度

    用于区分"模型什么都没说"和"模型只产生了推理但没产出实际回答"。

    Args:
        raw_line: 原始 SSE 数据行
    Returns:
        推理文本的字符总长度
    """
    total = 0
    for match in _REASONING_FIELD_RE.finditer(raw_line):
        total += len(match.group(1))
    return total


def _extract_reasoning_text_from_line(raw_line: str) -> list[str]:
    """从 SSE 行中提取推理文本片段

    支持三种推理字段格式：
    - DeepSeek/Kimi: delta.reasoning_content
    - Qwen: delta.reasoning
    - Gemini: parts[].thought=true

    Args:
        raw_line: 原始 SSE 数据行
    Returns:
        推理文本片段列表
    """
    line = raw_line.strip()
    if not line.startswith("data: "):
        return []

    data = line[6:].strip()
    if not data or data == "[DONE]":
        return []

    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return []

    out: list[str] = []

    # OpenAI 兼容格式：choices[].delta.reasoning_content / reasoning
    choices = parsed.get("choices", [])
    for choice in choices:
        delta = choice.get("delta", {})
        if isinstance(delta.get("reasoning_content"), str):
            out.append(delta["reasoning_content"])
        if isinstance(delta.get("reasoning"), str):
            out.append(delta["reasoning"])

    # Anthropic 格式：delta.type == "thinking_delta"
    delta = parsed.get("delta", {})
    if delta.get("type") == "thinking_delta":
        if isinstance(delta.get("thinking"), str):
            out.append(delta["thinking"])
        if isinstance(delta.get("text"), str):
            out.append(delta["text"])

    # Gemini 格式：candidates[].content.parts[].thought=true
    candidates = parsed.get("candidates", [])
    for candidate in candidates:
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            if part.get("thought") and isinstance(part.get("text"), str):
                out.append(part["text"])

    return out


# ---------------------------------------------------------------------------
# 提供商配置构建
# ---------------------------------------------------------------------------

def _build_provider_config(config: dict) -> dict:
    """根据提供商类型构建请求配置（URL、Headers、Body 构建函数）

    Args:
        config: LLM 配置字典，包含 provider, apiKey, baseUrl, model 等
    Returns:
        包含 url, headers, build_body, parse_stream 的配置字典
    """
    provider = config.get("provider", "openai")
    api_key = config.get("apiKey", "")
    base_url = config.get("baseUrl", "")
    model = config.get("model", "")

    if provider in _OPENAI_COMPATIBLE_PROVIDERS or provider == "custom":
        return _build_openai_compatible_config(config)
    elif provider == "anthropic":
        return _build_anthropic_config(config)
    elif provider == "google":
        return _build_google_config(config)
    else:
        # 默认按 OpenAI 兼容处理
        return _build_openai_compatible_config(config)


def _build_openai_compatible_config(config: dict) -> dict:
    """构建 OpenAI 兼容格式的请求配置

    适用于 OpenAI / DeepSeek / Qwen / Kimi / GLM / SiliconFlow / Doubao / OpenRouter / Grok / Tencent / Xiaomi

    Args:
        config: LLM 配置
    Returns:
        请求配置字典
    """
    provider = config.get("provider", "openai")
    api_key = config.get("apiKey", "")
    base_url = config.get("baseUrl", "")
    model = config.get("model", "")

    # 确定 URL：优先使用用户配置的 baseUrl，其次使用提供商默认地址
    resolved_base_url = base_url or _PROVIDER_DEFAULT_BASE_URLS.get(provider, "")
    if resolved_base_url:
        url = resolved_base_url.rstrip("/")
        # 防止重复拼接 /chat/completions
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
    else:
        url = "https://api.openai.com/v1/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def build_body(messages: list[dict], overrides: dict | None = None) -> dict:
        """构建 OpenAI 兼容请求体

        Args:
            messages: 消息列表 [{role, content}]
            overrides: 采样参数覆盖
        Returns:
            请求体字典
        """
        overrides = overrides or {}
        body: dict = {
            "messages": messages,
            "model": model,
            "stream": True,
        }

        # 采样参数
        if "temperature" in overrides:
            body["temperature"] = overrides["temperature"]
        elif "temperature" in config:
            body["temperature"] = config["temperature"]

        if "maxTokens" in overrides:
            body["max_tokens"] = overrides["maxTokens"]
        elif "maxTokens" in config:
            body["max_tokens"] = config["maxTokens"]

        if "top_p" in overrides:
            body["top_p"] = overrides["top_p"]

        # DeepSeek 推理模式
        if provider == "deepseek":
            reasoning = config.get("reasoning", {})
            mode = reasoning.get("mode", "auto") if reasoning else "auto"
            if mode == "off":
                body["thinking"] = {"type": "disabled"}
            elif mode not in ("auto",):
                body["thinking"] = {"type": "enabled"}
                if mode in ("high", "max"):
                    body["reasoning_effort"] = mode

        # Qwen 思考模型关闭
        if provider == "qwen" and re.search(r"qwen[-_]?3", model, re.IGNORECASE):
            reasoning = config.get("reasoning", {})
            mode = reasoning.get("mode", "auto") if reasoning else "auto"
            if mode == "off":
                body["chat_template_kwargs"] = {"enable_thinking": False}

        return body

    return {
        "url": url,
        "headers": headers,
        "build_body": build_body,
        "parse_stream": _parse_openai_line,
    }


def _build_anthropic_config(config: dict) -> dict:
    """构建 Anthropic 格式的请求配置

    Args:
        config: LLM 配置
    Returns:
        请求配置字典
    """
    api_key = config.get("apiKey", "")
    base_url = config.get("baseUrl", "")
    model = config.get("model", "")

    # 构建 URL
    url = _build_anthropic_url(base_url or "https://api.anthropic.com")

    # 构建 Headers
    headers = {"Content-Type": "application/json"}
    # 检查是否需要 Bearer 认证（MiniMax 等第三方端点）
    if _requires_bearer_auth(url):
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"

    def build_body(messages: list[dict], overrides: dict | None = None) -> dict:
        """构建 Anthropic 请求体

        system 消息提取到顶层 system 字段，非 system 消息保留在 messages 中。

        Args:
            messages: 消息列表
            overrides: 采样参数覆盖
        Returns:
            请求体字典
        """
        overrides = overrides or {}
        system_messages = [m for m in messages if m.get("role") == "system"]
        conversation_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m.get("role") != "system"
        ]

        system_text = "\n".join(m["content"] for m in system_messages) or None

        body: dict = {
            "messages": conversation_messages,
            "model": model,
            "stream": True,
            "max_tokens": overrides.get("maxTokens", config.get("maxTokens", 4096)),
        }
        if system_text:
            body["system"] = system_text

        # 采样参数
        if "temperature" in overrides:
            body["temperature"] = overrides["temperature"]
        elif "temperature" in config:
            body["temperature"] = config["temperature"]

        if "top_p" in overrides:
            body["top_p"] = overrides["top_p"]

        if "top_k" in overrides:
            body["top_k"] = overrides["top_k"]

        if "stop" in overrides:
            stop = overrides["stop"]
            body["stop_sequences"] = stop if isinstance(stop, list) else [stop]

        # 推理模式
        reasoning = config.get("reasoning", {})
        mode = reasoning.get("mode", "auto") if reasoning else "auto"
        if mode not in ("auto", "off"):
            budget_tokens = max(1024, reasoning.get("budgetTokens", 8192))
            if body.get("max_tokens", 0) <= budget_tokens:
                body["max_tokens"] = budget_tokens + 1
            body["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
            body.pop("temperature", None)
            body.pop("top_p", None)
            body.pop("top_k", None)

        return body

    return {
        "url": url,
        "headers": headers,
        "build_body": build_body,
        "parse_stream": _parse_anthropic_line,
    }


def _build_google_config(config: dict) -> dict:
    """构建 Google Gemini 格式的请求配置

    Args:
        config: LLM 配置
    Returns:
        请求配置字典
    """
    api_key = config.get("apiKey", "")
    base_url = config.get("baseUrl", "")
    model = config.get("model", "")

    # 编码模型名（处理 OpenRouter 风格的带斜杠模型 ID）
    from urllib.parse import quote
    encoded_model = quote(model, safe="")

    if base_url:
        url_base = base_url.rstrip("/")
    else:
        url_base = "https://generativelanguage.googleapis.com/v1beta"

    url = f"{url_base}/models/{encoded_model}:streamGenerateContent?alt=sse"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-goog-api-key"] = api_key

    def build_body(messages: list[dict], overrides: dict | None = None) -> dict:
        """构建 Gemini 请求体

        system 消息提取到 systemInstruction，assistant 角色映射为 model。
        采样参数放在 generationConfig 下（Gemini 不接受顶层采样参数）。

        Args:
            messages: 消息列表
            overrides: 采样参数覆盖
        Returns:
            请求体字典
        """
        overrides = overrides or {}
        system_messages = [m for m in messages if m.get("role") == "system"]
        conversation_messages = [m for m in messages if m.get("role") != "system"]

        # 构建内容
        contents = []
        for m in conversation_messages:
            role = "model" if m.get("role") == "assistant" else "user"
            parts = [{"text": m["content"]}]
            contents.append({"role": role, "parts": parts})

        # 系统指令
        system_instruction = None
        if system_messages:
            parts = [{"text": m["content"]} for m in system_messages]
            system_instruction = {"parts": parts}

        # 生成配置（Gemini 要求采样参数在 generationConfig 下）
        generation_config: dict = {}
        if "temperature" in overrides:
            generation_config["temperature"] = overrides["temperature"]
        elif "temperature" in config:
            generation_config["temperature"] = config["temperature"]

        if "top_p" in overrides:
            generation_config["topP"] = overrides["top_p"]

        if "top_k" in overrides:
            generation_config["topK"] = overrides["top_k"]

        if "maxTokens" in overrides:
            generation_config["maxOutputTokens"] = overrides["maxTokens"]
        elif "maxTokens" in config:
            generation_config["maxOutputTokens"] = config["maxTokens"]

        if "stop" in overrides:
            stop = overrides["stop"]
            generation_config["stopSequences"] = stop if isinstance(stop, list) else [stop]

        # 推理配置
        reasoning = config.get("reasoning", {})
        mode = reasoning.get("mode", "auto") if reasoning else "auto"
        if mode == "off":
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        elif mode not in ("auto",):
            budget = reasoning.get("budgetTokens", 8192)
            generation_config["thinkingConfig"] = {"thinkingBudget": budget}

        body: dict = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if generation_config:
            body["generationConfig"] = generation_config

        return body

    return {
        "url": url,
        "headers": headers,
        "build_body": build_body,
        "parse_stream": _parse_google_line,
    }


# ---------------------------------------------------------------------------
# SSE 流解析函数
# ---------------------------------------------------------------------------

def _parse_openai_line(line: str) -> str | None:
    """解析 OpenAI 兼容格式的 SSE 行

    格式：data: {"choices": [{"delta": {"content": "..."}}]}

    Args:
        line: SSE 数据行
    Returns:
        提取的文本 token，或 None
    """
    if not line.startswith("data: "):
        return None

    data = line[6:].strip()
    if data == "[DONE]":
        return None

    try:
        parsed = json.loads(data)
        choices = parsed.get("choices", [])
        if choices:
            return choices[0].get("delta", {}).get("content")
    except (json.JSONDecodeError, ValueError, IndexError, KeyError):
        pass

    return None


def _parse_anthropic_line(line: str) -> str | None:
    """解析 Anthropic 格式的 SSE 行

    格式：data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}

    Args:
        line: SSE 数据行
    Returns:
        提取的文本 token，或 None
    """
    if not line.startswith("data: "):
        return None

    data = line[6:].strip()

    try:
        parsed = json.loads(data)
        if (
            parsed.get("type") == "content_block_delta"
            and parsed.get("delta", {}).get("type") == "text_delta"
        ):
            return parsed["delta"].get("text")
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    return None


def _parse_google_line(line: str) -> str | None:
    """解析 Google Gemini 格式的 SSE 行

    格式：data: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}

    跳过 thought=true 的推理部分，仅提取实际回答文本。

    Args:
        line: SSE 数据行
    Returns:
        提取的文本 token，或 None
    """
    if not line.startswith("data: "):
        return None

    data = line[6:].strip()

    try:
        parsed = json.loads(data)
        candidates = parsed.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None

        # 拼接所有非 thought 的文本部分
        out = ""
        for p in parts:
            if p.get("thought"):
                continue
            if isinstance(p.get("text"), str):
                out += p["text"]

        return out if out else None
    except (json.JSONDecodeError, ValueError, KeyError, IndexError):
        pass

    return None


# ---------------------------------------------------------------------------
# Anthropic URL 构建
# ---------------------------------------------------------------------------

def _build_anthropic_url(base: str) -> str:
    """构建 Anthropic 端点的最终 POST URL

    处理各种用户输入格式：
    - .../v1/messages → 保持不变
    - .../v1 → 追加 /messages
    - .../api/paas/v4 → 追加 /messages
    - .../anthropic → 追加 /v1/messages

    Args:
        base: 用户输入的基础 URL
    Returns:
        完整的 API URL
    """
    trimmed = base.rstrip("/")

    # 已包含完整路径
    if re.search(r"/v\d+/messages$", trimmed, re.IGNORECASE):
        return trimmed

    # 以版本号结尾
    if re.search(r"/v\d+$", trimmed, re.IGNORECASE):
        return f"{trimmed}/messages"

    return f"{trimmed}/v1/messages"


def _requires_bearer_auth(url: str) -> bool:
    """判断 Anthropic 端点是否需要 Bearer 认证

    MiniMax 等第三方端点使用 Authorization: Bearer 而非 x-api-key。

    Args:
        url: API URL
    Returns:
        是否需要 Bearer 认证
    """
    normalized = url.lower().rstrip("/")
    return (
        normalized.startswith("https://api.minimax.io/anthropic")
        or normalized.startswith("https://api.minimaxi.com/anthropic")
        or normalized.startswith("https://coding.dashscope.aliyuncs.com/apps/anthropic")
    )


# ---------------------------------------------------------------------------
# 核心 API：stream_chat
# ---------------------------------------------------------------------------

async def stream_chat(
    config: dict,
    messages: list[dict],
    on_token: Callable[[str], Awaitable[None] | None],
    on_reasoning_token: Callable[[str], Awaitable[None] | None] | None = None,
    signal: asyncio.Event | None = None,
) -> str:
    """统一的 LLM 流式调用入口

    使用 httpx 进行流式 HTTP 请求，支持 OpenAI/Anthropic/Google 三种格式。
    SSE 流逐行解析，通过回调函数实时传递 token。

    Args:
        config: LLM 配置字典
            - provider: 提供商名称
            - apiKey: API 密钥
            - baseUrl: 基础 URL
            - model: 模型名称
            - temperature: 温度参数（可选）
            - maxTokens: 最大 token 数（可选）
            - reasoning: 推理配置（可选）
        messages: 消息列表 [{role: str, content: str}]
        on_token: token 回调函数，每收到一个文本 token 调用
        on_reasoning_token: 推理 token 回调函数（可选）
        signal: 取消信号，设置后中止请求（可选）
    Returns:
        完整的文本内容
    Raises:
        RuntimeError: 请求超时、网络错误、空内容诊断等
    """
    provider_config = _build_provider_config(config)

    # 构建请求体和 URL
    url = provider_config["url"]
    headers = provider_config["headers"]
    body = provider_config["build_body"](messages)
    parse_stream = provider_config["parse_stream"]

    # 超时控制
    timeout = httpx.Timeout(_TIMEOUT_MS / 1000, connect=30.0)

    # 诊断计数器
    content_chars_emitted = 0
    reasoning_chars_observed = 0

    full_text = ""

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
            ) as response:
                # 检查 HTTP 状态码
                if response.status_code != 200:
                    error_detail = f"HTTP {response.status_code}"
                    try:
                        error_body = await response.aread()
                        if error_body:
                            error_detail += f" — {error_body.decode('utf-8', errors='replace')[:500]}"
                    except Exception:
                        pass
                    raise RuntimeError(error_detail)

                # SSE 流式读取
                line_buffer = ""

                async for chunk_bytes in response.aiter_bytes():
                    # 检查取消信号
                    if signal and signal.is_set():
                        return full_text

                    # 解码并按行分割
                    chunk_text = chunk_bytes.decode("utf-8", errors="replace")
                    line_buffer += chunk_text
                    lines = line_buffer.split("\n")
                    line_buffer = lines.pop()  # 最后一行可能不完整，保留

                    for line in lines:
                        trimmed = line.strip()
                        if not trimmed:
                            continue

                        # 统计推理 token
                        reasoning_chars_observed += _count_reasoning_chars_in_line(trimmed)

                        # 提取推理文本并回调
                        if on_reasoning_token:
                            reasoning_parts = _extract_reasoning_text_from_line(trimmed)
                            for part in reasoning_parts:
                                result = on_reasoning_token(part)
                                if asyncio.iscoroutine(result):
                                    await result

                        # 解析实际内容 token
                        token = parse_stream(trimmed)
                        if token is not None:
                            content_chars_emitted += len(token)
                            full_text += token
                            result = on_token(token)
                            if asyncio.iscoroutine(result):
                                await result

                # 处理缓冲区中剩余的内容
                if line_buffer.strip():
                    trimmed = line_buffer.strip()
                    reasoning_chars_observed += _count_reasoning_chars_in_line(trimmed)

                    if on_reasoning_token:
                        reasoning_parts = _extract_reasoning_text_from_line(trimmed)
                        for part in reasoning_parts:
                            result = on_reasoning_token(part)
                            if asyncio.iscoroutine(result):
                                await result

                    token = parse_stream(trimmed)
                    if token is not None:
                        content_chars_emitted += len(token)
                        full_text += token
                        result = on_token(token)
                        if asyncio.iscoroutine(result):
                            await result

    except httpx.TimeoutException:
        raise RuntimeError(
            f"请求超时（{_TIMEOUT_MS / 60000:.0f} 分钟）。"
            "请尝试更快的模型或更小的上下文。"
        )
    except httpx.ConnectError:
        raise RuntimeError(
            f"无法连接到 {url}。请检查端点 URL、API 密钥和网络连接。"
        )
    except httpx.NetworkError:
        raise RuntimeError("流式传输期间连接丢失，请重试。")
    except RuntimeError:
        raise
    except Exception as err:
        raise RuntimeError(f"LLM 调用失败: {err}") from err

    # 空内容诊断：模型只产生了推理 token 但无实际回答
    if content_chars_emitted == 0 and reasoning_chars_observed >= _REASONING_DIAGNOSTIC_THRESHOLD:
        raise RuntimeError(
            f"模型产生了 {reasoning_chars_observed:,} 个字符的推理/思维链，"
            "但没有产生任何实际回答内容。"
            "这通常意味着端点达到了思维 token 限制、模型未从思考过渡到回答、"
            "或端点行为异常。"
            "请尝试更短的输入、增加 max_tokens、或切换到不同的模型。"
        )

    return full_text


# ---------------------------------------------------------------------------
# 便捷函数：非流式调用
# ---------------------------------------------------------------------------

async def simple_chat(
    config: dict,
    messages: list[dict],
    signal: asyncio.Event | None = None,
) -> str:
    """简化的非流式 LLM 调用

    不使用回调，直接返回完整文本。

    Args:
        config: LLM 配置字典
        messages: 消息列表
        signal: 取消信号（可选）
    Returns:
        完整的文本内容
    """
    return await stream_chat(
        config=config,
        messages=messages,
        on_token=lambda _: None,  # 空回调
        signal=signal,
    )
