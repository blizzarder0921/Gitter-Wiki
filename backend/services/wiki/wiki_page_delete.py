"""
Wiki 页面级联删除模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/wiki-page-delete.ts 移植。
当 Wiki 页面从磁盘删除时，需要同步清理：
  - 向量索引中的嵌入分块（防止幽灵搜索命中）
  - index.md 中的引用条目
  - 其他页面中的 [[xxx]] wikilink
  - 其他页面 frontmatter 中 related 字段的引用
  - source 页面对应的 wiki/media/<slug>/ 目录

核心函数：
  - is_source_page: 判断是否为 wiki/sources/ 下的页面
  - cascade_delete_wiki_page: 单页面级联删除（含引用清理）
"""

import logging
import os
import shutil

from backend.services.wiki.embedding import remove_page_embedding
from backend.services.wiki.wiki_cleanup import (
    build_deleted_keys,
    clean_index_listing,
    extract_frontmatter_title,
    normalize_wiki_ref_key,
    strip_deleted_wikilinks,
)
from backend.services.wiki.sources_merge import (
    parse_frontmatter_array,
    write_frontmatter_array,
)

logger = logging.getLogger(__name__)


def is_source_page(page_path: str) -> bool:
    """判断页面路径是否属于 wiki/sources/ 目录

    wiki/sources/ 下的页面被视为"源摘要页面"，每个源摘要拥有
    对应的 wiki/media/<slug>/ 图片目录。删除源摘要时需要额外
    清理该目录，而其他 wiki 路径（concepts、entities、queries 等）
    不拥有图片目录，因此媒体级联仅限于 source 页面。

    兼容 Windows 反斜杠和 Unix 正斜杠。

    Args:
        page_path: 页面文件路径（绝对或相对均可）
    Returns:
        True 表示该路径在 wiki/sources/ 下
    """
    # 统一路径分隔符为正斜杠，便于跨平台匹配
    normalized = page_path.replace("\\", "/")
    return "/wiki/sources/" in normalized


def _get_file_stem(page_path: str) -> str:
    """提取文件名主干（去掉目录和 .md 后缀）

    等价于 TypeScript 版的 getFileStem。
    例如 "wiki/sources/my-doc.md" → "my-doc"

    Args:
        page_path: 文件路径
    Returns:
        文件名主干；无扩展名时返回完整文件名
    """
    basename = os.path.basename(page_path)
    # 优先去掉 .md 后缀（wiki 页面的标准扩展名）
    if basename.lower().endswith(".md"):
        return basename[:-3]
    # 无 .md 后缀时，尝试去掉任意扩展名
    stem, _ = os.path.splitext(basename)
    return stem


def _flatten_md_files(wiki_dir: str) -> list[str]:
    """递归收集 wiki 目录下所有 .md 文件的绝对路径

    跳过隐藏目录（以 . 开头），与 TypeScript 版的 flattenMd 行为一致。

    Args:
        wiki_dir: wiki 根目录的绝对路径
    Returns:
        .md 文件绝对路径列表
    """
    md_files: list[str] = []
    for root, dirs, files in os.walk(wiki_dir):
        # 跳过隐藏目录（如 .git），避免遍历无关内容
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md"):
                md_files.append(os.path.join(root, fname))
    return md_files


def cascade_delete_wiki_page(project_path: str, page_path: str) -> None:
    """级联删除 Wiki 页面及其所有关联数据

    执行以下清理步骤：
      1. 读取页面内容，提取标题（用于 index.md 和 wikilink 匹配）
      2. 删除文件本身
      3. 移除对应的向量索引（remove_page_embedding）
      4. 清理 index.md 中的引用条目（clean_index_listing）
      5. 清理其他页面中的 [[xxx]] wikilink（strip_deleted_wikilinks）
      6. 清理其他页面 frontmatter 中 related 字段的引用
      7. 如果是 source 页面，额外清理 wiki/media/<slug>/ 目录

    步骤 4-6 遍历所有存活的 wiki .md 文件，单文件读取失败不会中断
    整体清理流程（尽力而为策略）。

    Args:
        project_path: 项目根目录的绝对路径
        page_path: 待删除页面的绝对路径
    """
    slug = _get_file_stem(page_path)

    # ---- 步骤 1：读取页面内容，提取标题 ----
    # 标题用于构建 deleted_keys，确保 index.md 中的标题形式引用
    # 也能被正确匹配和清理
    title = ""
    try:
        with open(page_path, "r", encoding="utf-8") as f:
            content = f.read()
        title = extract_frontmatter_title(content)
    except Exception:
        # 文件可能已被删除或无法读取，仅用 slug 形式做匹配
        pass

    # 构建已删除页面的键集合（slug 形式 + title 形式）
    infos: list[dict] = []
    if slug:
        infos.append({"slug": slug, "title": title})
    deleted_keys = build_deleted_keys(infos)

    # ---- 步骤 2：删除文件本身 ----
    if os.path.isdir(page_path):
        shutil.rmtree(page_path)
    elif os.path.isfile(page_path):
        os.unlink(page_path)

    # ---- 步骤 3：移除向量索引 ----
    # 删除嵌入分块，防止孤立分块污染后续搜索结果
    if slug:
        try:
            remove_page_embedding(project_path, slug)
        except Exception:
            # 非关键操作，失败不影响主流程
            pass

    # ---- 步骤 4-6：清理其他页面中的引用 ----
    if not deleted_keys:
        return

    wiki_dir = os.path.join(project_path, "wiki")
    if not os.path.isdir(wiki_dir):
        return

    # 收集所有存活的 .md 文件
    all_md = _flatten_md_files(wiki_dir)
    index_abs = os.path.join(wiki_dir, "index.md")

    for md_path in all_md:
        # 跳过已删除的文件本身（文件已在上一步删除，
        # 但 os.walk 可能在删除前已缓存路径）
        if os.path.normpath(md_path) == os.path.normpath(page_path):
            continue

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                file_content = f.read()
        except Exception:
            # 单文件读取失败不中断整体清理
            continue

        updated = file_content

        # 步骤 4：清理 index.md 中的引用条目
        # index.md 的列表条目形如 "- [[page-slug]]" 或 "- [[page-slug|别名]]"
        if os.path.normpath(md_path) == os.path.normpath(index_abs):
            updated = clean_index_listing(updated, deleted_keys)

        # 步骤 5：清理 [[xxx]] wikilink
        # 将指向已删除页面的 wikilink 替换为纯文本
        updated = strip_deleted_wikilinks(updated, deleted_keys)

        # 步骤 6：清理 frontmatter 中 related 字段的引用
        # 过滤掉 related 数组中指向已删除页面的条目
        related = parse_frontmatter_array(updated, "related")
        if related:
            filtered = [
                s for s in related
                if normalize_wiki_ref_key(s) not in deleted_keys
            ]
            if len(filtered) != len(related):
                updated = write_frontmatter_array(updated, "related", filtered)

        # 仅在内容有变化时写回，避免不必要的磁盘写入
        if updated != file_content:
            try:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(updated)
            except Exception as err:
                logger.warning(
                    "[wiki-delete] 重写文件失败 %s: %s", md_path, err
                )

    # ---- 步骤 7：source 页面额外清理媒体目录 ----
    # 防御性检查：slug 非空且不以 . 开头，避免误删
    # wiki/media/. 等隐藏目录（最坏情况下 slug == "."
    # 会指向 wiki/media/. 即整个 media 根目录）
    if is_source_page(page_path) and slug and not slug.startswith("."):
        media_dir = os.path.join(project_path, "wiki", "media", slug)
        if os.path.isdir(media_dir):
            try:
                shutil.rmtree(media_dir)
            except Exception:
                # 媒体目录删除失败不影响主流程，仅记录警告
                logger.warning(
                    "[wiki-delete] 清理媒体目录失败 %s", media_dir
                )
