"""
Frontmatter 数组字段合并模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/sources-merge.ts 移植。
解决摄入管线中数组字段（sources/tags/related）被覆盖导致数据丢失的问题。

核心场景：
  重复摄入同一页面时，新来源的 sources/tags/related 会覆盖旧值，
  导致旧来源信息丢失，后续删除流程会误删页面（静默数据丢失）。
  本模块通过集合并集合并，保留所有历史值。

三个公开函数：
  - parse_frontmatter_array: 解析 frontmatter 中的数组字段
  - write_frontmatter_array: 重写 frontmatter 中的数组字段
  - merge_array_fields_into_content: 多字段合并入口
"""

import re


def parse_frontmatter_array(content: str, field_name: str) -> list[str]:
    """从 frontmatter 中提取数组字段值

    支持两种 YAML 数组格式：
      内联形式：name: ["a", "b"] 或 name: [a, b]
      块形式：  name:\\n  - a\\n  - b

    字段名按整词匹配（行首 + 冒号），因此
    parse_frontmatter_array(c, "rel") 不会误匹配 related: [...]

    Args:
        content: Markdown 文件完整内容
        field_name: 要提取的数组字段名
    Returns:
        字符串列表；字段不存在、格式错误或无 frontmatter 时返回空列表
    """
    # 定位 frontmatter 块（文件顶部的 --- ... --- 之间）
    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if not fm_match:
        return []

    fm = fm_match.group(1)
    # 转义字段名中的正则特殊字符，防止注入
    escaped_name = re.escape(field_name)

    # 优先尝试块形式：name: 后换行，然后缩进的 - 列表项
    # 匹配模式：行首字段名 + 冒号 + 可选空白 + 换行 + 一个或多个缩进的列表项
    block_re = re.compile(
        rf"^{escaped_name}:\s*\n((?:[ \t]+-\s+.+\n?)+)",
        re.MULTILINE,
    )
    block = block_re.search(fm)
    if block:
        out: list[str] = []
        for line in block.group(1).split("\n"):
            # 提取列表项值，去除可选的引号包裹
            m = re.match(r"^\s+-\s+[\"']?(.+?)[\"']?\s*$", line)
            if m and m.group(1):
                out.append(m.group(1).strip())
        return out

    # 尝试内联形式：name: [item1, item2, ...]
    inline_re = re.compile(rf"^{escaped_name}:\s*\[([^\]]*)\]", re.MULTILINE)
    inline = inline_re.search(fm)
    if not inline:
        return []

    # 解析方括号内的逗号分隔值
    body = inline.group(1).strip()
    if not body:
        return []

    # 逐项去除空白和首尾引号，过滤空串
    return [
        s.strip().strip("\"'")
        for s in body.split(",")
        if s.strip().strip("\"'")
    ]


def write_frontmatter_array(
    content: str, field_name: str, values: list[str]
) -> str:
    """将数组字段写入 frontmatter

    始终使用内联形式 name: ["a", "b"] 输出，保证下游解析器
    看到一致的格式，无论原始输入是内联还是块形式。

    保留其他 frontmatter 行不变，维持原有顺序。
    无 frontmatter 时返回原内容（不制造 frontmatter，
    避免静默修复格式异常的页面）。

    Args:
        content: Markdown 文件完整内容
        field_name: 字段名
        values: 要写入的字符串列表
    Returns:
        修改后的完整内容；无 frontmatter 时原样返回
    """
    # 捕获 frontmatter 的三个部分：开分隔符、正文、关分隔符
    fm_match = re.match(r"^(---\n)([\s\S]*?)(\n---)", content)
    if not fm_match:
        return content

    open_delim = fm_match.group(1)   # "---\\n"
    fm_body = fm_match.group(2)      # frontmatter 正文
    close_delim = fm_match.group(3)  # "\\n---"
    rest = content[fm_match.end():]  # frontmatter 之后的正文

    escaped_name = re.escape(field_name)
    # 序列化为内联格式：每个值用双引号包裹，逗号+空格分隔
    serialized = ", ".join(f'"{s}"' for s in values)
    new_line = f"{field_name}: [{serialized}]"

    # 策略1：替换已有的内联形式（保持字段原位置）
    inline_re = re.compile(rf"^{escaped_name}:\s*\[[^\]]*\]", re.MULTILINE)
    if inline_re.search(fm_body):
        rewritten = inline_re.sub(new_line, fm_body)
        return f"{open_delim}{rewritten}{close_delim}{rest}"

    # 策略2：替换已有的块形式，标准化为内联形式
    block_re = re.compile(
        rf"^{escaped_name}:\s*\n((?:[ \t]+-\s+.+\n?)+)",
        re.MULTILINE,
    )
    if block_re.search(fm_body):
        rewritten = block_re.sub(new_line, fm_body)
        return f"{open_delim}{rewritten}{close_delim}{rest}"

    # 策略3：字段不存在，追加到 frontmatter 末尾
    rewritten = f"{fm_body}\n{new_line}"
    return f"{open_delim}{rewritten}{close_delim}{rest}"


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    """集合并集合并，大小写不敏感去重

    首次出现的写法保留（与 TypeScript 版行为一致），
    确保用户原始文件名大小写在多次摄入间保持稳定。

    Args:
        existing: 已有值列表
        incoming: 新增值列表
    Returns:
        合并并去重后的列表
    """
    seen: set[str] = set()
    out: list[str] = []
    for s in existing + incoming:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def merge_array_fields_into_content(
    content: str, new_values: dict[str, list[str]]
) -> str:
    """合并多个 frontmatter 数组字段

    对 new_values 中的每个字段，从 content 中解析旧值，
    与新值取并集（大小写不敏感去重），然后写回 content。

    快速路径：
      - content 无 frontmatter → 原样返回
      - new_values 为空 → 原样返回
      - 无字段实际变化 → 原样返回（稳定引用，调用方可用于缓存键不变性判断）

    Args:
        content: Markdown 文件完整内容（包含 frontmatter）
        new_values: 字段名到新值列表的映射，
                    例如 {"sources": [...], "tags": [...], "related": [...]}
    Returns:
        合并后的完整内容
    """
    if not new_values:
        return content

    # 无 frontmatter 时不做处理
    if not content.startswith("---\n"):
        return content

    result = content
    changed = False

    for field_name, incoming in new_values.items():
        # 从当前内容中解析该字段的旧值
        old_values = parse_frontmatter_array(result, field_name)

        # 集合并集合并
        merged = _merge_lists(old_values, incoming)

        # 检查是否有实际变化（长度和内容都相同则跳过）
        if len(merged) == len(old_values) and all(
            a == b for a, b in zip(merged, old_values)
        ):
            continue

        result = write_frontmatter_array(result, field_name, merged)
        changed = True

    return result if changed else content
