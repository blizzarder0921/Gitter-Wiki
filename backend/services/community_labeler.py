"""
知识图谱社区标签生成服务

使用系统配置的 LLM 模型为知识图谱社区生成语义标签。
当 LLM 不可用时，由 graphify 内置的自动描述性标签兜底。

流程：
1. 读取 graph.json 中的社区信息
2. 为每个社区收集代表性节点（度数最高的前 N 个）
3. 批量调用 LLM 生成简短的功能描述标签
4. 写入 .graphify_labels.json
5. 重新生成 graph.html
"""

import os
import re
import json
from collections import Counter

from backend.services.capability_generator import _get_llm_config_from_settings


def generate_community_labels(graphify_out_dir: str, llm_config: dict | None = None) -> bool:
    """使用 LLM 为知识图谱社区生成语义标签

    读取 graph.json 中的社区信息，收集每个社区的代表性节点，
    批量调用 LLM 生成简短的功能描述标签，写入 .graphify_labels.json，
    然后重新生成 graph.html。

    当 llm_config 为 None 时，自动从系统设置中读取 LLM 配置。

    Args:
        graphify_out_dir: graphify 输出目录路径（包含 graph.json）
        llm_config: LLM 配置字典，包含 provider/model/apiKey/baseUrl；
                    为 None 时自动从系统设置读取
    Returns:
        是否成功生成标签
    """
    import httpx

    if llm_config is None:
        llm_config = _get_llm_config_from_settings()

    graph_json_path = os.path.join(graphify_out_dir, "graph.json")
    if not os.path.exists(graph_json_path):
        print("[Labels] graph.json 不存在，跳过标签生成")
        return False

    # 读取图谱数据
    try:
        with open(graph_json_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
    except Exception as e:
        print(f"[Labels] 读取 graph.json 失败: {e}")
        return False

    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", graph_data.get("edges", []))
    if not nodes:
        print("[Labels] graph.json 中无节点，跳过标签生成")
        return False

    # 按社区分组节点
    communities: dict[int, list[dict]] = {}
    for node in nodes:
        cid = node.get("community")
        if cid is not None:
            communities.setdefault(cid, []).append(node)

    if not communities:
        print("[Labels] 无社区信息，跳过标签生成")
        return False

    # 检查是否已有 LLM 标签
    labels_path = os.path.join(graphify_out_dir, ".graphify_labels.json")
    existing_labels = _load_existing_labels(labels_path)

    # 计算每个节点的度数
    node_degree = _compute_node_degree(links)

    # 为每个社区收集摘要信息（度数最高的前 5 个节点）
    community_summaries: dict[int, str] = {}
    for cid, members in communities.items():
        if cid in existing_labels:
            continue
        sorted_members = sorted(
            members,
            key=lambda n: node_degree.get(n.get("id", ""), 0),
            reverse=True,
        )
        top_members = sorted_members[:5]
        summary_parts = []
        for m in top_members:
            label = m.get("label", "")
            sf = m.get("source_file", "")
            ft = m.get("file_type", "")
            deg = node_degree.get(m.get("id", ""), 0)
            summary_parts.append(f"- {label} (file: {sf}, type: {ft}, degree: {deg})")
        community_summaries[cid] = "\n".join(summary_parts)

    if not community_summaries:
        print("[Labels] 所有社区已有标签，跳过 LLM 调用")
        return True

    # 准备 LLM 调用
    api_key = llm_config.get("apiKey", "")
    base_url = llm_config.get("baseUrl", "")
    model = llm_config.get("model", "")

    if not api_key or not base_url:
        print("[Labels] LLM API Key 或 Base URL 未配置，跳过标签生成")
        return False

    # 确保 base_url 以 /chat/completions 结尾
    chat_url = base_url.rstrip("/")
    if not chat_url.endswith("/chat/completions"):
        chat_url += "/chat/completions"

    # 批量调用 LLM（每批最多 30 个社区）
    new_labels = _batch_label_communities(
        community_summaries, chat_url, api_key, model
    )

    if not new_labels:
        print("[Labels] 未生成任何标签")
        return False

    # 合并已有标签和新标签
    all_labels = {**existing_labels, **new_labels}

    # 写入 .graphify_labels.json
    if not _save_labels(labels_path, all_labels):
        return False

    # 重新生成 graph.html（使用新标签）
    try:
        _regenerate_graph_html(graphify_out_dir, all_labels)
    except Exception as e:
        print(f"[Labels] 重新生成 graph.html 失败: {e}")
        return False

    return True


def _load_existing_labels(labels_path: str) -> dict[int, str]:
    """从 .graphify_labels.json 加载已有标签，过滤占位标签

    Args:
        labels_path: 标签文件路径
    Returns:
        已有标签字典 {community_id: label}，过滤掉 "Community X" 占位标签
    """
    if not os.path.exists(labels_path):
        return {}
    try:
        with open(labels_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        labels = {int(k): v for k, v in raw.items()}
        placeholder_pattern = re.compile(r"^Community \d+$")
        return {k: v for k, v in labels.items() if not placeholder_pattern.match(v)}
    except Exception:
        return {}


def _compute_node_degree(links: list[dict]) -> dict[str, int]:
    """计算每个节点的度数（入度+出度之和）

    Args:
        links: 边列表，每条边包含 source 和 target 字段
    Returns:
        节点度数字典 {node_id: degree}
    """
    node_degree: dict[str, int] = Counter()
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        node_degree[src] = node_degree.get(src, 0) + 1
        node_degree[tgt] = node_degree.get(tgt, 0) + 1
    return dict(node_degree)


def _batch_label_communities(
    community_summaries: dict[int, str],
    chat_url: str,
    api_key: str,
    model: str,
    batch_size: int = 30,
) -> dict[int, str]:
    """批量调用 LLM 为社区生成语义标签

    将社区按批次分组，每批最多 batch_size 个社区，
    调用 LLM 生成简短的功能描述标签。

    Args:
        community_summaries: 社区摘要字典 {community_id: summary_text}
        chat_url: LLM API 的 chat/completions 端点 URL
        api_key: LLM API Key
        model: 模型名称
        batch_size: 每批社区数量，默认 30
    Returns:
        新生成的标签字典 {community_id: label}
    """
    import httpx

    cids = list(community_summaries.keys())
    new_labels: dict[int, str] = {}

    for batch_start in range(0, len(cids), batch_size):
        batch_cids = cids[batch_start:batch_start + batch_size]
        communities_text = ""
        for cid in batch_cids:
            communities_text += f"\nCommunity {cid}:\n{community_summaries[cid]}\n"

        system_prompt = (
            "你是一个代码分析专家。根据每个社区中的代表性代码节点信息，"
            "为每个社区生成一个简短的功能描述标签（2-6个词，中文或英文均可）。"
            "标签应概括社区的核心功能，如'注意力机制'、'数据预处理'、'训练循环'等。"
            "输出严格的 JSON 格式：{\"labels\": {\"社区ID\": \"标签\", ...}}"
        )
        user_prompt = f"请为以下代码社区生成功能描述标签：\n{communities_text}"

        try:
            resp = httpx.post(
                chat_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            resp_data = resp.json()
            content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # 解析 LLM 返回的 JSON（兼容 markdown 代码块包裹）
            content = _strip_markdown_fences(content)
            parsed = json.loads(content.strip())
            labels_dict = parsed.get("labels", {})
            for k, v in labels_dict.items():
                try:
                    cid = int(k)
                    if cid in community_summaries and isinstance(v, str) and v.strip():
                        new_labels[cid] = v.strip()
                except (ValueError, TypeError):
                    continue

            print(f"[Labels] 批次 {batch_start // batch_size + 1}: 生成 {len(labels_dict)} 个标签")

        except Exception as e:
            print(f"[Labels] LLM 调用失败（批次 {batch_start // batch_size + 1}）: {e}")
            continue

    return new_labels


def _strip_markdown_fences(content: str) -> str:
    """去除 LLM 返回内容中的 markdown 代码块包裹

    LLM 有时会用 ```json ... ``` 包裹 JSON 输出，
    此函数将其剥离以便正确解析。

    Args:
        content: LLM 返回的原始文本
    Returns:
        去除代码块包裹后的文本
    """
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.rsplit("```", 1)[0]
    return content


def _save_labels(labels_path: str, labels: dict[int, str]) -> bool:
    """将社区标签写入 .graphify_labels.json

    Args:
        labels_path: 标签文件路径
        labels: 标签字典 {community_id: label}
    Returns:
        是否写入成功
    """
    try:
        with open(labels_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in labels.items()}, f, ensure_ascii=False, indent=2)
        print(f"[Labels] 写入 {len(labels)} 个标签到 {labels_path}")
        return True
    except Exception as e:
        print(f"[Labels] 写入标签文件失败: {e}")
        return False


def _regenerate_graph_html(graphify_out_dir: str, labels: dict[int, str]) -> None:
    """使用新标签重新生成 graph.html

    读取 graph.json，重建图谱，应用社区标签，重新生成 HTML 可视化。
    注意：graphify 内部使用绝对导入（如 from graphify.xxx），
    需要确保 backend 目录在 sys.path 中。

    Args:
        graphify_out_dir: graphify 输出目录路径
        labels: 社区标签字典 {community_id: label_string}
    """
    import sys
    # graphify 内部使用 from graphify.xxx 绝对导入，
    # 需要确保 backend 目录在 sys.path 中
    _backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
    if _backend_dir not in sys.path:
        sys.path.insert(0, _backend_dir)

    from backend.graphify.build import build_from_json
    from backend.graphify.cluster import cluster
    from backend.graphify.export import to_html, _viz_node_limit

    graph_json_path = os.path.join(graphify_out_dir, "graph.json")
    with open(graph_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    G = build_from_json(data)
    communities = cluster(G)

    html_path = os.path.join(graphify_out_dir, "graph.html")
    to_html(G, communities, html_path, community_labels=labels, node_limit=_viz_node_limit())
    print(f"[Labels] graph.html 已重新生成: {html_path}")
