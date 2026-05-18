import hashlib
import json
import os
import time


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _cache_path(project_path: str) -> str:
    return os.path.join(project_path, ".llm-wiki", "ingest-cache.json")


def _load_cache(project_path: str) -> dict:
    try:
        with open(_cache_path(project_path), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": {}}


def _save_cache(project_path: str, cache: dict) -> None:
    try:
        path = _cache_path(project_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def check_ingest_cache(project_path: str, source_file_name: str, source_content: str) -> list[str] | None:
    cache = _load_cache(project_path)
    entry = cache.get("entries", {}).get(source_file_name)
    if not entry:
        return None

    current_hash = _sha256(source_content)
    if entry.get("hash") != current_hash:
        return None

    for file_path in entry.get("files_written", []):
        full_path = file_path if os.path.isabs(file_path) else os.path.join(project_path, file_path)
        full_path = os.path.normpath(full_path)
        if not os.path.isfile(full_path):
            return None

    return entry.get("files_written")


def save_ingest_cache(project_path: str, source_file_name: str, source_content: str, files_written: list[str]) -> None:
    cache = _load_cache(project_path)
    hash_val = _sha256(source_content)
    entries = dict(cache.get("entries", {}))
    entries[source_file_name] = {
        "hash": hash_val,
        "timestamp": int(time.time() * 1000),
        "files_written": files_written,
    }
    _save_cache(project_path, {"entries": entries})


def remove_from_ingest_cache(project_path: str, source_file_name: str) -> None:
    cache = _load_cache(project_path)
    entries = dict(cache.get("entries", {}))
    entries.pop(source_file_name, None)
    _save_cache(project_path, {"entries": entries})
