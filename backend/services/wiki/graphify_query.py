"""
Graphify 代码结构查询模块

基于 graph.json（NetworkX 格式）提供代码结构的查询能力，
包括调用者查找、被调用者查找、影响范围分析等。

graph.json 格式参考：
{
    "nodes": [{"id": "module.function", "type": "function", ...}],
    "edges": [{"source": "module.caller", "target": "module.callee", "type": "calls", ...}]
}

仅依赖 json 标准库，无项目内部模块依赖。
"""

import json
from collections import deque


class GraphifyQuery:
    """基于 graph.json 的代码结构查询

    加载 NetworkX 导出的 graph.json，构建内存中的调用图索引，
    提供 BFS 遍历的调用链查询和影响范围分析。

    Attributes:
        nodes: 节点字典 {node_id: node_data}
        edges: 边列表 [{"source": ..., "target": ..., ...}]
        callers_map: 被调用索引 {callee_id: [caller_id, ...]}
        callees_map: 调用索引 {caller_id: [callee_id, ...]}
    """

    def __init__(self, graph_path: str):
        """加载 graph.json 并构建索引

        读取指定路径的 graph.json 文件，解析节点和边，
        构建 callers_map（谁调用了谁）和 callees_map（谁被谁调用）两个索引，
        以支持高效的 BFS 遍历查询。

        Args:
            graph_path: graph.json 文件的路径
        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 解析节点列表为字典，便于按 id 快速查找
        self.nodes: dict[str, dict] = {}
        for node in data.get("nodes", []):
            node_id = node.get("id", "")
            if node_id:
                self.nodes[node_id] = node

        # 解析边列表
        self.edges: list[dict] = data.get("edges", [])

        # 构建 callers_map: callee_id -> [caller_id, ...]
        # 表示"谁调用了这个函数"，用于向上追溯调用链
        self.callers_map: dict[str, list[str]] = {}
        # 构建 callees_map: caller_id -> [callee_id, ...]
        # 表示"这个函数调用了谁"，用于向下追踪依赖
        self.callees_map: dict[str, list[str]] = {}

        for edge in self.edges:
            source = edge.get("source", "")
            target = edge.get("target", "")
            edge_type = edge.get("type", "")

            # 仅处理 "calls" 类型的边
            if edge_type != "calls" or not source or not target:
                continue

            # callers_map: target 被 source 调用
            if target not in self.callers_map:
                self.callers_map[target] = []
            self.callers_map[target].append(source)

            # callees_map: source 调用了 target
            if source not in self.callees_map:
                self.callees_map[source] = []
            self.callees_map[source].append(target)

    def find_callers(self, function_name: str) -> list[str]:
        """查找谁调用了指定函数（BFS 遍历）

        从指定函数出发，沿 callers_map 向上 BFS 遍历，
        找出所有直接和间接调用该函数的函数。

        Args:
            function_name: 函数名（支持完整 id 或部分名称匹配）
        Returns:
            调用者 id 列表，按 BFS 遍历顺序排列（去重）
        """
        # 查找匹配的节点
        matched_ids = self._match_function(function_name)
        if not matched_ids:
            return []

        # BFS 遍历 callers_map
        visited: set[str] = set()
        result: list[str] = []
        queue: deque[str] = deque()

        for fid in matched_ids:
            queue.append(fid)
            visited.add(fid)

        while queue:
            current = queue.popleft()
            # 跳过起始节点本身（不把查询目标列入结果）
            if current not in matched_ids:
                result.append(current)

            # 继续向上追溯调用者
            for caller_id in self.callers_map.get(current, []):
                if caller_id not in visited:
                    visited.add(caller_id)
                    queue.append(caller_id)

        return result

    def find_callees(self, function_name: str) -> list[str]:
        """查找指定函数调用了谁（BFS 遍历）

        从指定函数出发，沿 callees_map 向下 BFS 遍历，
        找出该函数直接和间接调用的所有函数。

        Args:
            function_name: 函数名（支持完整 id 或部分名称匹配）
        Returns:
            被调用者 id 列表，按 BFS 遍历顺序排列（去重）
        """
        # 查找匹配的节点
        matched_ids = self._match_function(function_name)
        if not matched_ids:
            return []

        # BFS 遍历 callees_map
        visited: set[str] = set()
        result: list[str] = []
        queue: deque[str] = deque()

        for fid in matched_ids:
            queue.append(fid)
            visited.add(fid)

        while queue:
            current = queue.popleft()
            # 跳过起始节点本身
            if current not in matched_ids:
                result.append(current)

            # 继续向下追踪被调用者
            for callee_id in self.callees_map.get(current, []):
                if callee_id not in visited:
                    visited.add(callee_id)
                    queue.append(callee_id)

        return result

    def find_impact(self, function_name: str, depth: int = 2) -> dict:
        """分析修改某函数的影响范围（BFS 向上遍历调用链）

        从指定函数出发，沿 callers_map 向上 BFS 遍历指定深度，
        找出所有可能受影响的调用者。结果按层级组织，
        第 1 层为直接调用者，第 2 层为调用直接调用者的函数，以此类推。

        Args:
            function_name: 函数名（支持完整 id 或部分名称匹配）
            depth: BFS 遍历深度，默认 2 层
        Returns:
            影响范围字典，包含以下字段：
            - target: 查询的目标函数 id
            - depth: 遍历深度
            - levels: 按层级组织的调用者列表 {层级: [caller_id, ...]}
            - total_affected: 受影响函数总数
        """
        # 查找匹配的节点
        matched_ids = self._match_function(function_name)
        if not matched_ids:
            return {
                "target": function_name,
                "depth": depth,
                "levels": {},
                "total_affected": 0,
            }

        # 取第一个匹配的节点作为目标
        target_id = matched_ids[0]

        # BFS 向上遍历，记录每一层的调用者
        levels: dict[int, list[str]] = {}
        visited: set[str] = {target_id}
        current_level_nodes = [target_id]

        for level in range(1, depth + 1):
            next_level_nodes: list[str] = []

            for node_id in current_level_nodes:
                for caller_id in self.callers_map.get(node_id, []):
                    if caller_id not in visited:
                        visited.add(caller_id)
                        next_level_nodes.append(caller_id)

            if not next_level_nodes:
                break

            levels[level] = next_level_nodes
            current_level_nodes = next_level_nodes

        # 计算受影响总数（不含目标本身）
        total_affected = sum(len(v) for v in levels.values())

        return {
            "target": target_id,
            "depth": depth,
            "levels": levels,
            "total_affected": total_affected,
        }

    def search(self, query: str) -> str:
        """自然语言查询，返回格式化的代码结构信息

        根据查询关键词在节点 id 和节点属性中进行模糊匹配，
        返回匹配节点的详细信息（类型、调用者、被调用者）。

        Args:
            query: 查询关键词
        Returns:
            格式化的代码结构信息文本
        """
        if not query or not query.strip():
            return "请提供查询关键词。"

        query = query.strip().lower()

        # 在节点 id 和属性中搜索匹配
        matched_nodes: list[str] = []
        for node_id, node_data in self.nodes.items():
            # 匹配节点 id
            if query in node_id.lower():
                matched_nodes.append(node_id)
                continue
            # 匹配节点属性值
            for key, value in node_data.items():
                if isinstance(value, str) and query in value.lower():
                    matched_nodes.append(node_id)
                    break

        if not matched_nodes:
            return f"未找到与 '{query}' 相关的代码结构信息。"

        # 格式化输出每个匹配节点的信息
        lines: list[str] = []
        for node_id in matched_nodes:
            node_data = self.nodes[node_id]
            node_type = node_data.get("type", "unknown")

            lines.append(f"## {node_id}")
            lines.append(f"  类型: {node_type}")

            # 调用者信息
            callers = self.callers_map.get(node_id, [])
            if callers:
                lines.append(f"  被调用者 ({len(callers)}): {', '.join(callers)}")
            else:
                lines.append("  被调用者: 无")

            # 被调用者信息
            callees = self.callees_map.get(node_id, [])
            if callees:
                lines.append(f"  调用了 ({len(callees)}): {', '.join(callees)}")
            else:
                lines.append("  调用了: 无")

            lines.append("")  # 空行分隔

        return "\n".join(lines)

    def _match_function(self, function_name: str) -> list[str]:
        """模糊匹配函数名，返回匹配的节点 id 列表

        支持三种匹配方式：
        1. 精确匹配：function_name 等于节点 id
        2. 后缀匹配：节点 id 以 function_name 结尾（如 "module.func" 匹配 "func"）
        3. 包含匹配：节点 id 包含 function_name

        Args:
            function_name: 函数名或部分名称
        Returns:
            匹配的节点 id 列表
        """
        if not function_name:
            return []

        fn_lower = function_name.lower()

        # 优先精确匹配
        exact = [nid for nid in self.nodes if nid == function_name]
        if exact:
            return exact

        # 后缀匹配（如 "func" 匹配 "module.func"）
        suffix = [
            nid for nid in self.nodes
            if nid.lower().endswith(f".{fn_lower}") or nid.lower() == fn_lower
        ]
        if suffix:
            return suffix

        # 包含匹配
        contains = [nid for nid in self.nodes if fn_lower in nid.lower()]
        return contains


# ---------------------------------------------------------------------------
# 独立运行测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import tempfile

    # 创建测试用的 graph.json
    test_graph = {
        "nodes": [
            {"id": "main.main", "type": "function"},
            {"id": "router.handle_request", "type": "function"},
            {"id": "router.validate_input", "type": "function"},
            {"id": "service.process_data", "type": "function"},
            {"id": "service.query_database", "type": "function"},
            {"id": "db.execute_sql", "type": "function"},
            {"id": "utils.format_response", "type": "function"},
            {"id": "utils.log_error", "type": "function"},
        ],
        "edges": [
            {"source": "main.main", "target": "router.handle_request", "type": "calls"},
            {"source": "router.handle_request", "target": "router.validate_input", "type": "calls"},
            {"source": "router.handle_request", "target": "service.process_data", "type": "calls"},
            {"source": "service.process_data", "target": "service.query_database", "type": "calls"},
            {"source": "service.process_data", "target": "utils.format_response", "type": "calls"},
            {"source": "service.query_database", "target": "db.execute_sql", "type": "calls"},
            {"source": "router.handle_request", "target": "utils.log_error", "type": "calls"},
        ],
    }

    # 写入临时文件
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(test_graph, f, ensure_ascii=False, indent=2)
        temp_path = f.name

    try:
        gq = GraphifyQuery(temp_path)

        print("=" * 60)
        print("GraphifyQuery 查询测试")
        print("=" * 60)

        # 测试 find_callers
        callers = gq.find_callers("execute_sql")
        print(f"\n调用 db.execute_sql 的函数: {callers}")

        # 测试 find_callees
        callees = gq.find_callees("handle_request")
        print(f"router.handle_request 调用的函数: {callees}")

        # 测试 find_impact
        impact = gq.find_impact("execute_sql", depth=3)
        print(f"\n修改 db.execute_sql 的影响范围:")
        print(f"  目标: {impact['target']}")
        print(f"  总影响数: {impact['total_affected']}")
        for level, nodes in impact["levels"].items():
            print(f"  第{level}层: {nodes}")

        # 测试 search
        result = gq.search("service")
        print(f"\n搜索 'service' 的结果:\n{result}")

    finally:
        # 清理临时文件
        os.unlink(temp_path)
