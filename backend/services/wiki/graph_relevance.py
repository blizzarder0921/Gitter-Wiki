import os
import re
import math
from dataclasses import dataclass, field

from backend.services.wiki.frontmatter import parse_frontmatter, parse_frontmatter_array

WIKILINK_REGEX = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")

WEIGHTS = {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "common_neighbor": 1.5,
    "type_affinity": 1.0,
}

TYPE_AFFINITY = {
    "entity": {"concept": 1.2, "entity": 0.8, "source": 1.0, "synthesis": 1.0, "query": 0.8},
    "concept": {"entity": 1.2, "concept": 0.8, "source": 1.0, "synthesis": 1.2, "query": 1.0},
    "source": {"entity": 1.0, "concept": 1.0, "source": 0.5, "query": 0.8, "synthesis": 1.0},
    "query": {"concept": 1.0, "entity": 0.8, "synthesis": 1.0, "source": 0.8, "query": 0.5},
    "synthesis": {"concept": 1.2, "entity": 1.0, "source": 1.0, "query": 1.0, "synthesis": 0.8},
}

_cached_graph: "RetrievalGraph | None" = None


@dataclass
class RetrievalNode:
    id: str
    title: str
    type: str
    path: str
    sources: list[str] = field(default_factory=list)
    out_links: set[str] = field(default_factory=set)
    in_links: set[str] = field(default_factory=set)


@dataclass
class RetrievalGraph:
    nodes: dict[str, RetrievalNode] = field(default_factory=dict)
    data_version: int = 0


def _flatten_md_files(wiki_root: str) -> list[str]:
    result = []
    for dirpath, _, filenames in os.walk(wiki_root):
        for fname in filenames:
            if fname.endswith(".md"):
                result.append(os.path.join(dirpath, fname))
    return result


def _file_name_to_id(file_name: str) -> str:
    return re.sub(r"\.md$", "", file_name)


def _extract_frontmatter(content: str) -> dict:
    fm_result = parse_frontmatter(content)
    fm = fm_result.frontmatter or {}

    title = ""
    if "title" in fm and fm["title"]:
        title = fm["title"] if isinstance(fm["title"], str) else str(fm["title"])
    if not title:
        heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = heading_match.group(1).strip() if heading_match else ""

    node_type = "other"
    if "type" in fm and fm["type"]:
        raw_type = fm["type"] if isinstance(fm["type"], str) else str(fm["type"])
        node_type = raw_type.strip().lower()

    sources = parse_frontmatter_array(content, "sources")

    return {"title": title, "type": node_type, "sources": sources}


def _extract_wikilinks(content: str) -> list[str]:
    links = []
    for match in WIKILINK_REGEX.finditer(content):
        links.append(match.group(1).strip())
    return links


def _resolve_target(raw: str, node_ids: set[str]) -> str | None:
    if raw in node_ids:
        return raw
    normalized = raw.lower().replace(" ", "-")
    for nid in node_ids:
        nid_lower = nid.lower()
        if nid_lower == normalized:
            return nid
        if nid_lower == raw.lower():
            return nid
        if nid_lower.replace(" ", "-") == normalized:
            return nid
    return None


def _get_neighbors(node: RetrievalNode) -> set[str]:
    neighbors = set()
    neighbors.update(node.out_links)
    neighbors.update(node.in_links)
    return neighbors


def _get_node_degree(node: RetrievalNode) -> int:
    return len(node.out_links) + len(node.in_links)


def build_retrieval_graph(project_path: str, data_version: int = 0) -> RetrievalGraph:
    global _cached_graph

    if _cached_graph is not None and _cached_graph.data_version == data_version:
        return _cached_graph

    wiki_root = os.path.join(os.path.normpath(project_path), "wiki")
    if not os.path.isdir(wiki_root):
        empty_graph = RetrievalGraph(nodes={}, data_version=data_version)
        _cached_graph = empty_graph
        return empty_graph

    md_files = _flatten_md_files(wiki_root)

    raw_nodes = []
    for fpath in md_files:
        fname = os.path.basename(fpath)
        node_id = _file_name_to_id(fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        fm = _extract_frontmatter(content)
        raw_nodes.append({
            "id": node_id,
            "title": fm["title"] or _file_name_to_id(fname).replace("-", " "),
            "type": fm["type"],
            "path": fpath,
            "sources": fm["sources"],
            "raw_links": _extract_wikilinks(content),
            "file_name": fname,
        })

    node_ids = {n["id"] for n in raw_nodes}

    out_links_map: dict[str, set[str]] = {nid: set() for nid in node_ids}
    in_links_map: dict[str, set[str]] = {nid: set() for nid in node_ids}

    for raw in raw_nodes:
        for link_target in raw["raw_links"]:
            resolved_id = _resolve_target(link_target, node_ids)
            if resolved_id is None or resolved_id == raw["id"]:
                continue
            out_links_map[raw["id"]].add(resolved_id)
            in_links_map[resolved_id].add(raw["id"])

    nodes: dict[str, RetrievalNode] = {}
    for raw in raw_nodes:
        nodes[raw["id"]] = RetrievalNode(
            id=raw["id"],
            title=raw["title"],
            type=raw["type"],
            path=raw["path"],
            sources=list(raw["sources"]),
            out_links=out_links_map.get(raw["id"], set()),
            in_links=in_links_map.get(raw["id"], set()),
        )

    graph = RetrievalGraph(nodes=nodes, data_version=data_version)
    _cached_graph = graph
    return graph


def calculate_relevance(node_a: RetrievalNode, node_b: RetrievalNode, graph: RetrievalGraph) -> float:
    if node_a.id == node_b.id:
        return 0

    forward_links = 1 if node_b.id in node_a.out_links else 0
    backward_links = 1 if node_a.id in node_b.out_links else 0
    direct_link_score = (forward_links + backward_links) * WEIGHTS["direct_link"]

    sources_a = set(node_a.sources)
    shared_source_count = sum(1 for src in node_b.sources if src in sources_a)
    source_overlap_score = shared_source_count * WEIGHTS["source_overlap"]

    neighbors_a = _get_neighbors(node_a)
    neighbors_b = _get_neighbors(node_b)
    adamic_adar = 0.0
    for neighbor_id in neighbors_a:
        if neighbor_id in neighbors_b:
            neighbor = graph.nodes.get(neighbor_id)
            if neighbor:
                degree = _get_node_degree(neighbor)
                adamic_adar += 1 / math.log(max(degree, 2))
    common_neighbor_score = adamic_adar * WEIGHTS["common_neighbor"]

    affinity_map = TYPE_AFFINITY.get(node_a.type)
    type_affinity_score = (affinity_map.get(node_b.type, 0.5) if affinity_map else 0.5) * WEIGHTS["type_affinity"]

    return direct_link_score + source_overlap_score + common_neighbor_score + type_affinity_score


def get_related_nodes(node_id: str, graph: RetrievalGraph, limit: int = 5) -> list[tuple[RetrievalNode, float]]:
    source_node = graph.nodes.get(node_id)
    if not source_node:
        return []

    scored: list[tuple[RetrievalNode, float]] = []
    for nid, node in graph.nodes.items():
        if nid == node_id:
            continue
        relevance = calculate_relevance(source_node, node, graph)
        if relevance > 0:
            scored.append((node, relevance))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def clear_graph_cache() -> None:
    global _cached_graph
    _cached_graph = None
