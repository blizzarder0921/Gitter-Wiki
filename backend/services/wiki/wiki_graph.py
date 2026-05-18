"""
知识图谱构建模块

从 Wiki 页面构建知识图谱，提取节点和边，运行 Louvain 社区检测。
移植自 TypeScript 项目 llm_wiki-0.4.9/src/lib/wiki-graph.ts。

核心功能：
- 扫描 Wiki 目录下所有 .md 文件，提取页面元数据和双向链接
- 解析 Wikilink 并进行大小写不敏感 + 空格/连字符归一化匹配
- 使用 networkx + python-louvain 执行社区检测
- 计算社区凝聚度（cohesion = 实际社区内边数 / 可能的最大边数）
- 通过 graph_relevance 模块计算边权重

依赖：graph_relevance.py, frontmatter.py
"""

import os
import re
import logging
from typing import Optional

import networkx as nx

try:
    import community as community_louvain  # python-louvain
except ImportError:
    community_louvain = None  # 降级：无社区检测时返回空社区

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class GraphNode:
    """图谱节点

    Attributes:
        id: 节点标识（文件名去掉 .md 后缀）
        label: 显示标题
        type: 页面类型（source/entity/concept/synthesis/comparison/query/other）
        path: 文件相对路径
        linkCount: 入度 + 出度链接总数
        community: Louvain 社区检测分配的社区 ID
        projectSources: 节点所属的源文件列表（如 ["1.md", "2.md"]），用于项目归属判断
    """
    def __init__(self, id: str, label: str, type: str, path: str,
                 link_count: int = 0, community: int = 0,
                 project_sources: list[str] | None = None):
        self.id = id
        self.label = label
        self.type = type
        self.path = path
        self.linkCount = link_count
        self.community = community
        self.projectSources = project_sources or []

    def to_dict(self) -> dict:
        """转换为字典格式，用于 API 响应序列化"""
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "path": self.path,
            "linkCount": self.linkCount,
            "community": self.community,
            "projectSources": self.projectSources,
        }


class GraphEdge:
    """图谱边

    Attributes:
        source: 源节点 ID
        target: 目标节点 ID
        weight: 相关性权重（由 graph_relevance.calculate_relevance 计算）
    """
    def __init__(self, source: str, target: str, weight: float = 1.0):
        self.source = source
        self.target = target
        self.weight = weight

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "source": self.source,
            "target": self.target,
            "weight": self.weight,
        }


class CommunityInfo:
    """社区信息

    Attributes:
        id: 社区编号（从 0 开始顺序编号）
        nodeCount: 社区内节点数
        cohesion: 社区凝聚度 = 实际社区内边数 / 可能的最大边数 n*(n-1)/2
        topNodes: 按 linkCount 排序的前 5 个节点标签
    """
    def __init__(self, id: int, node_count: int, cohesion: float,
                 top_nodes: list[str]):
        self.id = id
        self.nodeCount = node_count
        self.cohesion = cohesion
        self.topNodes = top_nodes

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "nodeCount": self.nodeCount,
            "cohesion": round(self.cohesion, 4),
            "topNodes": self.topNodes,
        }


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Wikilink 正则：匹配 [[target]] 或 [[target|display]]
WIKILINK_REGEX = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')

# 隐藏类型：query 类型节点是中间产物，不属于知识结构
HIDDEN_TYPES = frozenset(["query"])


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _flatten_md_files(directory: str, prefix: str = "") -> list[dict]:
    """递归扫描目录，收集所有 .md 文件信息

    Args:
        directory: 目录绝对路径
        prefix: 路径前缀（用于构建相对路径）
    Returns:
        文件信息列表，每项包含 name, path（绝对路径）, rel_path（相对路径）
    """
    files: list[dict] = []
    if not os.path.exists(directory):
        return files

    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return files

    for entry in entries:
        if entry.startswith("."):
            continue
        full_path = os.path.join(directory, entry)
        rel_path = f"{prefix}/{entry}" if prefix else entry

        if os.path.isdir(full_path):
            files.extend(_flatten_md_files(full_path, rel_path))
        elif entry.endswith(".md"):
            files.append({
                "name": entry,
                "path": full_path,
                "rel_path": rel_path,
            })

    return files


def _extract_title(content: str, file_name: str) -> str:
    """从 Markdown 内容提取页面标题

    提取优先级：
    1. YAML frontmatter 中的 title 字段
    2. 第一个 # 标题
    3. 文件名（去掉 .md 后缀，连字符替换为空格）

    Args:
        content: Markdown 文件内容
        file_name: 文件名（含 .md 后缀）
    Returns:
        页面标题
    """
    # 尝试从 frontmatter 提取 title
    fm_match = re.search(r'^---\n[\s\S]*?^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    if fm_match:
        return fm_match.group(1).strip()

    # 尝试从第一个标题提取
    heading_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    # 回退到文件名
    return file_name.replace(".md", "").replace("-", " ")


def _extract_type(content: str) -> str:
    """从 Markdown 内容提取页面类型

    Args:
        content: Markdown 文件内容
    Returns:
        页面类型（小写），默认 "other"
    """
    fm_match = re.search(r'^---\n[\s\S]*?^type:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    if fm_match:
        return fm_match.group(1).strip().lower()
    return "other"


def _extract_sources(content: str) -> list[str]:
    """从 Markdown frontmatter 提取 sources 字段

    sources 字段记录了生成该页面的源文件名列表，
    用于判断节点所属的项目来源。

    支持的格式：
    - YAML 数组：sources: ["1.md", "2.md"]
    - YAML 流式数组：sources: [1.md, 2.md]
    - YAML 多行数组：
      sources:
        - 1.md
        - 2.md

    Args:
        content: Markdown 文件内容
    Returns:
        源文件名列表，未找到时返回空列表
    """
    # 尝试匹配 YAML 流式数组：sources: ["1.md", "2.md"]
    fm_match = re.search(
        r'^---\n[\s\S]*?^sources:\s*\[(.*?)\]\s*$',
        content, re.MULTILINE,
    )
    if fm_match:
        raw = fm_match.group(1)
        items = re.findall(r'["\']?([^"\'\s,]+)["\']?', raw)
        return [item.strip() for item in items if item.strip()]

    # 尝试匹配 YAML 多行数组
    fm_block = re.search(r'^---\n([\s\S]*?)^---', content, re.MULTILINE)
    if fm_block:
        block = fm_block.group(1)
        lines = block.split('\n')
        in_sources = False
        sources: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('sources:'):
                in_sources = True
                # 单行 sources: value 的情况
                after_colon = stripped.split(':', 1)[1].strip()
                if after_colon and after_colon != '-':
                    items = re.findall(r'["\']?([^"\'\s,]+)["\']?', after_colon)
                    sources.extend(item.strip() for item in items if item.strip())
                continue
            if in_sources:
                if stripped.startswith('- '):
                    val = stripped[2:].strip().strip('"').strip("'")
                    if val:
                        sources.append(val)
                elif stripped and not stripped.startswith('#'):
                    in_sources = False
        return sources

    return []


def _extract_wikilinks(content: str) -> list[str]:
    """从 Markdown 内容提取所有 Wikilink 目标

    Args:
        content: Markdown 文件内容
    Returns:
        Wikilink 目标列表（已去除空白）
    """
    return [m.group(1).strip() for m in WIKILINK_REGEX.finditer(content)]


def _file_name_to_id(file_name: str) -> str:
    """将文件名转换为节点 ID（去掉 .md 后缀）

    Args:
        file_name: 文件名
    Returns:
        节点 ID
    """
    return file_name.replace(".md", "")


def _resolve_target(raw: str, node_ids: set[str]) -> Optional[str]:
    """解析 Wikilink 目标为实际节点 ID

    匹配策略（大小写不敏感 + 空格/连字符归一化）：
    1. 直接匹配
    2. 全小写匹配
    3. 空格替换为连字符后小写匹配
    4. 目标 ID 空格替换为连字符后小写匹配

    Args:
        raw: Wikilink 原始目标文本
        node_ids: 所有已知节点 ID 集合
    Returns:
        匹配到的节点 ID，未匹配返回 None
    """
    # 直接匹配
    if raw in node_ids:
        return raw

    # 归一化：小写 + 空格替换为连字符
    normalized = raw.lower().replace(" ", "-")
    for node_id in node_ids:
        id_lower = node_id.lower()
        if id_lower == normalized:
            return node_id
        if id_lower == raw.lower():
            return node_id
        if id_lower.replace(" ", "-") == normalized:
            return node_id

    return None


# ---------------------------------------------------------------------------
# 社区检测
# ---------------------------------------------------------------------------

def _detect_communities(
    nodes: list[dict],
    edges: list[GraphEdge],
) -> tuple[dict[str, int], list[CommunityInfo]]:
    """运行 Louvain 社区检测并计算每个社区的凝聚度

    Args:
        nodes: 节点列表，每项包含 id, label, linkCount
        edges: 边列表
    Returns:
        (assignments, communities) 元组
        - assignments: 节点 ID → 社区 ID 的映射
        - communities: 社区信息列表（按节点数降序排列，ID 从 0 重新编号）
    """
    if not nodes:
        return {}, []

    # 构建无向图
    g = nx.Graph()
    for node in nodes:
        g.add_node(node["id"])

    for edge in edges:
        if g.has_node(edge.source) and g.has_node(edge.target):
            # 避免重复边
            if not g.has_edge(edge.source, edge.target):
                g.add_edge(edge.source, edge.target, weight=edge.weight)

    # 运行 Louvain 社区检测
    if community_louvain is not None:
        try:
            community_map = community_louvain.best_partition(g, resolution=1.0)
        except Exception as e:
            logger.warning(f"[wiki-graph] Louvain 社区检测失败: {e}，回退到连通分量")
            community_map = _fallback_communities(g)
    else:
        # python-louvain 不可用时，使用连通分量作为社区
        logger.info("[wiki-graph] python-louvain 不可用，使用连通分量作为社区")
        community_map = _fallback_communities(g)

    # 构建节点 ID → 社区 ID 映射
    assignments: dict[str, int] = dict(community_map)

    # 按社区分组
    groups: dict[int, list[str]] = {}
    for node_id, comm_id in assignments.items():
        groups.setdefault(comm_id, []).append(node_id)

    # 构建边查找集合（双向）
    edge_set: set[str] = set()
    for edge in edges:
        edge_set.add(f"{edge.source}:::{edge.target}")
        edge_set.add(f"{edge.target}:::{edge.source}")

    # 构建节点信息查找
    node_info: dict[str, dict] = {n["id"]: n for n in nodes}

    # 计算每个社区的信息
    communities: list[CommunityInfo] = []
    for comm_id, member_ids in groups.items():
        n = len(member_ids)
        # 凝聚度 = 实际社区内边数 / 可能的最大边数
        intra_edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                if f"{member_ids[i]}:::{member_ids[j]}" in edge_set:
                    intra_edges += 1
        possible_edges = n * (n - 1) / 2 if n > 1 else 1
        cohesion = intra_edges / possible_edges if possible_edges > 0 else 0.0

        # 按 linkCount 降序排列，取前 5 个
        sorted_ids = sorted(
            member_ids,
            key=lambda nid: node_info.get(nid, {}).get("linkCount", 0),
            reverse=True,
        )
        top_nodes = [
            node_info.get(nid, {}).get("label", nid)
            for nid in sorted_ids[:5]
        ]

        communities.append(CommunityInfo(
            id=comm_id,
            node_count=n,
            cohesion=cohesion,
            top_nodes=top_nodes,
        ))

    # 按节点数降序排列
    communities.sort(key=lambda c: c.nodeCount, reverse=True)

    # 重新编号社区 ID（0, 1, 2, ...）
    id_remap: dict[int, int] = {}
    for idx, comm in enumerate(communities):
        id_remap[comm.id] = idx
        comm.id = idx

    # 更新 assignments 中的社区 ID
    for node_id in list(assignments.keys()):
        old_id = assignments[node_id]
        assignments[node_id] = id_remap.get(old_id, 0)

    return assignments, communities


def _fallback_communities(g: nx.Graph) -> dict[str, int]:
    """使用连通分量作为社区划分的降级方案

    Args:
        g: networkx 无向图
    Returns:
        节点 ID → 社区 ID 的映射
    """
    community_map: dict[str, int] = {}
    for idx, component in enumerate(nx.connected_components(g)):
        for node_id in component:
            community_map[node_id] = idx
    # 孤立节点也分配社区
    for node_id in g.nodes():
        if node_id not in community_map:
            community_map[node_id] = len(community_map)
    return community_map


# ---------------------------------------------------------------------------
# 核心接口
# ---------------------------------------------------------------------------

async def build_wiki_graph(project_path: str) -> dict:
    """从 Wiki 页面构建知识图谱

    扫描项目 Wiki 目录下所有 .md 文件，提取节点和边，
    运行 Louvain 社区检测，计算边权重和社区凝聚度。

    Args:
        project_path: 项目根目录的绝对路径
    Returns:
        {
            "nodes": [{"id", "label", "type", "path", "linkCount", "community"}],
            "edges": [{"source", "target", "weight"}],
            "communities": [{"id", "nodeCount", "cohesion", "topNodes"}]
        }
    """
    wiki_root = os.path.join(project_path, "wiki")

    # 扫描 Wiki 目录
    md_files = _flatten_md_files(wiki_root)
    if not md_files:
        return {"nodes": [], "edges": [], "communities": []}

    # 构建源文件→项目名称映射
    # 读取 wiki/sources/ 目录下的源摘要页面，提取 title 作为项目名称
    source_to_name: dict[str, str] = {}
    sources_dir = os.path.join(wiki_root, "sources")
    if os.path.isdir(sources_dir):
        for entry in os.listdir(sources_dir):
            if not entry.endswith(".md"):
                continue
            src_path = os.path.join(sources_dir, entry)
            try:
                with open(src_path, "r", encoding="utf-8") as f:
                    src_content = f.read()
                src_title = _extract_title(src_content, entry)
                # 源文件名作为 key（如 "1.md"）
                source_key = entry
                # 清理标题中的冗余前缀（如 "6.md - Index-anisora 项目分析" → "Index-anisora"）
                cleaned = re.sub(r'^\d+\.md\s*[-–—]\s*', '', src_title)
                cleaned = re.sub(r'\s*(项目介绍|项目分析|项目概述)\s*$', '', cleaned)
                source_to_name[source_key] = cleaned if cleaned else src_title
            except (OSError, UnicodeDecodeError):
                continue

    # 读取所有文件，构建节点映射
    # node_map: id → {id, label, type, path, links, sources}
    node_map: dict[str, dict] = {}

    for file_info in md_files:
        node_id = _file_name_to_id(file_info["name"])
        try:
            with open(file_info["path"], "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        node_map[node_id] = {
            "id": node_id,
            "label": _extract_title(content, file_info["name"]),
            "type": _extract_type(content),
            "path": file_info["rel_path"],
            "links": _extract_wikilinks(content),
            "sources": _extract_sources(content),
        }

    # 过滤掉隐藏类型节点（query 类型是中间产物）
    for node_id in list(node_map.keys()):
        if node_map[node_id]["type"] in HIDDEN_TYPES:
            del node_map[node_id]

    # 初始化链接计数
    link_counts: dict[str, int] = {nid: 0 for nid in node_map}

    # 构建原始边列表
    raw_edges: list[GraphEdge] = []
    node_ids = set(node_map.keys())

    for source_id, node_data in node_map.items():
        for target_raw in node_data["links"]:
            # 解析目标：大小写不敏感 + 空格/连字符归一化
            target_id = _resolve_target(target_raw, node_ids)
            if target_id is None:
                continue
            if target_id == source_id:
                continue

            raw_edges.append(GraphEdge(source=source_id, target=target_id, weight=1.0))

            link_counts[source_id] = link_counts.get(source_id, 0) + 1
            link_counts[target_id] = link_counts.get(target_id, 0) + 1

    # 边去重（无向图：A→B 和 B→A 视为同一条边）
    seen_edges: set[str] = set()
    deduped_edges: list[GraphEdge] = []
    for edge in raw_edges:
        key = f"{edge.source}:::{edge.target}"
        reverse_key = f"{edge.target}:::{edge.source}"
        if key not in seen_edges and reverse_key not in seen_edges:
            seen_edges.add(key)
            deduped_edges.append(edge)

    # 计算边权重（使用 graph_relevance 模块）
    edges: list[GraphEdge] = []
    try:
        from backend.services.wiki.graph_relevance import build_retrieval_graph, calculate_relevance
        retrieval_graph = build_retrieval_graph(project_path)
        if retrieval_graph is not None:
            for edge in deduped_edges:
                node_a = retrieval_graph.nodes.get(edge.source)
                node_b = retrieval_graph.nodes.get(edge.target)
                if node_a and node_b:
                    weight = calculate_relevance(node_a, node_b, retrieval_graph)
                    edges.append(GraphEdge(
                        source=edge.source, target=edge.target, weight=weight
                    ))
                else:
                    edges.append(edge)
        else:
            edges = deduped_edges
    except ImportError:
        logger.debug("[wiki-graph] graph_relevance 模块不可用，使用默认权重 1.0")
        edges = deduped_edges
    except Exception as e:
        logger.warning(f"[wiki-graph] 计算边权重失败: {e}，使用默认权重 1.0")
        edges = deduped_edges

    # 构建社区检测所需的节点列表
    prelim_nodes = [
        {
            "id": n["id"],
            "label": n["label"],
            "linkCount": link_counts.get(n["id"], 0),
        }
        for n in node_map.values()
    ]

    # 运行社区检测
    assignments, communities = _detect_communities(prelim_nodes, edges)

    # 构建最终节点列表
    nodes: list[GraphNode] = []
    for n in node_map.values():
        nodes.append(GraphNode(
            id=n["id"],
            label=n["label"],
            type=n["type"],
            path=n["path"],
            link_count=link_counts.get(n["id"], 0),
            community=assignments.get(n["id"], 0),
            project_sources=n.get("sources", []),
        ))

    return {
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
        "communities": [c.to_dict() for c in communities],
        "sourceToName": source_to_name,
    }
