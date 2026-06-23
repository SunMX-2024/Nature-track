from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


USAGE_PATH = Path("data") / "usage.json"

DEFAULT_USAGE: dict[str, Any] = {
    "views": 0,
    "searches": 0,
    "articles_seen": 0,
    "test_pushes": 0,
    "scheduled_pushes": 0,
    "keyword_counts": {},
    "keyword_memory": {},
    "read_articles": [],
    "last_view_at": "",
    "last_search_at": "",
    "last_push_at": "",
}


def load_usage(path: Path = USAGE_PATH) -> dict[str, Any]:
    if not path.exists():
        return DEFAULT_USAGE.copy()
    with path.open("r", encoding="utf-8") as handle:
        return DEFAULT_USAGE | json.load(handle)


def save_usage(usage: dict[str, Any], path: Path = USAGE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(DEFAULT_USAGE | usage, handle, ensure_ascii=False, indent=2)


def record_usage(**increments: int) -> dict[str, Any]:
    usage = load_usage()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for key, increment in increments.items():
        usage[key] = int(usage.get(key, 0)) + increment
    if increments.get("views"):
        usage["last_view_at"] = now
    if increments.get("searches"):
        usage["last_search_at"] = now
    if increments.get("test_pushes") or increments.get("scheduled_pushes"):
        usage["last_push_at"] = now
    save_usage(usage)
    return usage


def record_keywords(terms: list[str], path: Path = USAGE_PATH) -> dict[str, Any]:
    usage = load_usage(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    counts = dict(usage.get("keyword_counts", {}))
    memory = _keyword_memory(usage)
    for term in terms:
        normalized = term.strip().casefold()
        if normalized:
            counts[normalized] = int(counts.get(normalized, 0)) + 1
            current = memory.get(normalized, {"count": 0, "last_used_at": ""})
            memory[normalized] = {
                "count": int(current.get("count", 0)) + 1,
                "last_used_at": now,
            }
    usage["keyword_counts"] = counts
    usage["keyword_memory"] = memory
    save_usage(usage, path)
    return usage


def frequent_keyword_entries(limit: int = 12, path: Path = USAGE_PATH) -> list[dict[str, Any]]:
    memory = _keyword_memory(load_usage(path))
    return [
        {"term": term, **entry}
        for term, entry in sorted(
            memory.items(),
            key=lambda item: (
                -int(item[1].get("count", 0)),
                -_keyword_timestamp(str(item[1].get("last_used_at", ""))),
                item[0].casefold(),
            ),
        )[:limit]
    ]


def frequent_keywords(limit: int = 12, path: Path = USAGE_PATH) -> list[str]:
    return [
        entry["term"]
        for entry in frequent_keyword_entries(limit, path)
    ]


def _keyword_memory(usage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    memory: dict[str, dict[str, Any]] = {}
    for term, count in dict(usage.get("keyword_counts", {})).items():
        normalized = str(term).strip().casefold()
        if normalized:
            memory[normalized] = {"count": int(count), "last_used_at": ""}

    for term, entry in dict(usage.get("keyword_memory", {})).items():
        normalized = str(term).strip().casefold()
        if not normalized:
            continue
        if isinstance(entry, dict):
            memory[normalized] = {
                "count": int(entry.get("count", memory.get(normalized, {}).get("count", 0))),
                "last_used_at": str(entry.get("last_used_at", "")),
            }
        else:
            memory[normalized] = {"count": int(entry), "last_used_at": ""}
    return memory


def _keyword_timestamp(value: str) -> float:
    if not value:
        return 0
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return 0


def record_read_article(article: dict[str, Any], action: str) -> dict[str, Any]:
    usage = load_usage()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    archive = list(usage.get("read_articles", []))
    key = article.get("doi") or article.get("title")

    existing = next(
        (item for item in archive if (item.get("doi") or item.get("title")) == key),
        None,
    )
    if existing:
        existing["last_read_at"] = now
        existing["read_count"] = int(existing.get("read_count", 1)) + 1
        existing["last_action"] = action
    else:
        archive.insert(
            0,
            {
                **article,
                "first_read_at": now,
                "last_read_at": now,
                "read_count": 1,
                "last_action": action,
            },
        )

    usage["read_articles"] = archive[:100]
    save_usage(usage)
    return usage
