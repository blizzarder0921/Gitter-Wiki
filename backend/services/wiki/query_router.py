"""
智能查询路由模块

根据用户问题中的关键词模式，自动判断问题类型并生成路由决策。
将问题分为 code / troubleshooting / knowledge / general 四类，
每类对应不同的数据源（graphify / wiki）和目标页面路径。

仅依赖 re 标准库，无项目内部模块依赖。
"""

import re


class QueryRouter:
    """智能查询路由，根据用户问题关键词判断走哪个引擎

    通过正则匹配将用户问题分为四类：
    - code: 代码相关问题，需要 graphify + wiki 双源
    - troubleshooting: 排查类问题，仅需 wiki
    - knowledge: 知识类问题，仅需 wiki
    - general: 通用问题，需要 graphify + wiki 双源
    """

    # 代码相关问题关键词模式
    # 匹配：函数/方法/类/模块/文件/调用/依赖/import/def/class/修改/改哪个/影响/变更
    # 以及代码文件名模式（如 xxx.py / xxx.ts / xxx.js 等）
    CODE_PATTERNS = [
        re.compile(r"函数|方法|类|模块|文件", re.IGNORECASE),
        re.compile(r"调用|依赖|import|from\s+\w+", re.IGNORECASE),
        re.compile(r"\bdef\b|\bclass\b", re.IGNORECASE),
        re.compile(r"修改|改哪个|影响|变更", re.IGNORECASE),
        re.compile(r"\w+\.(py|ts|js|tsx|jsx|java|go|rs|c|cpp|h|rb|php|cs|swift|kt)$", re.IGNORECASE),
        re.compile(r"参数|返回值|接口|API|实现", re.IGNORECASE),
    ]

    # 知识类问题关键词模式
    # 匹配：安装/使用/教程/入门/快速上手/是什么/干嘛的/为什么/设计/架构/原理/配置/参数
    KNOWLEDGE_PATTERNS = [
        re.compile(r"安装|使用|教程|入门|快速上手", re.IGNORECASE),
        re.compile(r"是什么|干嘛的|为什么|如何理解", re.IGNORECASE),
        re.compile(r"设计|架构|原理|机制|流程", re.IGNORECASE),
        re.compile(r"配置|参数|设置|选项", re.IGNORECASE),
        re.compile(r"概念|介绍|概述|说明|文档", re.IGNORECASE),
    ]

    # 排查类问题关键词模式
    # 匹配：报错/错误/失败/问题/bug/exception/error/卡住/不行/怎么解决
    TROUBLESHOOTING_PATTERNS = [
        re.compile(r"报错|错误|失败|异常", re.IGNORECASE),
        re.compile(r"问题|bug|exception|error|traceback", re.IGNORECASE),
        re.compile(r"卡住|不行|怎么解决|无法|不能", re.IGNORECASE),
        re.compile(r"崩溃|crash|timeout|超时", re.IGNORECASE),
        re.compile(r"不工作|不生效|不正常|不正确", re.IGNORECASE),
    ]

    # 各类型对应的路由配置
    # 包含数据源需求（graphify_needed / wiki_needed）和目标页面路径
    ROUTE_CONFIG = {
        "code": {
            "graphify_needed": True,
            "wiki_needed": True,
            "target_pages": [
                "internals/architecture.md",
                "internals/modules/",
            ],
            "instruction": "请结合代码结构分析和项目文档回答代码相关问题，重点关注函数调用链和模块依赖关系。",
        },
        "troubleshooting": {
            "graphify_needed": False,
            "wiki_needed": True,
            "target_pages": [
                "guides/troubleshooting.md",
            ],
            "instruction": "请基于项目文档中的故障排查指南回答问题，提供具体的解决步骤。",
        },
        "knowledge": {
            "graphify_needed": False,
            "wiki_needed": True,
            "target_pages": [
                "basics/",
                "guides/",
            ],
            "instruction": "请基于项目文档中的基础知识和使用指南回答问题，提供清晰的解释和示例。",
        },
        "general": {
            "graphify_needed": True,
            "wiki_needed": True,
            "target_pages": [
                "basics/",
                "guides/",
                "internals/",
            ],
            "instruction": "请综合代码结构分析和项目文档回答问题，提供全面的信息。",
        },
    }

    def classify(self, question: str) -> tuple[str, float]:
        """分类问题类型，返回 (type, confidence)

        按优先级依次匹配 troubleshooting > code > knowledge，
        匹配到的模式数量越多置信度越高。
        若无任何模式命中，则归为 general 类型。

        Args:
            question: 用户问题文本
        Returns:
            (type, confidence) 元组
            - type: code / troubleshooting / knowledge / general
            - confidence: 0.0 ~ 1.0，匹配模式越多越高
        """
        if not question or not question.strip():
            return ("general", 0.0)

        question = question.strip()

        # 依次统计各类型匹配的模式数量
        troubleshooting_hits = sum(
            1 for p in self.TROUBLESHOOTING_PATTERNS if p.search(question)
        )
        code_hits = sum(
            1 for p in self.CODE_PATTERNS if p.search(question)
        )
        knowledge_hits = sum(
            1 for p in self.KNOWLEDGE_PATTERNS if p.search(question)
        )

        # 无任何模式命中，归为 general
        if troubleshooting_hits == 0 and code_hits == 0 and knowledge_hits == 0:
            return ("general", 0.3)

        # 按优先级选择类型：troubleshooting > code > knowledge
        # troubleshooting 优先级最高，因为报错类问题最紧急
        if troubleshooting_hits > 0:
            max_possible = len(self.TROUBLESHOOTING_PATTERNS)
            confidence = min(0.5 + 0.5 * (troubleshooting_hits / max_possible), 1.0)
            return ("troubleshooting", round(confidence, 2))

        if code_hits > 0:
            max_possible = len(self.CODE_PATTERNS)
            confidence = min(0.5 + 0.5 * (code_hits / max_possible), 1.0)
            return ("code", round(confidence, 2))

        if knowledge_hits > 0:
            max_possible = len(self.KNOWLEDGE_PATTERNS)
            confidence = min(0.5 + 0.5 * (knowledge_hits / max_possible), 1.0)
            return ("knowledge", round(confidence, 2))

        return ("general", 0.3)

    def route(self, question: str) -> dict:
        """返回路由决策字典

        根据问题分类结果，生成包含数据源需求、目标页面和回答指令的路由决策。

        Args:
            question: 用户问题文本
        Returns:
            路由决策字典，包含以下字段：
            - type: 问题类型
            - confidence: 分类置信度
            - sources: 需要查询的数据源列表
            - graphify_needed: 是否需要 graphify 数据源
            - wiki_needed: 是否需要 wiki 数据源
            - target_pages: 目标页面路径列表
            - instruction: 回答生成指令
        """
        q_type, confidence = self.classify(question)
        config = self.ROUTE_CONFIG[q_type]

        # 构建数据源列表
        sources = []
        if config["graphify_needed"]:
            sources.append("graphify")
        if config["wiki_needed"]:
            sources.append("wiki")

        return {
            "type": q_type,
            "confidence": confidence,
            "sources": sources,
            "graphify_needed": config["graphify_needed"],
            "wiki_needed": config["wiki_needed"],
            "target_pages": config["target_pages"],
            "instruction": config["instruction"],
        }


# ---------------------------------------------------------------------------
# 独立运行测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    router = QueryRouter()

    # 测试用例：覆盖四种类型
    test_questions = [
        # code 类型
        "find_impact 函数在哪里被调用？",
        "修改 graphify_query.py 会影响哪些模块？",
        "import llm_client 的地方有哪些？",
        # troubleshooting 类型
        "启动报错 ModuleNotFoundError 怎么解决？",
        "数据库连接失败，error 日志如下",
        "页面渲染不正常，卡住了",
        # knowledge 类型
        "这个项目是什么？架构是怎样的？",
        "如何安装和配置？",
        "快速上手教程在哪里？",
        # general 类型
        "你好",
        "今天天气怎么样？",
    ]

    print("=" * 60)
    print("QueryRouter 分类测试")
    print("=" * 60)

    for q in test_questions:
        result = router.route(q)
        print(f"\n问题: {q}")
        print(f"  类型: {result['type']}  置信度: {result['confidence']}")
        print(f"  数据源: {result['sources']}")
        print(f"  目标页面: {result['target_pages']}")
