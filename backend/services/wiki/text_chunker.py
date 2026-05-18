"""
Markdown 文本分块模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/text-chunker.ts 移植。
提供 Markdown 感知的递归文本分块，用于嵌入管线。

设计约束：
1. 每个分块携带 headingPath 面包屑，保留结构上下文
2. 分块优先级：标题段落 > 段落边界 > 换行 > 句子终止符 > 空白 > 硬切分
3. 不在代码围栏内切分
4. 不在表格内切分
5. 剥离 YAML frontmatter 后再分块
6. 相邻分块间应用重叠
7. 合并过小的分块
8. 纯函数、确定性：相同输入产生相同输出
"""

import re
from dataclasses import dataclass, field


@dataclass
class ChunkingOptions:
    """分块选项

    Attributes:
        target_chars: 目标分块字符数
        max_chars: 硬上限，超过此大小的原子块仍会输出但标记为 oversized
        min_chars: 小于此大小的分块会合并到下一个兄弟
        overlap_chars: 相邻分块间的重叠字符数
    """
    target_chars: int = 1000
    max_chars: int = 1500
    min_chars: int = 200
    overlap_chars: int = 200


@dataclass
class Chunk:
    """一个文档分块

    Attributes:
        index: 0-based 发射顺序
        text: 分块可见内容（无 frontmatter、无标题前缀）
        heading_path: 标题面包屑，如 "## Techniques > ### Flash Attention"
        char_start: 在原始输入中的字符偏移（含 frontmatter）
        char_end: 在原始输入中的字符偏移（不含）
        oversized: 是否超过 max_chars（因为不可分割的原子单元）
    """
    index: int
    text: str
    heading_path: str
    char_start: int
    char_end: int
    oversized: bool = False


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def chunk_markdown(
    content: str,
    target_chars: int | None = None,
    max_chars: int | None = None,
    min_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[Chunk]:
    """将 Markdown 文档分块为嵌入大小的片段

    完整合约见模块级文档字符串。

    Args:
        content: Markdown 文档完整内容
        target_chars: 目标分块字符数（默认 1000）
        max_chars: 硬上限字符数（默认 1500）
        min_chars: 最小分块字符数（默认 200）
        overlap_chars: 重叠字符数（默认 200）
    Returns:
        Chunk 列表
    """
    opts = ChunkingOptions(
        target_chars=target_chars or 1000,
        max_chars=max_chars or 1500,
        min_chars=min_chars or 200,
        overlap_chars=overlap_chars or 200,
    )

    # 防御性检查
    if opts.max_chars < opts.target_chars:
        opts.max_chars = opts.target_chars
    if opts.overlap_chars >= opts.target_chars:
        opts.overlap_chars = opts.target_chars // 2

    # 剥离 frontmatter
    body, body_offset = _strip_frontmatter(content)
    if not body.strip():
        return []

    # 按标题分段
    sections = _split_into_sections(body, body_offset)

    # 对每个段落分块
    chunks: list[Chunk] = []
    running_index = 0
    for section in sections:
        section_chunks = _chunk_section(section, opts)
        for c in section_chunks:
            c.index = running_index
            chunks.append(c)
            running_index += 1

    return chunks


# ---------------------------------------------------------------------------
# Frontmatter 处理
# ---------------------------------------------------------------------------

def _strip_frontmatter(content: str) -> tuple[str, int]:
    """剥离 YAML frontmatter 块，返回正文和偏移量

    Args:
        content: 文件内容
    Returns:
        (正文, 正文在原始内容中的起始偏移)
    """
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return content, 0

    # 查找闭合 ---
    rest = content[4:]  # 跳过首行 ---\n
    close_match = re.search(r"(^|\n)---\s*(\n|$)", rest)
    if not close_match:
        return content, 0

    after_match = re.match(r"(\n)?---\s*\n?", rest[close_match.start():])
    if not after_match:
        return content, 0

    body_offset = 4 + close_match.start() + after_match.end()
    return content[body_offset:], body_offset


# ---------------------------------------------------------------------------
# 段落分割
# ---------------------------------------------------------------------------

@dataclass
class _Section:
    """一个标题段落"""
    text: str
    body_start: int
    heading_path: str


def _split_into_sections(body: str, body_offset: int) -> list[_Section]:
    """按标题将正文分割为段落

    跟踪当前标题路径，遇到新标题时切割段落。
    代码围栏内的标题不会触发切割。

    Args:
        body: 剥离 frontmatter 后的正文
        body_offset: 正文在原始文件中的偏移
    Returns:
        _Section 列表
    """
    lines = body.split("\n")
    sections: list[_Section] = []

    # 标题栈：headings[level] = 最近该级别的标题文本
    headings: dict[int, str] = {}

    current_lines: list[str] = []
    current_start = body_offset
    current_heading = ""
    in_fence = False
    fence_marker = ""
    char_cursor = body_offset

    def _flush():
        """将当前段落刷入 sections"""
        text = "\n".join(current_lines)
        if text.strip():
            sections.append(_Section(
                text=text,
                body_start=current_start,
                heading_path=current_heading,
            ))

    for i, line in enumerate(lines):
        line_len = len(line) + (1 if i < len(lines) - 1 else 0)

        # 代码围栏状态跟踪
        fence_match = re.match(r"^(`{3,}|~{3,})", line)
        if fence_match:
            if not in_fence:
                in_fence = True
                fence_marker = fence_match.group(1)[0] * len(fence_match.group(1))
            elif line.startswith(fence_marker) and line.strip() == fence_marker:
                in_fence = False
            current_lines.append(line)
            char_cursor += line_len
            continue

        # 标题检测（仅在围栏外）
        h_match = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if h_match:
            _flush()
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            headings[level] = title
            # 清除更深层级
            for lvl in range(level + 1, 7):
                headings.pop(lvl, None)

            path_parts = []
            for lvl in range(1, 7):
                if lvl in headings:
                    path_parts.append(f"{'#' * lvl} {headings[lvl]}")

            current_lines = [line]
            current_start = char_cursor
            current_heading = " > ".join(path_parts)
            char_cursor += line_len
            continue

        current_lines.append(line)
        char_cursor += line_len

    _flush()
    return sections


# ---------------------------------------------------------------------------
# 段落 → 分块
# ---------------------------------------------------------------------------

@dataclass
class _Atom:
    """不可分割的文本原子"""
    text: str
    offset: int
    indivisible: bool
    kind: str  # "code" | "table" | "paragraph" | "blank"


@dataclass
class _Piece:
    """分块片段"""
    text: str
    offset: int


def _chunk_section(section: _Section, opts: ChunkingOptions) -> list[Chunk]:
    """将一个段落分块

    Args:
        section: 段落数据
        opts: 分块选项
    Returns:
        Chunk 列表（index 待外部赋值）
    """
    text = section.text
    body_start = section.body_start
    heading_path = section.heading_path

    if len(text) <= opts.target_chars:
        return [Chunk(
            index=0,
            text=text,
            heading_path=heading_path,
            char_start=body_start,
            char_end=body_start + len(text),
            oversized=False,
        )]

    # 分解为原子 → 片段 → 分块 → 合并 → 重叠
    atoms = _tokenize_atoms(text)
    pieces = _split_atoms_to_pieces(atoms, opts)
    sized = _size_pieces(pieces, opts)
    merged = _merge_small(sized, opts)
    with_overlap = _apply_overlap(merged, opts)

    out: list[Chunk] = []
    for piece in with_overlap:
        out.append(Chunk(
            index=0,
            text=piece.text,
            heading_path=heading_path,
            char_start=body_start + piece.offset,
            char_end=body_start + piece.offset + len(piece.text),
            oversized=len(piece.text) > opts.max_chars,
        ))
    return out


# ---------------------------------------------------------------------------
# 原子标记化
# ---------------------------------------------------------------------------

def _tokenize_atoms(text: str) -> list[_Atom]:
    """将文本分解为原子单元（可分割 vs 不可分割）

    代码块和表格为不可分割原子，段落为可分割原子。

    Args:
        text: 段落文本
    Returns:
        _Atom 列表
    """
    atoms: list[_Atom] = []
    lines = text.split("\n")

    cursor = 0
    i = 0
    while i < len(lines):
        line = lines[i]

        # 代码围栏
        fence_match = re.match(r"^(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)
            start = cursor
            body_lines = [line]
            j = i + 1
            cursor += len(line) + 1
            while j < len(lines):
                body_lines.append(lines[j])
                cursor += len(lines[j]) + 1
                if lines[j].startswith(marker) and lines[j].strip() == marker:
                    j += 1
                    break
                j += 1
            content = "\n".join(body_lines)
            atoms.append(_Atom(text=content, offset=start, indivisible=True, kind="code"))
            i = j
            continue

        # 表格：连续以 | 开头的行
        if line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            if j - i >= 2:
                start = cursor
                body_lines = lines[i:j]
                content = "\n".join(body_lines)
                cursor += len(content) + (1 if j < len(lines) else 0)
                atoms.append(_Atom(text=content, offset=start, indivisible=True, kind="table"))
                i = j
                continue

        # 空行
        if line.strip() == "":
            cursor += len(line) + 1
            i += 1
            continue

        # 普通段落：累积连续非空、非特殊行
        start = cursor
        body_lines = []
        while (
            i < len(lines)
            and lines[i].strip() != ""
            and not lines[i].startswith("|")
            and not re.match(r"^(`{3,}|~{3,})", lines[i])
        ):
            body_lines.append(lines[i])
            cursor += len(lines[i]) + 1
            i += 1
        content = "\n".join(body_lines)
        if content.strip():
            atoms.append(_Atom(text=content, offset=start, indivisible=False, kind="paragraph"))

    return atoms


# ---------------------------------------------------------------------------
# 可分割原子 → 片段
# ---------------------------------------------------------------------------

def _split_atoms_to_pieces(atoms: list[_Atom], opts: ChunkingOptions) -> list[_Piece]:
    """将每个可分割原子分解为不超过 target_chars 的片段

    不可分割原子直接通过。

    Args:
        atoms: 原子列表
        opts: 分块选项
    Returns:
        _Piece 列表
    """
    pieces: list[_Piece] = []
    for atom in atoms:
        if atom.indivisible:
            pieces.append(_Piece(text=atom.text, offset=atom.offset))
            continue
        if atom.kind == "blank":
            continue
        if len(atom.text) <= opts.target_chars:
            pieces.append(_Piece(text=atom.text, offset=atom.offset))
            continue
        pieces.extend(_recursive_split(atom.text, atom.offset, opts.target_chars))
    return pieces


# 句子分割器列表：从粗粒度到细粒度
_SENTENCE_SPLITTERS: list[tuple[str, re.Pattern]] = [
    ("lines", re.compile(r"(\n+)")),
    ("sentences", re.compile(r"([。！？!?；;]+\s*|(?:\.\s+))")),
    ("spaces", re.compile(r"(\s+)")),
]


def _recursive_split(
    text: str, base_offset: int, target_chars: int
) -> list[_Piece]:
    """自顶向下递归分割：先尝试粗粒度分隔符，再逐步细化

    Args:
        text: 待分割文本
        base_offset: 在段落中的偏移
        target_chars: 目标字符数
    Returns:
        _Piece 列表
    """
    # 先按双换行（段落）分割
    para_pieces = _split_keeping_sep(text, re.compile(r"(\n{2,})"))
    out: list[_Piece] = []
    cursor = base_offset

    for chunk in para_pieces:
        if not chunk:
            continue
        if len(chunk) <= target_chars:
            out.append(_Piece(text=chunk, offset=cursor))
            cursor += len(chunk)
            continue

        # 段落过大，尝试更细的分隔符
        split_done = False
        for _, splitter in _SENTENCE_SPLITTERS:
            subs = _split_keeping_sep(chunk, splitter)
            if not subs:
                continue

            # 检查是否所有子片段都足够小
            if all(len(s) <= target_chars for s in subs) and len(subs) > 1:
                sub_cursor = cursor
                for s in subs:
                    if s:
                        out.append(_Piece(text=s, offset=sub_cursor))
                    sub_cursor += len(s)
                cursor += len(chunk)
                split_done = True
                break

            # 尝试只保留足够小的子片段
            any_too_big = False
            sub_cursor = cursor
            sub_out: list[_Piece] = []
            for s in subs:
                if not s:
                    continue
                if len(s) <= target_chars:
                    sub_out.append(_Piece(text=s, offset=sub_cursor))
                else:
                    any_too_big = True
                sub_cursor += len(s)

            if not any_too_big and len(subs) > 1:
                out.extend(sub_out)
                cursor += len(chunk)
                split_done = True
                break

        # 所有分隔符都无法分割，硬切分
        if not split_done:
            slice_cursor = cursor
            for si in range(0, len(chunk), target_chars):
                piece = chunk[si:si + target_chars]
                out.append(_Piece(text=piece, offset=slice_cursor))
                slice_cursor += len(piece)
            cursor += len(chunk)

    return out


def _split_keeping_sep(text: str, sep: re.Pattern) -> list[str]:
    """按正则分割文本，但保留分隔符附加到前一个片段

    Args:
        text: 待分割文本
        sep: 分隔符正则
    Returns:
        片段列表
    """
    out: list[str] = []
    last = 0
    for m in sep.finditer(text):
        end = m.end()
        out.append(text[last:end])
        last = end
    if last < len(text):
        out.append(text[last:])
    return [s for s in out if s]


# ---------------------------------------------------------------------------
# 片段打包
# ---------------------------------------------------------------------------

def _size_pieces(pieces: list[_Piece], opts: ChunkingOptions) -> list[_Piece]:
    """贪心打包：累积片段直到超过 target_chars 后发射

    Args:
        pieces: 片段列表
        opts: 分块选项
    Returns:
        打包后的片段列表
    """
    out: list[_Piece] = []
    buf = ""
    buf_offset: int | None = None

    for p in pieces:
        if not p.text:
            continue

        # 单片段超过 target_chars：先刷出缓冲区，再单独发射
        if len(p.text) > opts.target_chars:
            if buf and buf_offset is not None:
                out.append(_Piece(text=buf, offset=buf_offset))
            out.append(_Piece(text=p.text, offset=p.offset))
            buf = ""
            buf_offset = None
            continue

        # 加入后超过 target_chars：先发射缓冲区
        if buf and len(buf) + len(p.text) > opts.target_chars and buf_offset is not None:
            out.append(_Piece(text=buf, offset=buf_offset))
            buf = p.text
            buf_offset = p.offset
            continue

        # 累积
        if not buf:
            buf_offset = p.offset
        buf += p.text

    if buf and buf_offset is not None:
        out.append(_Piece(text=buf, offset=buf_offset))

    return out


# ---------------------------------------------------------------------------
# 小分块合并
# ---------------------------------------------------------------------------

def _merge_small(pieces: list[_Piece], opts: ChunkingOptions) -> list[_Piece]:
    """将过小的分块合并到下一个兄弟

    防止发射大量 30 字符的碎片。

    Args:
        pieces: 片段列表
        opts: 分块选项
    Returns:
        合并后的片段列表
    """
    if len(pieces) < 2:
        return pieces

    out: list[_Piece] = []
    for p in pieces:
        if out:
            last = out[-1]
            if (
                len(last.text) < opts.min_chars
                and len(last.text) + len(p.text) <= opts.max_chars
            ):
                out[-1] = _Piece(text=last.text + p.text, offset=last.offset)
                continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# 重叠注入
# ---------------------------------------------------------------------------

def _apply_overlap(pieces: list[_Piece], opts: ChunkingOptions) -> list[_Piece]:
    """在前一个分块尾部和当前分块头部之间注入重叠

    从前一个分块尾部取 overlap_chars 字符，对齐到句子/词边界后
    拼接到当前分块头部。

    Args:
        pieces: 片段列表
        opts: 分块选项
    Returns:
        带重叠的片段列表
    """
    if opts.overlap_chars <= 0 or len(pieces) < 2:
        return pieces

    out: list[_Piece] = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        curr = pieces[i]

        # 从前一个分块尾部取重叠文本
        tail_src = prev.text[max(0, len(prev.text) - opts.overlap_chars):]
        # 对齐到句子/词边界
        snapped = _snap_overlap_head(tail_src)
        out.append(_Piece(
            text=snapped + curr.text,
            offset=curr.offset - len(snapped),
        ))

    return out


def _snap_overlap_head(tail: str) -> str:
    """将重叠文本头部对齐到句子/词边界

    向前搜索第一个干净的单元起始边界（句子结束、换行、空白），
    确保重叠是连贯的文本段而非截断的词/句。

    Args:
        tail: 尾部文本
    Returns:
        对齐后的重叠文本
    """
    # 尝试句子边界
    sent_match = re.search(r"[。！？!?.;；][\s]*", tail)
    if sent_match:
        after = sent_match.end()
        if 0 < after < len(tail):
            return tail[after:]

    # 尝试空白边界
    ws_match = re.search(r"\s", tail)
    if ws_match and ws_match.start() < len(tail) - 1:
        return tail[ws_match.start() + 1:]

    return tail
