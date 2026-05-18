"""
多源答案合并模块

将 graphify（代码结构分析）和 wiki（项目文档）两个数据源的结果合并，
生成统一的最终回答。所有场景均通过 LLM 生成针对性回答，保持一致性。

依赖 llm_client.py 的 simple_chat 接口进行 LLM 调用。
"""

from backend.services.wiki.llm_client import simple_chat


# ---------------------------------------------------------------------------
# 合并 Prompt 模板
# ---------------------------------------------------------------------------

# 双源合并 Prompt：同时拥有代码结构分析和项目文档
_MERGE_BOTH_PROMPT = """你是一个项目知识助手。请根据以下两个来源的信息，综合回答用户的问题。

【来源1：代码结构分析（Graphify）】
{graphify_result}

【来源2：项目文档（Wiki）】
{wiki_result}

请综合以上两个来源，生成一个完整、准确的回答。要求：
1. 优先使用代码结构分析中的具体函数调用链和依赖关系
2. 用项目文档补充概念解释和使用说明
3. 如果两个来源有冲突，以代码结构分析为准
4. 回答要结构清晰，使用 Markdown 格式
"""

# 仅 graphify 结果时的 Prompt
_GRAPHIFY_ONLY_PROMPT = """你是一个项目代码分析助手。请根据以下代码结构分析结果，回答用户的问题。

【代码结构分析（Graphify）】
{graphify_result}

请基于以上代码结构信息生成回答。要求：
1. 重点说明函数调用链和模块依赖关系
2. 如有影响范围分析，请清晰列出
3. 回答要结构清晰，使用 Markdown 格式
"""

# 仅 wiki 结果时的 Prompt
_WIKI_ONLY_PROMPT = """你是一个项目知识助手。请根据以下项目文档内容，回答用户的问题。

【项目文档（Wiki）】
{wiki_result}

请基于以上文档内容生成回答。要求：
1. 准确回答用户问题，不要编造文档中没有的信息
2. 如果文档内容不足以回答问题，明确说明并给出文档中已有的相关信息
3. 使用 [[wikilink]] 语法引用相关 Wiki 页面
4. 回答要结构清晰，使用 Markdown 格式
"""


async def generate_answer(
    question: str,
    graphify_result: str = None,
    wiki_result: str = None,
    llm_config: dict = None,
) -> str:
    """合并多源答案生成最终响应

    根据可用的数据源数量采取不同策略，所有场景均通过 LLM 生成针对性回答：
    - 两个来源都有：构建合并 Prompt，让 LLM 综合两个来源生成统一答案
    - 仅 graphify_result：通过 LLM 基于代码结构生成回答
    - 仅 wiki_result：通过 LLM 基于文档内容生成回答
    - 都没有：返回默认提示

    Args:
        question: 用户原始问题
        graphify_result: graphify 代码结构分析结果（可选）
        wiki_result: wiki 项目文档检索结果（可选）
        llm_config: LLM 配置字典，包含 provider/apiKey/baseUrl/model 等
    Returns:
        合并后的最终回答文本
    """
    has_graphify = bool(graphify_result and graphify_result.strip())
    has_wiki = bool(wiki_result and wiki_result.strip())

    # 两个来源都没有
    if not has_graphify and not has_wiki:
        return "未找到相关信息。"

    # 仅 wiki 结果：通过 LLM 基于文档内容生成回答
    if has_wiki and not has_graphify:
        return await _generate_from_wiki(question, wiki_result, llm_config)

    # 仅 graphify 结果：通过 LLM 基于代码结构生成回答
    if has_graphify and not has_wiki:
        return await _generate_from_graphify(question, graphify_result, llm_config)

    # 两个来源都有：通过 LLM 合并生成
    return await _merge_both_sources(question, graphify_result, wiki_result, llm_config)


async def _merge_both_sources(
    question: str,
    graphify_result: str,
    wiki_result: str,
    llm_config: dict,
) -> str:
    """合并 graphify 和 wiki 两个来源的结果

    构建合并 Prompt，让 LLM 综合代码结构分析和项目文档生成统一答案。

    Args:
        question: 用户原始问题
        graphify_result: graphify 代码结构分析结果
        wiki_result: wiki 项目文档检索结果
        llm_config: LLM 配置字典
    Returns:
        合并后的回答文本
    """
    if not llm_config:
        return (
            f"【代码结构分析】\n{graphify_result.strip()}\n\n"
            f"【项目文档】\n{wiki_result.strip()}"
        )

    system_prompt = _MERGE_BOTH_PROMPT.format(
        graphify_result=graphify_result.strip(),
        wiki_result=wiki_result.strip(),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    answer = await simple_chat(config=llm_config, messages=messages)
    return answer


async def _generate_from_graphify(
    question: str,
    graphify_result: str,
    llm_config: dict,
) -> str:
    """基于 graphify 代码结构分析结果生成回答

    当只有 graphify 结果时，通过 LLM 将代码结构信息转化为自然语言回答。

    Args:
        question: 用户原始问题
        graphify_result: graphify 代码结构分析结果
        llm_config: LLM 配置字典
    Returns:
        基于代码结构的回答文本
    """
    if not llm_config:
        return f"【代码结构分析】\n{graphify_result.strip()}"

    system_prompt = _GRAPHIFY_ONLY_PROMPT.format(
        graphify_result=graphify_result.strip(),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    answer = await simple_chat(config=llm_config, messages=messages)
    return answer


async def _generate_from_wiki(
    question: str,
    wiki_result: str,
    llm_config: dict,
) -> str:
    """基于 wiki 项目文档内容生成回答

    当只有 wiki 结果时，通过 LLM 根据文档内容针对用户问题生成回答，
    而非直接返回原始文档片段。

    Args:
        question: 用户原始问题
        wiki_result: wiki 项目文档检索结果
        llm_config: LLM 配置字典
    Returns:
        基于文档内容的回答文本
    """
    if not llm_config:
        return f"【项目文档】\n{wiki_result.strip()}"

    system_prompt = _WIKI_ONLY_PROMPT.format(
        wiki_result=wiki_result.strip(),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    answer = await simple_chat(config=llm_config, messages=messages)
    return answer


# ---------------------------------------------------------------------------
# 独立运行测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _test():
        """测试多源答案合并逻辑（不使用 LLM）"""
        print("=" * 60)
        print("AnswerMerger 合并测试（无 LLM 配置）")
        print("=" * 60)

        # 测试1：两个来源都没有
        result = await generate_answer("测试问题")
        print(f"\n[无来源] 结果: {result}")

        # 测试2：仅 wiki 结果
        result = await generate_answer(
            "如何安装？",
            wiki_result="安装步骤：1. 克隆仓库 2. 安装依赖 3. 运行启动脚本",
        )
        print(f"\n[仅Wiki] 结果: {result}")

        # 测试3：仅 graphify 结果（无 LLM）
        result = await generate_answer(
            "find_impact 在哪里被调用？",
            graphify_result="find_impact 被 find_callers 和 search 两个函数调用",
        )
        print(f"\n[仅Graphify] 结果: {result}")

        # 测试4：两个来源都有（无 LLM，简单拼接）
        result = await generate_answer(
            "修改 find_impact 会影响什么？",
            graphify_result="find_impact 被 find_callers 和 search 调用",
            wiki_result="find_impact 是 GraphifyQuery 类的核心方法，用于分析函数修改的影响范围",
        )
        print(f"\n[双源合并] 结果: {result}")

    asyncio.run(_test())
