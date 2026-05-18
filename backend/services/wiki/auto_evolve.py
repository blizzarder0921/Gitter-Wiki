"""
Wiki 自动进化引擎模块

实现 Wiki 知识库的三层自动进化流程：
- L1 事件驱动：Git 变更感知 → 增量摄入 / 级联清理
- L2 结构驱动：图谱洞察 → 知识空白 + 社区检测
- L3 语义驱动：概念过时检测 + 跨项目关联

核心函数：
- detect_git_changes: 检测 Git 变更文件（分类：新增/修改/删除）
- trigger_incremental_ingest: 触发增量摄入
- trigger_cascade_cleanup: 对已删除文件触发级联清理
- schedule_lint_scan: 执行 Lint 扫描并生成审核项
- run_auto_evolve: 自动进化主入口（三层引擎）
"""

import logging
import os
import subprocess
from typing import Any

from backend.services.wiki.ingest import auto_ingest
from backend.services.wiki.lint import run_structural_lint, run_semantic_lint

logger = logging.getLogger(__name__)


def detect_git_changes(project_path: str) -> dict[str, list[str]]:
    """检测 Git 变更文件并分类为新增/修改/删除

    同时检测两类变更：
    1. 最近一次提交的变更：git diff --name-only HEAD~1 HEAD
    2. 未提交的修改：git diff --name-only

    使用 git diff --diff-filter 区分文件状态：
    - A (Added): 新增文件
    - M (Modified): 修改文件
    - D (Deleted): 删除文件

    自动过滤 wiki/ 目录下自动生成的文件，
    避免对自身产物重复摄入。

    Args:
        project_path: 项目根目录路径
    Returns:
        分类结果字典：
        {
            "added": [新增文件路径列表],
            "modified": [修改文件路径列表],
            "deleted": [删除文件路径列表]
        }
    """
    added: set[str] = set()
    modified: set[str] = set()
    deleted: set[str] = set()

    # 检测最近一次提交的变更（带状态标记）
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", "HEAD~1", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                status, filepath = parts[0], parts[1]
                # 跳过 wiki 目录下自动生成的文件
                if filepath.startswith("wiki/"):
                    continue
                if status == "A":
                    added.add(filepath)
                elif status == "M":
                    modified.add(filepath)
                elif status == "D":
                    deleted.add(filepath)
                elif status.startswith("R"):
                    # 重命名：R100\told\tnew 格式
                    renames = filepath.split("\t")
                    if len(renames) >= 2:
                        deleted.add(renames[0])
                        added.add(renames[1])
    except Exception as err:
        logger.warning("[auto_evolve] git diff --name-status HEAD~1 HEAD 执行失败: %s", err)

    # 检测未提交的修改（工作区变更）
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                status, filepath = parts[0], parts[1]
                if filepath.startswith("wiki/"):
                    continue
                if status == "A":
                    added.add(filepath)
                elif status == "M":
                    modified.add(filepath)
                elif status == "D":
                    deleted.add(filepath)
    except Exception as err:
        logger.warning("[auto_evolve] git diff --name-status 执行失败: %s", err)

    # 验证新增/修改文件确实存在（可能被后续操作删除）
    valid_added = sorted(f for f in added if os.path.isfile(os.path.join(project_path, f)))
    valid_modified = sorted(f for f in modified if os.path.isfile(os.path.join(project_path, f)))
    valid_deleted = sorted(deleted)

    logger.info(
        "[auto_evolve] Git 变更检测: %d 新增, %d 修改, %d 删除",
        len(valid_added),
        len(valid_modified),
        len(valid_deleted),
    )

    return {
        "added": valid_added,
        "modified": valid_modified,
        "deleted": valid_deleted,
    }


async def trigger_incremental_ingest(
    project_path: str,
    changed_files: list[str],
    llm_config: dict,
    folder_context: str = "git-auto-ingest",
) -> dict:
    """触发增量摄入

    对每个变更文件调用 auto_ingest 进行摄入处理，
    将源文件内容转化为 Wiki 知识页面。

    处理逻辑：
    - 逐文件调用 auto_ingest，单个文件失败不影响其他文件
    - 汇总所有成功写入的 Wiki 页面路径
    - 统计成功和失败的文件数

    Args:
        project_path: 项目根目录路径
        changed_files: 变更文件路径列表（相对于项目根目录）
        llm_config: LLM 配置字典，包含 provider、model、apiKey 等字段
        folder_context: 文件夹上下文提示，区分新增摄入和重新摄入
    Returns:
        {"processed": int, "failed": int, "files_written": list[str]}
    """
    processed: int = 0
    failed: int = 0
    all_written: list[str] = []

    for file_rel_path in changed_files:
        file_full_path = os.path.join(project_path, file_rel_path)

        if not os.path.isfile(file_full_path):
            logger.warning(
                "[auto_evolve] 文件不存在，跳过摄入: %s", file_rel_path
            )
            failed += 1
            continue

        try:
            written = await auto_ingest(project_path, file_full_path, llm_config)
            all_written.extend(written)
            processed += 1
            logger.info(
                "[auto_evolve] 增量摄入成功 [%s]: %s（生成 %d 个页面）",
                folder_context,
                file_rel_path,
                len(written),
            )
        except Exception as err:
            failed += 1
            logger.error(
                "[auto_evolve] 增量摄入失败 %s: %s", file_rel_path, err
            )

    return {
        "processed": processed,
        "failed": failed,
        "files_written": all_written,
    }


async def trigger_cascade_cleanup(
    project_path: str,
    deleted_files: list[str],
) -> dict:
    """对已删除的源文件触发 Wiki 页面级联清理

    当 Git 检测到源文件被删除时，需要同步清理对应的 Wiki 页面：
    - 删除 Wiki 页面文件本身
    - 清理 index.md 中的引用
    - 清理其他页面中的 [[wikilink]]
    - 清理向量索引
    - 清理 source 页面对应的 media 目录

    清理逻辑：将源文件路径映射为 Wiki 页面路径（wiki/sources/<slug>.md），
    然后调用 cascade_delete_wiki_page 执行级联删除。

    Args:
        project_path: 项目根目录路径
        deleted_files: 已删除的源文件路径列表（相对于项目根目录）
    Returns:
        {"cleaned": int, "failed": int, "details": list[str]}
    """
    if not deleted_files:
        return {"cleaned": 0, "failed": 0, "details": []}

    from backend.services.wiki.wiki_page_delete import cascade_delete_wiki_page

    cleaned: int = 0
    failed: int = 0
    details: list[str] = []

    for file_rel_path in deleted_files:
        # 将源文件路径映射为 Wiki 页面路径
        # 例如: src/utils.py → wiki/sources/src-utils.md
        file_stem = os.path.splitext(os.path.basename(file_rel_path))[0]
        # 将路径中的分隔符替换为连字符，生成 slug
        slug = file_rel_path.replace("\\", "/").replace("/", "-")
        if slug.endswith(os.path.splitext(file_rel_path)[1]):
            slug = slug[: -len(os.path.splitext(file_rel_path)[1])]
        wiki_page_path = os.path.join(project_path, "wiki", "sources", f"{slug}.md")

        if not os.path.isfile(wiki_page_path):
            logger.info(
                "[auto_evolve] 删除文件的 Wiki 页面不存在，跳过清理: %s",
                wiki_page_path,
            )
            continue

        try:
            cascade_delete_wiki_page(project_path, wiki_page_path)
            cleaned += 1
            details.append(f"已清理: {file_rel_path} → {wiki_page_path}")
            logger.info(
                "[auto_evolve] 级联清理成功: %s → %s",
                file_rel_path,
                wiki_page_path,
            )
        except Exception as err:
            failed += 1
            details.append(f"清理失败: {file_rel_path} - {err}")
            logger.error(
                "[auto_evolve] 级联清理失败 %s: %s", file_rel_path, err
            )

    return {
        "cleaned": cleaned,
        "failed": failed,
        "details": details,
    }


async def schedule_lint_scan(
    project_path: str,
    llm_config: dict,
    project_id: int | None = None,
) -> dict:
    """执行 Lint 扫描并生成审核项

    依次执行两类检查：
    1. 结构检查（run_structural_lint）：检测孤立页面、断链、无出链
    2. 语义检查（run_semantic_lint）：通过 LLM 发现矛盾、过时、缺失等问题

    将发现的问题转化为 review items，供用户审核处理。
    问题类型映射：
    - orphan -> missing-page（孤立页面需要创建入链或新页面）
    - broken-link -> broken-link（断链需要修复）
    - no-outlinks -> missing-page（无出链页面需要补充关联）
    - semantic -> suggestion（语义问题作为建议项）

    Args:
        project_path: 项目根目录路径
        llm_config: LLM 配置字典（语义检查需要 LLM 支持）
        project_id: 项目 ID（用于创建 review items，为 None 时跳过审核项创建）
    Returns:
        {"lint_issues": int, "reviews_created": int}
    """
    structural_results = await run_structural_lint(project_path)

    semantic_results: list[dict] = []
    if llm_config:
        try:
            semantic_results = await run_semantic_lint(project_path, llm_config)
        except Exception as err:
            logger.error("[auto_evolve] 语义检查失败: %s", err)

    all_issues = structural_results + semantic_results
    reviews_created: int = 0

    if project_id is not None:
        from backend.services.project_service import create_review_item

        review_type_map: dict[str, str] = {
            "orphan": "missing-page",
            "broken-link": "broken-link",
            "no-outlinks": "missing-page",
            "semantic": "suggestion",
        }

        for issue in all_issues:
            issue_type = issue.get("type", "unknown")
            review_type = review_type_map.get(issue_type, "confirm")

            try:
                create_review_item(project_id, {
                    "item_type": review_type,
                    "title": f"{issue_type}: {issue.get('page', 'unknown')}",
                    "description": issue.get("detail", ""),
                    "source_path": issue.get("page"),
                    "affected_pages": (
                        ",".join(issue.get("affectedPages", []))
                        if issue.get("affectedPages")
                        else None
                    ),
                    "options": [
                        {"label": "Create Page", "action": "Create Page"},
                        {"label": "Skip", "action": "Skip"},
                    ],
                })
                reviews_created += 1
            except Exception as err:
                logger.error(
                    "[auto_evolve] 创建审核项失败: %s", err
                )

    logger.info(
        "[auto_evolve] Lint 扫描完成: 发现 %d 个问题, 创建 %d 个审核项",
        len(all_issues),
        reviews_created,
    )

    return {
        "lint_issues": len(all_issues),
        "reviews_created": reviews_created,
    }


async def run_auto_evolve(
    project_path: str,
    llm_config: dict,
    project_id: int | None = None,
) -> dict:
    """自动进化主入口（三层引擎）

    执行完整的三层自动进化流程：
    L1 事件驱动：
      - Git 新增文件 → 自动加入摄入队列
      - Git 修改文件 → 自动重新摄入（页面合并）
      - Git 删除文件 → 自动级联清理 Wiki 页面
    L2 结构驱动：
      - 图谱知识空白 → 孤立节点 + 稀疏社区检测
      - 社区检测 → 发现新兴知识聚类（Louvain）
    L3 语义驱动：
      - 概念过时检测 → LLM 判断时效性
      - Lint 扫描 → 结构 + 语义问题 → 审核项

    Args:
        project_path: 项目根目录路径
        llm_config: LLM 配置字典
        project_id: 项目 ID（用于创建 review items，为 None 时跳过审核项创建）
    Returns:
        综合结果字典，包含：
        - git_changes: 分类变更结果（added/modified/deleted）
        - ingest: 增量摄入结果（processed, failed, files_written）
        - cleanup: 级联清理结果（cleaned, failed, details）
        - lint: Lint 扫描结果（lint_issues, reviews_created）
        - graph_insights: 图谱洞察结果（knowledge_gaps, surprising_connections）
    """
    logger.info("[auto_evolve] 开始三层自动进化，项目路径: %s", project_path)

    # ── L1 事件驱动：Git 变更检测 ──────────────────────────────
    git_changes = detect_git_changes(project_path)
    added_files = git_changes["added"]
    modified_files = git_changes["modified"]
    deleted_files = git_changes["deleted"]

    # L1-a：新增文件 → 自动摄入
    ingest_added: dict = {"processed": 0, "failed": 0, "files_written": []}
    if added_files:
        ingest_added = await trigger_incremental_ingest(
            project_path, added_files, llm_config,
            folder_context="git-auto-ingest",
        )

    # L1-b：修改文件 → 自动重新摄入（页面合并）
    ingest_modified: dict = {"processed": 0, "failed": 0, "files_written": []}
    if modified_files:
        ingest_modified = await trigger_incremental_ingest(
            project_path, modified_files, llm_config,
            folder_context="git-re-ingest",
        )

    # L1-c：删除文件 → 级联清理 Wiki 页面
    cleanup_result = await trigger_cascade_cleanup(project_path, deleted_files)

    # 合并摄入结果
    ingest_result = {
        "processed": ingest_added["processed"] + ingest_modified["processed"],
        "failed": ingest_added["failed"] + ingest_modified["failed"],
        "files_written": ingest_added["files_written"] + ingest_modified["files_written"],
    }

    # ── L2 结构驱动：图谱洞察 ──────────────────────────────────
    graph_insights: dict[str, Any] = {
        "knowledge_gaps": [],
        "surprising_connections": [],
    }
    wiki_dir = os.path.join(project_path, "wiki")
    if os.path.isdir(wiki_dir):
        try:
            from backend.services.wiki.wiki_graph import build_wiki_graph
            from backend.services.wiki.graph_insights import (
                detect_knowledge_gaps,
                find_surprising_connections,
            )

            graph_data = await build_wiki_graph(project_path)
            nodes = graph_data.get("nodes", [])
            edges = graph_data.get("edges", [])
            communities = graph_data.get("communities", [])

            if nodes:
                gaps = detect_knowledge_gaps(nodes, edges, communities)
                graph_insights["knowledge_gaps"] = gaps

                connections = find_surprising_connections(
                    nodes, edges, communities
                )
                graph_insights["surprising_connections"] = connections

                logger.info(
                    "[auto_evolve] L2 图谱洞察: %d 个知识缺口, %d 个意外连接",
                    len(gaps),
                    len(connections),
                )
        except Exception as err:
            logger.warning("[auto_evolve] L2 图谱洞察检测失败: %s", err)

    # ── L3 语义驱动：Lint 扫描 + 审核项 ────────────────────────
    lint_result = await schedule_lint_scan(
        project_path, llm_config, project_id
    )

    # 汇总结果
    result: dict[str, Any] = {
        "git_changes": git_changes,
        "ingest": ingest_result,
        "cleanup": cleanup_result,
        "lint": lint_result,
        "graph_insights": graph_insights,
    }

    logger.info(
        "[auto_evolve] 三层自动进化完成: "
        "L1[%d 新增, %d 修改, %d 删除, %d 摄入成功, %d 清理] "
        "L2[%d 缺口, %d 意外连接] "
        "L3[%d Lint问题]",
        len(added_files),
        len(modified_files),
        len(deleted_files),
        ingest_result["processed"],
        cleanup_result["cleaned"],
        len(graph_insights["knowledge_gaps"]),
        len(graph_insights["surprising_connections"]),
        lint_result["lint_issues"],
    )

    return result
