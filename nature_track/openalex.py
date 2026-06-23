from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from html import unescape
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote

import requests


OPENALEX_API = "https://api.openalex.org"
OPENALEX_MAILTO = "nature-track@example.local"
REQUEST_TIMEOUT = 25
REQUEST_RETRIES = 2
SOURCE_CACHE_PATH = Path("data") / "source_ids.json"
RESPONSE_CACHE_DIR = Path("data") / "openalex_cache"
RATE_LIMIT_PATH = Path("data") / "openalex_rate_limit.json"
DEFAULT_HEADERS = {
    "User-Agent": "Nature-track/1.0 (local research tracker; mailto:nature-track@example.local)",
}
RATE_LIMIT_COOLDOWN_SECONDS = 15 * 60
RATE_LIMIT_MAX_COOLDOWN_SECONDS = 30 * 60


@dataclass(frozen=True)
class ArticleQuery:
    journals: list[str]
    from_date: date
    to_date: date
    keywords: str = ""
    article_types: list[str] | None = None
    max_results: int = 50
    max_pages: int = 5
    mailto: str = ""


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
    primary_topic: str = ""
    topics: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @property
    def compact_label(self) -> str:
        first = self.first_author or "Unknown"
        corresponding = self.corresponding_author or "Unknown"
        journal = self.journal or "Unknown journal"
        title = self.title or "Untitled"
        return f"{first}_{corresponding}_{journal}_{title}"


def _request_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    mailto = (params.pop("mailto", "") or OPENALEX_MAILTO).strip()
    params = {"mailto": mailto, **params}
    cache_path = _response_cache_path(path, params)
    cached = _load_response_cache(cache_path)
    if cached is not None:
        return cached
    _raise_if_rate_limited()

    last_error: requests.RequestException | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            response = requests.get(
                f"{OPENALEX_API}{path}",
                params=params,
                headers=_headers_for_mailto(mailto),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 429 and attempt < REQUEST_RETRIES:
                _record_rate_limit(response.headers.get("Retry-After"))
                retry_after = response.headers.get("Retry-After")
                delay = _retry_delay(attempt, retry_after)
                time.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            _save_response_cache(cache_path, data)
            return data
        except requests.RequestException as error:
            last_error = error
            response = getattr(error, "response", None)
            if response is not None and getattr(response, "status_code", None) == 429:
                _record_rate_limit(response.headers.get("Retry-After"))
            if attempt < REQUEST_RETRIES:
                time.sleep(_retry_delay(attempt))
    if last_error:
        raise last_error
    raise RuntimeError("OpenAlex request failed")


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 8.0)
        except ValueError:
            pass
    return min(1.5 * (2 ** attempt), 6.0)


def _headers_for_mailto(mailto: str) -> dict[str, str]:
    if not mailto or mailto == OPENALEX_MAILTO:
        return DEFAULT_HEADERS
    return {
        "User-Agent": f"Nature-track/1.0 (local research tracker; mailto:{mailto})",
    }


def _raise_if_rate_limited(path: Path = RATE_LIMIT_PATH) -> None:
    state = _load_rate_limit_state(path)
    until = float(state.get("until", 0))
    remaining = int(until - time.time())
    if remaining > RATE_LIMIT_MAX_COOLDOWN_SECONDS:
        until = time.time() + RATE_LIMIT_MAX_COOLDOWN_SECONDS
        _save_rate_limit_until(until, path)
        remaining = RATE_LIMIT_MAX_COOLDOWN_SECONDS
    if remaining > 0:
        response = requests.Response()
        response.status_code = 429
        error = requests.HTTPError(
            f"OpenAlex cooling down after rate limit; retry in about {max(1, remaining // 60)} min"
        )
        error.response = response
        raise error


def _record_rate_limit(retry_after: str | None = None, path: Path = RATE_LIMIT_PATH) -> None:
    delay = RATE_LIMIT_COOLDOWN_SECONDS
    if retry_after:
        try:
            delay = max(delay, int(float(retry_after)))
        except ValueError:
            pass
    delay = min(delay, RATE_LIMIT_MAX_COOLDOWN_SECONDS)
    _save_rate_limit_until(time.time() + delay, path)


def _save_rate_limit_until(until: float, path: Path = RATE_LIMIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"until": until}, handle)


def _load_rate_limit_state(path: Path = RATE_LIMIT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=256)
def resolve_source_id(journal_name: str, mailto: str = "") -> str | None:
    normalized = journal_name.casefold().strip()
    cached = _load_source_cache().get(normalized)
    if cached:
        return cached

    params = {"search": journal_name, "per-page": 5}
    if mailto:
        params["mailto"] = mailto
    data = _request_json("/sources", params)
    results = data.get("results", [])
    source_id = None

    for source in results:
        if source.get("display_name", "").casefold().strip() == normalized:
            source_id = source.get("id")
            break

    if not source_id:
        for source in results:
            aliases = [alias.casefold().strip() for alias in source.get("alternate_titles", [])]
            if normalized in aliases:
                source_id = source.get("id")
                break

    if not source_id:
        source_id = results[0].get("id") if results else None

    if source_id:
        cache = _load_source_cache()
        cache[normalized] = source_id
        _save_source_cache(cache)

    return source_id


def fetch_articles(query: ArticleQuery) -> list[Article]:
    source_ids = _resolve_source_ids(query.journals, query.mailto)
    if query.journals and not source_ids:
        return []
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

    articles: list[Article] = []
    seen_ids: set[str] = set()
    max_pages = max(query.max_pages, 1)
    for page in range(1, max_pages + 1):
        request_params = params | {"page": page}
        if query.mailto:
            request_params["mailto"] = query.mailto
        data = _request_json("/works", request_params)
        results = data.get("results", [])
        if not results:
            break

        for item in results:
            item_id = item.get("id") or item.get("doi") or item.get("title")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            articles.append(_parse_article(item))

        if len(results) < params["per-page"]:
            break

    return articles


def _resolve_source_ids(journals: list[str], mailto: str = "") -> list[str]:
    source_ids: list[str] = []
    for name in journals:
        try:
            source_id = resolve_source_id(name, mailto)
        except requests.RequestException:
            continue
        if source_id:
            source_ids.append(source_id)
    return _dedupe(source_ids)


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
        primary_topic=_topic_name(item.get("primary_topic") or {}),
        topics=_topic_names(item),
        concepts=_concept_names(item),
        keywords=_keyword_names(item),
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


def _topic_name(topic: dict[str, Any]) -> str:
    return _clean_text(topic.get("display_name") or "")


def _topic_names(item: dict[str, Any]) -> list[str]:
    names = [_topic_name(topic) for topic in item.get("topics", [])]
    primary = _topic_name(item.get("primary_topic") or {})
    return _dedupe([primary, *names])


def _concept_names(item: dict[str, Any]) -> list[str]:
    return _dedupe(
        _clean_text(concept.get("display_name") or "")
        for concept in item.get("concepts", [])
    )


def _keyword_names(item: dict[str, Any]) -> list[str]:
    return _dedupe(
        _clean_text(keyword.get("display_name") or keyword.get("keyword") or "")
        for keyword in item.get("keywords", [])
    )


def _dedupe(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _load_source_cache(path: Path = SOURCE_CACHE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def _save_source_cache(cache: dict[str, str], path: Path = SOURCE_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def _response_cache_path(path: str, params: dict[str, Any]) -> Path:
    payload = json.dumps({"path": path, "params": params}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return RESPONSE_CACHE_DIR / f"{digest}.json"


def _load_response_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _save_response_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()
