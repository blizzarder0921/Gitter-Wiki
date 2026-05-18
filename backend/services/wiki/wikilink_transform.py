import re
from urllib.parse import quote

WIKILINK_RE = re.compile(r'\[\[([^\]|\n]+)(?:\|([^\]\n]*))?\]\]')


def transform_wikilinks(body: str) -> str:
    if "[[" not in body:
        return body

    parts = re.split(r"(```[\s\S]*?```)", body)
    return "".join(
        part if idx % 2 == 1 else _transform_outside_code(part)
        for idx, part in enumerate(parts)
    )


def _transform_outside_code(text: str) -> str:
    if "[[" not in text:
        return text

    parts = re.split(r"(`[^`\n]+`)", text)
    return "".join(
        part if idx % 2 == 1 else _replace_wikilinks(part)
        for idx, part in enumerate(parts)
    )


def _replace_wikilinks(text: str) -> str:
    def _replacer(m: re.Match) -> str:
        raw_target = m.group(1)
        raw_alias = m.group(2)
        target = raw_target.strip()
        alias = raw_alias.strip() if raw_alias else ""
        label = alias if alias else target
        href = f"#{quote(target, safe='')}"
        escaped_label = label.replace("[", "\\[").replace("]", "\\]")
        return f"[{escaped_label}]({href})"

    return WIKILINK_RE.sub(_replacer, text)
