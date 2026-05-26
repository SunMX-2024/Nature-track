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


def record_keywords(terms: list[str]) -> dict[str, Any]:
    usage = load_usage()
    counts = dict(usage.get("keyword_counts", {}))
    for term in terms:
        normalized = term.strip()
        if normalized:
            counts[normalized] = int(counts.get(normalized, 0)) + 1
    usage["keyword_counts"] = counts
    save_usage(usage)
    return usage


def frequent_keywords(limit: int = 12) -> list[str]:
    counts = load_usage().get("keyword_counts", {})
    return [
        term
        for term, _ in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0].casefold()))[:limit]
    ]


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
