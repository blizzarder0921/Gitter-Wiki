"""
Wiki 文件名生成模块

为用户发起的 "保存到 Wiki" 操作生成安全的文件名。

为什么需要独立模块：
  早期内联逻辑会将所有非 ASCII 字符从 slug 中移除，
  这导致所有中文标题的对话都坍缩为空 slug，最终碰撞成
  同一天的 `-YYYY-MM-DD.md`，用户每天只能保留一条保存记录。
  本纯函数模块使文件名策略可被独立测试。

文件名格式：
  {slug}-{YYYY-MM-DD}-{HHMMSS}.md

Slug 规则：
  - Unicode 感知：保留所有文字体系的字母和数字（拉丁、CJK、
    西里尔、阿拉伯等）以及 ASCII 连字符。
  - NFKC 归一化，使全角字符与半角等价形式统一。
  - 小写化（对没有大小写的文字体系无影响）。
  - 空白字符转为连字符。
  - 折叠连续连字符，去除首尾连字符。
  - 截断到 50 字符。
  - 空结果回退为 "query"。

尾部时间戳保证同一天内多次保存不会因标题产生相同 slug 而冲突
（例如多个中文对话拥有相同主题，或反复保存 "无标题"）。
"""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, Optional


def make_query_slug(title: str) -> str:
    """
    生成 Unicode 安全的 slug 字符串。

    对标题进行 NFKC 归一化后，保留 Unicode 字母、数字和 ASCII 连字符，
    移除表情符号和标点以确保文件名在 Windows/macOS/Linux 上均安全。

    参数:
        title: 原始标题字符串

    返回:
        处理后的 slug 字符串；若结果为空则回退为 "query"
    """
    # 1. NFKC 归一化：统一全角/半角等变体形式
    slug = unicodedata.normalize("NFKC", title)

    # 2. 去除首尾空白
    slug = slug.strip()

    # 3. 空白字符（含连续空白）替换为单个连字符
    slug = re.sub(r"\s+", "-", slug)

    # 4. 仅保留 Unicode 字母(\\p{L})、Unicode 数字(\\p{N})和 ASCII 连字符
    #    移除 emoji、标点等，保持文件名跨平台安全
    slug = re.sub(r"[^\w-]", "", slug, flags=re.UNICODE)

    # \w 在 Python 中包含下划线 _，但原始规范不保留下划线，需额外移除
    slug = slug.replace("_", "")

    # 5. 折叠连续连字符为单个
    slug = re.sub(r"-+", "-", slug)

    # 6. 去除首尾连字符
    slug = slug.strip("-")

    # 7. 小写化（对无大小写的文字体系无影响）
    slug = slug.lower()

    # 8. 截断到 50 字符
    slug = slug[:50]

    # 9. 空结果回退为 "query"
    return slug if slug else "query"


def make_query_file_name(
    title: str,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """
    生成完整的 Wiki 文件名。

    文件名格式为 {slug}-{YYYY-MM-DD}-{HHMMSS}.md，使用 UTC 时间戳
    以避免不同机器/时区产生不同文件名。

    参数:
        title: 原始标题字符串
        now:   可选的时间注入参数，用于确定性测试；
               生产调用应省略，默认使用当前 UTC 时间

    返回:
        包含以下键的字典：
        - slug:      标题生成的 slug
        - file_name: 完整文件名，如 "我的查询-2026-04-23-143052.md"
        - date:      UTC 日期部分，如 "2026-04-23"
        - time:      UTC 时间部分（无冒号），如 "143052"
    """
    slug = make_query_slug(title)

    # 使用 UTC 时间，避免夏令时/时区翻转导致同一保存产生不同文件名
    if now is None:
        now = datetime.now(timezone.utc)

    # 确保 now 是 UTC 感知的 datetime 对象
    if now.tzinfo is None:
        # 若传入 naive datetime，视为 UTC
        now = now.replace(tzinfo=timezone.utc)

    # 转换为 UTC（若传入其他时区的时间）
    now_utc = now.astimezone(timezone.utc)

    # 格式化日期和时间部分
    date_str = now_utc.strftime("%Y-%m-%d")   # 例如 "2026-04-23"
    time_str = now_utc.strftime("%H%M%S")     # 例如 "143052"

    # 组装完整文件名
    file_name = f"{slug}-{date_str}-{time_str}.md"

    return {
        "slug": slug,
        "file_name": file_name,
        "date": date_str,
        "time": time_str,
    }
