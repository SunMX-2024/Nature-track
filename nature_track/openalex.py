from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from html import unescape
import re
from typing import Any
from urllib.parse import quote

import requests


OPENALEX_API = "https://api.openalex.org"
OPENALEX_MAILTO = "nature-track@example.local"
REQUEST_TIMEOUT = 25


@dataclass(frozen=True)
class ArticleQuery:
    journals: list[str]
    from_date: date
    to_date: date
    keywords: str = ""
    article_types: list[str] | None = None
    max_results: int = 50


@dataclass(frozen=True)
class Article:
    title: str
    journal: str
    first_author: str
    authors: list[str]
    corresponding_authors: list[str]
    corresponding_author: str
    corresponding_inferred: bool
    doi: str
    doi_url: str
    publication_date: str
    article_type: str
    abstract: str
    is_oa: bool
    pdf_url: str
    landing_page_url: str

    @property
    def compact_label(self) -> str:
        first = self.first_author or "Unknown"
        corresponding = self.corresponding_author or "Unknown"
        journal = self.journal or "Unknown journal"
        title = self.title or "Untitled"
        return f"{first}_{corresponding}_{journal}_{title}"


def _request_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    params = {"mailto": OPENALEX_MAILTO, **params}
    response = requests.get(f"{OPENALEX_API}{path}", params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=256)
def resolve_source_id(journal_name: str) -> str | None:
    data = _request_json("/sources", {"search": journal_name, "per-page": 5})
    results = data.get("results", [])
    normalized = journal_name.casefold().strip()

    for source in results:
        if source.get("display_name", "").casefold().strip() == normalized:
            return source.get("id")

    for source in results:
        aliases = [alias.casefold().strip() for alias in source.get("alternate_titles", [])]
        if normalized in aliases:
            return source.get("id")

    return results[0].get("id") if results else None


def fetch_articles(query: ArticleQuery) -> list[Article]:
    source_ids = [source_id for name in query.journals if (source_id := resolve_source_id(name))]
    filters = [
        f"from_publication_date:{query.from_date.isoformat()}",
        f"to_publication_date:{query.to_date.isoformat()}",
    ]

    if source_ids:
        filters.append("primary_location.source.id:" + "|".join(source_ids))

    if query.article_types:
        filters.append("type:" + "|".join(query.article_types))

    params: dict[str, Any] = {
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per-page": min(max(query.max_results, 1), 200),
    }
    if query.keywords:
        params["search"] = query.keywords

    data = _request_json("/works", params)
    return [_parse_article(item) for item in data.get("results", [])]


def _parse_article(item: dict[str, Any]) -> Article:
    authorships = item.get("authorships", [])
    first_author = _author_name(authorships[0]) if authorships else ""
    authors = [_author_name(authorship) for authorship in authorships if _author_name(authorship)]
    corresponding_authors, inferred = _corresponding_authors(item, authorships)
    corresponding_author = "; ".join(corresponding_authors)
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    oa_location = item.get("best_oa_location") or {}
    doi = item.get("doi") or ""

    return Article(
        title=_clean_text(item.get("title") or ""),
        journal=source.get("display_name") or "",
        first_author=first_author,
        authors=authors,
        corresponding_authors=corresponding_authors,
        corresponding_author=corresponding_author,
        corresponding_inferred=inferred,
        doi=doi.replace("https://doi.org/", ""),
        doi_url=doi if doi.startswith("http") else (f"https://doi.org/{quote(doi)}" if doi else ""),
        publication_date=item.get("publication_date") or "",
        article_type=item.get("type") or "",
        abstract=_decode_abstract(item.get("abstract_inverted_index")),
        is_oa=bool((item.get("open_access") or {}).get("is_oa")),
        pdf_url=oa_location.get("pdf_url") or primary_location.get("pdf_url") or "",
        landing_page_url=oa_location.get("landing_page_url") or primary_location.get("landing_page_url") or "",
    )


def _author_name(authorship: dict[str, Any]) -> str:
    author = authorship.get("author") or {}
    return _clean_text(authorship.get("raw_author_name") or author.get("display_name") or "")


def _corresponding_authors(item: dict[str, Any], authorships: list[dict[str, Any]]) -> tuple[list[str], bool]:
    corresponding_ids = set(item.get("corresponding_author_ids") or [])
    if corresponding_ids:
        names = [
            _author_name(authorship)
            for authorship in authorships
            if (authorship.get("author") or {}).get("id") in corresponding_ids
        ]
        if names:
            return names, False

    if authorships:
        return [_author_name(authorships[-1])], True
    return [], False


def _decode_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""

    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((position, word) for position in positions)

    return _clean_text(" ".join(word for _, word in sorted(words, key=lambda pair: pair[0])))


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()
