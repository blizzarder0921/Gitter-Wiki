"""
图谱洞察模块

从知识图谱中发现"意外连接"和"知识缺口"。
移植自 TypeScript 项目 llm_wiki-0.4.9/src/lib/graph-insights.ts。

核心功能：
- 意外连接检测：基于 4 信号评分发现跨社区/跨类型/外围-枢纽/低权重的意外边
- 知识缺口检测：识别孤立节点、稀疏社区和桥接节点

依赖：wiki_graph.py（类型定义）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class SurprisingConnection:
    """意外连接

    Attributes:
        source: 源节点信息（字典，包含 id/label/type/community/linkCount 等）
        target: 目标节点信息
        score: 信号评分总和
        reasons: 触发信号的原因列表
        key: 稳定标识（用于 dismiss 跟踪），格式为排序后的 "id1:::id2"
    """
    def __init__(self, source: dict, target: dict, score: int,
                 reasons: list[str], key: str):
        self.source = source
        self.target = target
        self.score = score
        self.reasons = reasons
        self.key = key

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "source": self.source,
            "target": self.target,
            "score": self.score,
            "reasons": self.reasons,
            "key": self.key,
        }


class KnowledgeGap:
    """知识缺口

    Attributes:
        type: 缺口类型（isolated-node / sparse-community / bridge-node）
        title: 缺口标题
        description: 缺口描述
        nodeIds: 相关节点 ID 列表
        suggestion: 修复建议
    """
    def __init__(self, type: str, title: str, description: str,
                 node_ids: list[str], suggestion: str):
        self.type = type
        self.title = title
        self.description = description
        self.nodeIds = node_ids
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "nodeIds": self.nodeIds,
            "suggestion": self.suggestion,
        }


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 结构性页面（链接到所有内容），排除在分析之外
STRUCTURAL_IDS = frozenset(["index", "log", "overview"])

# 远距类型对：跨类型连接中，这些类型对距离更远，评分更高
DISTANT_TYPE_PAIRS = frozenset([
    "source-concept", "concept-source",
    "source-synthesis", "synthesis-source",
    "query-entity", "entity-query",
])


# ---------------------------------------------------------------------------
# 意外连接检测
# ---------------------------------------------------------------------------

def find_surprising_connections(
    nodes: list[dict],
    edges: list[dict],
    communities: list[dict],
    limit: int = 10,
) -> list[dict]:
    """发现图谱中的意外连接

    基于 4 信号评分系统检测跨社区、跨类型、外围-枢纽耦合和低权重的边：
    - 跨社区边: +3
    - 跨类型边（远距类型对）: +2，其他跨类型: +1
    - 外围-枢纽耦合（度<=2 链接到度>=maxDegree*0.5）: +2
    - 低权重边（0 < weight < 2）: +1
    阈值: score >= 3 才报告

    Args:
        nodes: 节点列表，每项包含 id/label/type/community/linkCount 等
        edges: 边列表，每项包含 source/target/weight
        communities: 社区信息列表
        limit: 返回结果数量上限
    Returns:
        意外连接列表，按 score 降序排列
    """
    # 构建节点查找映射
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}
    degree_map: dict[str, int] = {n["id"]: n.get("linkCount", 0) for n in nodes}

    # 计算最大度数（至少为 1，避免除零）
    max_degree = max((n.get("linkCount", 0) for n in nodes), default=1)
    max_degree = max(max_degree, 1)

    scored: list[SurprisingConnection] = []

    for edge in edges:
        source = node_map.get(edge["source"])
        target = node_map.get(edge["target"])
        if not source or not target:
            continue

        # 排除结构性页面
        if source["id"] in STRUCTURAL_IDS or target["id"] in STRUCTURAL_IDS:
            continue

        score = 0
        reasons: list[str] = []

        # 信号 1：跨社区边 (+3)
        source_community = source.get("community", 0)
        target_community = target.get("community", 0)
        if source_community != target_community:
            score += 3
            reasons.append("crosses community boundary")

        # 信号 2：跨类型边
        source_type = source.get("type", "other")
        target_type = target.get("type", "other")
        if source_type != target_type:
            pair = f"{source_type}-{target_type}"
            if pair in DISTANT_TYPE_PAIRS:
                score += 2
                reasons.append(f"connects {source_type} to {target_type}")
            else:
                score += 1
                reasons.append("different types")

        # 信号 3：外围-枢纽耦合 (+2)
        source_deg = degree_map.get(source["id"], 0)
        target_deg = degree_map.get(target["id"], 0)
        min_deg = min(source_deg, target_deg)
        max_deg = max(source_deg, target_deg)
        if min_deg <= 2 and max_deg >= max_degree * 0.5:
            score += 2
            reasons.append("peripheral node links to hub")

        # 信号 4：低权重边（0 < weight < 2）(+1)
        weight = edge.get("weight", 1.0)
        if 0 < weight < 2:
            score += 1
            reasons.append("weak but present connection")

        # 阈值过滤：score >= 3 才报告
        if score >= 3 and reasons:
            # 生成稳定 key（排序后拼接，确保 A-B 和 B-A 生成相同 key）
            key_parts = sorted([source["id"], target["id"]])
            key = ":::".join(key_parts)
            scored.append(SurprisingConnection(
                source=source,
                target=target,
                score=score,
                reasons=reasons,
                key=key,
            ))

    # 按 score 降序排列
    scored.sort(key=lambda sc: sc.score, reverse=True)

    return [sc.to_dict() for sc in scored[:limit]]


# ---------------------------------------------------------------------------
# 知识缺口检测
# ---------------------------------------------------------------------------

def detect_knowledge_gaps(
    nodes: list[dict],
    edges: list[dict],
    communities: list[dict],
    limit: int = 10,
) -> list[dict]:
    """检测知识图谱中的知识缺口

    三类缺口：
    1. 孤立节点：入度 <= 1（排除 overview/index/log）
    2. 稀疏社区：凝聚度 < 0.15 且节点数 >= 3
    3. 桥接节点：连接 >= 3 个不同社区的节点

    Args:
        nodes: 节点列表
        edges: 边列表
        communities: 社区信息列表
        limit: 返回结果数量上限
    Returns:
        知识缺口列表
    """
    gaps: list[KnowledgeGap] = []
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}

    # ── 1. 孤立节点 ──────────────────────────────────────────────
    isolated_nodes = [
        n for n in nodes
        if n.get("linkCount", 0) <= 1
        and n.get("type") != "overview"
        and n["id"] != "index"
        and n["id"] != "log"
    ]

    if isolated_nodes:
        top_isolated = isolated_nodes[:5]
        labels = ", ".join(n.get("label", n["id"]) for n in top_isolated)
        suffix = (
            f" and {len(isolated_nodes) - 5} more"
            if len(isolated_nodes) > 5
            else ""
        )
        plural = "s" if len(isolated_nodes) > 1 else ""
        gaps.append(KnowledgeGap(
            type="isolated-node",
            title=f"{len(isolated_nodes)} isolated page{plural}",
            description=labels + suffix,
            node_ids=[n["id"] for n in isolated_nodes],
            suggestion=(
                "These pages have few or no connections. "
                "Consider adding [[wikilinks]] to related pages, "
                "or research to expand their content."
            ),
        ))

    # ── 2. 稀疏社区（低凝聚度） ──────────────────────────────────
    for comm in communities:
        cohesion = comm.get("cohesion", 0)
        node_count = comm.get("nodeCount", 0)
        if cohesion < 0.15 and node_count >= 3:
            top_node_label = (
                comm.get("topNodes", [""])[0]
                or f"Community {comm['id']}"
            )
            # 查找属于该社区的所有节点 ID
            comm_node_ids = [
                n["id"] for n in nodes
                if n.get("community") == comm["id"]
            ]
            gaps.append(KnowledgeGap(
                type="sparse-community",
                title=f"Sparse cluster: {top_node_label}",
                description=(
                    f"{node_count} pages with cohesion "
                    f"{cohesion:.2f} — internal connections are weak."
                ),
                node_ids=comm_node_ids,
                suggestion=(
                    "This knowledge area lacks internal cross-references. "
                    "Consider adding links between these pages or "
                    "researching to fill gaps."
                ),
            ))

    # ── 3. 桥接节点（连接多个社区） ──────────────────────────────
    # 计算每个节点连接的不同社区集合
    community_neighbors: dict[str, set[int]] = {
        n["id"]: set() for n in nodes
    }

    for edge in edges:
        source_node = node_map.get(edge["source"])
        target_node = node_map.get(edge["target"])
        if source_node and target_node:
            target_community = target_node.get("community", 0)
            source_community = source_node.get("community", 0)
            community_neighbors[edge["source"]].add(target_community)
            community_neighbors[edge["target"]].add(source_community)

    # 筛选桥接节点：连接 >= 3 个不同社区，排除结构性页面
    bridge_nodes = [
        n for n in nodes
        if n["id"] not in STRUCTURAL_IDS
        and len(community_neighbors.get(n["id"], set())) >= 3
    ]

    # 按连接社区数降序排列，取前 3 个
    bridge_nodes.sort(
        key=lambda n: len(community_neighbors.get(n["id"], set())),
        reverse=True,
    )
    bridge_nodes = bridge_nodes[:3]

    for bridge in bridge_nodes:
        comm_count = len(community_neighbors.get(bridge["id"], set()))
        gaps.append(KnowledgeGap(
            type="bridge-node",
            title=f"Key bridge: {bridge.get('label', bridge['id'])}",
            description=(
                f"Connects {comm_count} different knowledge clusters. "
                "This is a critical junction in your wiki."
            ),
            node_ids=[bridge["id"]],
            suggestion=(
                "This page bridges multiple knowledge areas. "
                "Ensure it's well-maintained — if it's thin, "
                "expanding it will strengthen your entire wiki."
            ),
        ))

    return [g.to_dict() for g in gaps[:limit]]
