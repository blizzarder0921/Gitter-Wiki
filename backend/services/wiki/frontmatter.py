"""
Frontmatter 解析与操作模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/frontmatter.ts 移植。
提供 YAML frontmatter 的解析、提取、修改功能。

核心功能：
- 解析 Markdown 文件中的 YAML frontmatter 块
- 支持严格模式（文件顶部）和回退模式（前几行内）
- 自动修复 LLM 生成的常见格式问题（如 wikilink 列表）
- 标量化输出：所有值转为 string 或 string[]
"""

import re
from typing import Union

# 类型别名：frontmatter 值为字符串或字符串列表
FrontmatterValue = Union[str, list[str]]
FrontmatterDict = dict[str, FrontmatterValue]

# 严格模式正则：frontmatter 必须在文件顶部
_FM_BLOCK_STRICT_RE = re.compile(r"^---\s*\r?\n([\s\S]*?)\r?\n---\s*(?:\r?\n|$)")

# 回退模式正则：允许前几行有垃圾内容
_FM_BLOCK_ANYWHERE_RE = re.compile(r"\n---\s*\r?\n([\s\S]*?)\r?\n---\s*(?:\r?\n|$)")

# frontmatter 开头最大允许的前置行数
_MAX_PREFIX_LINES = 6


class FrontmatterParseResult:
    """Frontmatter 解析结果

    Attributes:
        frontmatter: 解析后的 frontmatter 字典，无 frontmatter 时为 None
        body: frontmatter 之后的正文内容
        raw_block: 原始 frontmatter 块文本（包含 --- 分隔符）
    """

    def __init__(
        self,
        frontmatter: FrontmatterDict | None,
        body: str,
        raw_block: str,
    ):
        self.frontmatter = frontmatter
        self.body = body
        self.raw_block = raw_block


def parse_frontmatter(content: str) -> FrontmatterParseResult:
    """解析 Markdown 内容中的 YAML frontmatter

    两阶段定位策略：
    1. 优先严格匹配（文件顶部）
    2. 回退扫描前几行内的 frontmatter 块

    两阶段 YAML 解析：
    1. 直接解析
    2. 失败后尝试修复 wikilink 列表格式再解析

    Args:
        content: Markdown 文件完整内容
    Returns:
        FrontmatterParseResult 实例
    """
    located = _locate_frontmatter_block(content)
    if not located:
        return FrontmatterParseResult(frontmatter=None, body=content, raw_block="")

    yaml_payload = located["yaml_payload"]
    raw_block = located["raw_block"]
    body = located["body"]

    # 两阶段 YAML 解析
    parsed = _safe_yaml_parse(yaml_payload)
    if parsed is None:
        # 尝试修复 wikilink 列表后重新解析
        repaired = _repair_wikilink_lists(yaml_payload)
        parsed = _safe_yaml_parse(repaired)
        if parsed is None:
            return FrontmatterParseResult(frontmatter=None, body=body, raw_block=raw_block)

    return FrontmatterParseResult(
        frontmatter=_normalize(parsed),
        body=body,
        raw_block=raw_block,
    )


def _locate_frontmatter_block(content: str) -> dict | None:
    """定位 frontmatter 块位置

    优先使用严格模式匹配，失败后使用回退模式。
    回退模式要求 opening --- 在前几行内，防止误匹配正文中的分隔线。

    Args:
        content: 文件内容
    Returns:
        包含 yaml_payload, raw_block, body 的字典，或 None
    """
    # 严格模式匹配
    strict = _FM_BLOCK_STRICT_RE.match(content)
    if strict:
        return {
            "yaml_payload": strict.group(1),
            "raw_block": strict.group(0),
            "body": content[strict.end():],
        }

    # 回退模式匹配
    fallback = _FM_BLOCK_ANYWHERE_RE.search(content)
    if not fallback:
        return None

    # opening --- 的位置（跳过前导 \n）
    open_idx = fallback.start() + 1
    if _line_number_at(content, open_idx) > _MAX_PREFIX_LINES:
        return None

    raw_block = content[open_idx:open_idx + len(fallback.group(0)) - 1]
    body_after_fm = content[open_idx + len(raw_block):]

    # 如果前缀是 ```yaml 代码围栏，也剥离 body 开头的对应闭合围栏
    prefix = content[:open_idx]
    if re.match(r"^\s*```(?:yaml|yml)?\s*\r?\n$", prefix, re.IGNORECASE):
        stripped = re.sub(r"^\s*```\s*(?:\r?\n|$)", "", body_after_fm)
        return {
            "yaml_payload": fallback.group(1),
            "raw_block": raw_block,
            "body": stripped,
        }

    return {
        "yaml_payload": fallback.group(1),
        "raw_block": raw_block,
        "body": body_after_fm,
    }


def _line_number_at(s: str, index: int) -> int:
    """计算给定字符索引所在的行号（1-based）

    Args:
        s: 字符串
        index: 字符索引
    Returns:
        行号（从1开始）
    """
    line = 1
    for i in range(min(index, len(s))):
        if s[i] == "\n":
            line += 1
    return line


def _safe_yaml_parse(payload: str) -> dict | None:
    """安全解析 YAML 字符串

    使用简单的行级解析，不依赖 PyYAML 的复杂特性。
    仅支持扁平的 key: value 和 key: [...] 格式。

    Args:
        payload: YAML 文本
    Returns:
        解析后的字典，或 None（解析失败时）
    """
    try:
        import yaml
        result = yaml.safe_load(payload)
        if result is None:
            return None
        if not isinstance(result, dict):
            return None
        return result
    except Exception:
        return None


def _repair_wikilink_lists(payload: str) -> str:
    """修复 YAML 中的 wikilink 列表格式

    LLM 有时会生成如下格式：
        related: [[a]], [[b]], [[c]]
    这不是合法的 YAML。修复为：
        related: ["[[a]]", "[[b]]", "[[c]]"]

    Args:
        payload: YAML 文本
    Returns:
        修复后的 YAML 文本
    """
    pattern = re.compile(
        r"^(\s*[A-Za-z_][\w-]*\s*:\s*)"
        r"(\[\[[^\]]+\]\](?:\s*,\s*\[\[[^\]]+\]\])+)\s*$",
        re.MULTILINE,
    )

    def _replace(match: re.Match) -> str:
        prefix = match.group(1)
        items_str = match.group(2)
        items = [f'"{s.strip()}"' for s in items_str.split(",") if s.strip()]
        return f"{prefix}[{', '.join(items)}]"

    return pattern.sub(_replace, payload)


def _normalize(parsed: dict) -> FrontmatterDict | None:
    """将 YAML 解析结果标准化为扁平的 string | string[] 字典

    嵌套对象和非字符串标量会被字符串化，
    确保所有值都是 string 或 string[] 类型。

    Args:
        parsed: YAML 解析结果
    Returns:
        标准化后的字典，或 None
    """
    if not parsed or not isinstance(parsed, dict):
        return None

    out: FrontmatterDict = {}
    for key, value in parsed.items():
        if isinstance(value, list):
            out[key] = [_stringify_scalar(v) for v in value]
        else:
            out[key] = _stringify_scalar(value)
    return out


def _stringify_scalar(v: object) -> str:
    """将任意标量值转为字符串

    Args:
        v: 任意值
    Returns:
        字符串表示
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    try:
        import json
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


# ---------------------------------------------------------------------------
# Frontmatter 数组字段操作（从 sources-merge.ts 移植）
# ---------------------------------------------------------------------------

def parse_frontmatter_array(content: str, field_name: str) -> list[str]:
    """从 frontmatter 中提取数组字段值

    支持两种格式：
    - 内联形式：name: ["a", "b"] 或 name: [a, b]
    - 块形式：name:\\n  - a\\n  - b

    Args:
        content: Markdown 文件完整内容
        field_name: 字段名
    Returns:
        字符串列表，字段不存在时返回空列表
    """
    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if not fm_match:
        return []

    fm = fm_match.group(1)
    escaped_name = re.escape(field_name)

    # 尝试块形式匹配
    block_re = re.compile(
        rf"^{escaped_name}:\s*\n((?:[ \t]+-\s+.+\n?)+)",
        re.MULTILINE,
    )
    block = block_re.search(fm)
    if block:
        out: list[str] = []
        for line in block.group(1).split("\n"):
            m = re.match(r"^\s+-\s+[\"']?(.+?)[\"']?\s*$", line)
            if m and m.group(1):
                out.append(m.group(1).strip())
        return out

    # 尝试内联形式匹配
    inline_re = re.compile(rf"^{escaped_name}:\s*\[([^\]]*)\]", re.MULTILINE)
    inline = inline_re.search(fm)
    if not inline:
        return []

    body = inline.group(1).strip()
    if not body:
        return []

    return [
        s.strip().strip("\"'")
        for s in body.split(",")
        if s.strip().strip("\"'")
    ]


def write_frontmatter_array(
    content: str, field_name: str, values: list[str]
) -> str:
    """将数组字段写入 frontmatter

    始终使用内联形式 name: ["a", "b"] 输出，保持一致性。
    如果字段已存在则替换，不存在则追加。

    Args:
        content: Markdown 文件完整内容
        field_name: 字段名
        values: 字符串列表
    Returns:
        修改后的内容，无 frontmatter 时原样返回
    """
    fm_match = re.match(r"^(---\n)([\s\S]*?)(\n---)", content)
    if not fm_match:
        return content

    open_delim = fm_match.group(1)
    fm_body = fm_match.group(2)
    close_delim = fm_match.group(3)
    rest = content[fm_match.end():]

    escaped_name = re.escape(field_name)
    serialized = ", ".join(f'"{s}"' for s in values)
    new_line = f"{field_name}: [{serialized}]"

    # 替换内联形式
    inline_re = re.compile(rf"^{escaped_name}:\s*\[[^\]]*\]", re.MULTILINE)
    if inline_re.search(fm_body):
        rewritten = inline_re.sub(new_line, fm_body)
        return f"{open_delim}{rewritten}{close_delim}{rest}"

    # 替换块形式
    block_re = re.compile(
        rf"^{escaped_name}:\s*\n((?:[ \t]+-\s+.+\n?)+)",
        re.MULTILINE,
    )
    if block_re.search(fm_body):
        rewritten = block_re.sub(new_line, fm_body)
        return f"{open_delim}{rewritten}{close_delim}{rest}"

    # 字段不存在，追加到 frontmatter 末尾
    rewritten = f"{fm_body}\n{new_line}"
    return f"{open_delim}{rewritten}{close_delim}{rest}"


def merge_array_fields_into_content(
    new_content: str,
    existing_content: str | None,
    fields: list[str],
) -> str:
    """多字段合并入口：对每个指定字段做集合并集合并

    快速路径：
    - existing_content 为空 → 直接返回 new_content
    - existing_content 无 frontmatter → 直接返回 new_content
    - 无字段实际变化 → 原样返回 new_content（稳定引用）

    Args:
        new_content: 新内容
        existing_content: 已有内容，可为 None
        fields: 需要合并的字段名列表
    Returns:
        合并后的内容
    """
    if not existing_content:
        return new_content
    if not existing_content.startswith("---\n"):
        return new_content

    result = new_content
    changed = False
    for field in fields:
        old_values = parse_frontmatter_array(existing_content, field)
        if not old_values:
            continue  # 已有内容中无此字段，无需保留
        new_values = parse_frontmatter_array(result, field)
        merged = _merge_lists(old_values, new_values)
        # 检查是否有实际变化
        if len(merged) == len(new_values) and all(
            a == b for a, b in zip(merged, new_values)
        ):
            continue
        result = write_frontmatter_array(result, field, merged)
        changed = True

    return result if changed else new_content


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    """集合并集合并，大小写不敏感去重，首次出现的写法保留

    Args:
        existing: 已有值列表
        incoming: 新增值列表
    Returns:
        合并后的列表
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


def set_frontmatter_scalar(
    content: str, field_name: str, value: str
) -> str:
    """设置 frontmatter 中的标量字段值

    如果字段已存在则替换，不存在则追加。
    仅匹配标量形式（不匹配数组形式）。

    Args:
        content: Markdown 文件完整内容
        field_name: 字段名
        value: 新值
    Returns:
        修改后的内容，无 frontmatter 时原样返回
    """
    fm_match = re.match(r"^(---\n)([\s\S]*?)(\n---)", content)
    if not fm_match:
        return content

    open_delim = fm_match.group(1)
    fm_body = fm_match.group(2)
    close_delim = fm_match.group(3)
    rest = content[fm_match.end():]

    escaped_name = re.escape(field_name)
    new_line = f"{field_name}: {value}"

    # 仅匹配标量形式（排除数组 [ 和块 - 形式）
    line_re = re.compile(rf"^{escaped_name}:\s*(?!\[)([^\n]*)", re.MULTILINE)
    if line_re.search(fm_body):
        rewritten = line_re.sub(new_line, fm_body)
        return f"{open_delim}{rewritten}{close_delim}{rest}"

    # 字段不存在，追加到 frontmatter 末尾
    rewritten = f"{fm_body}\n{new_line}"
    return f"{open_delim}{rewritten}{close_delim}{rest}"
