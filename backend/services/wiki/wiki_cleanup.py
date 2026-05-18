import re

INDEX_ENTRY_RE = re.compile(r'^\s*[-*]\s*\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]')
WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]')


def normalize_wiki_ref_key(s: str) -> str:
    normalized = s.strip().replace("\\", "/")
    leaf = normalized.split("/")[-1] if "/" in normalized else normalized
    if leaf.lower().endswith(".md"):
        leaf = leaf[:-3]
    return re.sub(r'[\s\-_]+', '', leaf.lower())


def build_deleted_keys(infos: list[dict]) -> set[str]:
    keys = set()
    for info in infos:
        slug = info.get("slug", "")
        title = info.get("title", "")
        if slug:
            keys.add(normalize_wiki_ref_key(slug))
        if title:
            keys.add(normalize_wiki_ref_key(title))
    return keys


def extract_frontmatter_title(content: str) -> str:
    m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def clean_index_listing(text: str, deleted_keys: set[str]) -> str:
    if not deleted_keys:
        return text
    lines = text.split("\n")
    filtered = []
    for line in lines:
        m = INDEX_ENTRY_RE.match(line)
        if m and normalize_wiki_ref_key(m.group(1).strip()) in deleted_keys:
            continue
        filtered.append(line)
    return "\n".join(filtered)


def strip_deleted_wikilinks(text: str, deleted_keys: set[str]) -> str:
    if not deleted_keys:
        return text

    def _replacer(m: re.Match) -> str:
        target = m.group(1)
        display = m.group(2)
        key = normalize_wiki_ref_key(target.strip())
        if key not in deleted_keys:
            return m.group(0)
        return display if display else target

    return WIKILINK_RE.sub(_replacer, text)
