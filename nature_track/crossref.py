from __future__ import annotations

from dataclasses import dataclass
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

from nature_track.openalex import Article, ArticleQuery


CROSSREF_API = "https://api.crossref.org"
DEFAULT_MAILTO = "nature-track@example.local"
REQUEST_TIMEOUT = 25
REQUEST_RETRIES = 2
ISSN_CACHE_PATH = Path("data") / "crossref_issns.json"
RESPONSE_CACHE_DIR = Path("data") / "crossref_cache"


@dataclass(frozen=True)
class CrossrefResult:
    articles: list[Article]
    warnings: list[str]


def fetch_crossref_articles(query: ArticleQuery) -> list[Article]:
    return fetch_crossref_articles_with_diagnostics(query).articles


def fetch_crossref_articles_with_diagnostics(query: ArticleQuery) -> CrossrefResult:
    warnings: list[str] = []
    articles: list[Article] = []
    seen: set[str] = set()
    journal_issns = _resolve_journal_issns(query.journals, query.mailto)

    if query.journals and not journal_issns:
        return CrossrefResult([], ["Crossref could not resolve ISSNs for the selected journals."])

    if journal_issns:
        per_journal_rows = _per_journal_rows(query)
        for journal, issns in journal_issns.items():
            journal_articles, error = _fetch_journal_articles(query, issns, per_journal_rows)
            if error:
                warnings.append(f"Crossref search failed for '{journal}': {error}")
            for article in journal_articles:
                key = _article_key(article)
                if key in seen:
                    continue
                seen.add(key)
                articles.append(article)
    else:
        articles, error = _fetch_crossref_works(query, None, query.max_results)
        if error:
            warnings.append(f"Crossref search failed: {error}")

    return CrossrefResult(
        sorted(articles, key=lambda article: article.publication_date, reverse=True)[: max(query.max_results, 1)],
        warnings,
    )


def _fetch_journal_articles(query: ArticleQuery, issns: list[str], rows: int) -> tuple[list[Article], str]:
    collected: list[Article] = []
    errors: list[str] = []
    for issn in issns[:2]:
        articles, error = _fetch_crossref_works(query, issn, rows)
        if error:
            errors.append(error)
            continue
        collected.extend(articles)
        if articles:
            break
    return collected, "; ".join(_dedupe(errors))


def _fetch_crossref_works(query: ArticleQuery, issn: str | None, rows: int) -> tuple[list[Article], str]:
    path = f"/journals/{quote(issn)}/works" if issn else "/works"
    filters = [
        f"from-pub-date:{query.from_date.isoformat()}",
        f"until-pub-date:{query.to_date.isoformat()}",
        "type:journal-article",
    ]
    params: dict[str, Any] = {
        "filter": ",".join(filters),
        "sort": "published",
        "order": "desc",
        "rows": min(max(rows, 1), 100),
        "select": ",".join(
            [
                "DOI",
                "URL",
                "title",
                "container-title",
                "published-print",
                "published-online",
                "published",
                "type",
                "abstract",
                "author",
                "ISSN",
                "link",
            ]
        ),
    }
    if query.keywords:
        params["query.bibliographic"] = query.keywords
    if query.mailto:
        params["mailto"] = query.mailto

    try:
        data = _request_json(path, params)
    except requests.RequestException as error:
        return [], _format_request_error(error)

    items = data.get("message", {}).get("items", [])
    return [_parse_crossref_article(item) for item in items], ""


def _resolve_journal_issns(journals: list[str], mailto: str = "") -> dict[str, list[str]]:
    return {
        journal: issns
        for journal in journals
        if (issns := resolve_journal_issns(journal, mailto))
    }


@lru_cache(maxsize=256)
def resolve_journal_issns(journal_name: str, mailto: str = "") -> tuple[str, ...]:
    normalized = journal_name.casefold().strip()
    cache = _load_issn_cache()
    if normalized in cache:
        return tuple(cache[normalized])

    params: dict[str, Any] = {"query": journal_name, "rows": 5}
    if mailto:
        params["mailto"] = mailto
    try:
        data = _request_json("/journals", params)
    except requests.RequestException:
        return tuple()

    items = data.get("message", {}).get("items", [])
    issns: list[str] = []
    for item in items:
        title = str(item.get("title") or "").casefold().strip()
        if title == normalized or normalized in [str(v).casefold().strip() for v in item.get("subjects", [])]:
            issns = _issns_from_item(item)
            break
    if not issns and items:
        issns = _issns_from_item(items[0])

    if issns:
        cache[normalized] = issns
        _save_issn_cache(cache)
    return tuple(issns)


def _issns_from_item(item: dict[str, Any]) -> list[str]:
    values = []
    for key in ["ISSN", "issn-type"]:
        raw = item.get(key, [])
        if key == "issn-type":
            values.extend(entry.get("value", "") for entry in raw if isinstance(entry, dict))
        elif isinstance(raw, list):
            values.extend(str(value) for value in raw)
    return _dedupe(values)


def _parse_crossref_article(item: dict[str, Any]) -> Article:
    doi = _clean_text(item.get("DOI") or "")
    title = _first(item.get("title"))
    journal = _first(item.get("container-title"))
    authors = [_author_name(author) for author in item.get("author", []) if _author_name(author)]
    publication_date = _published_date(item)
    doi_url = f"https://doi.org/{quote(doi)}" if doi else _clean_text(item.get("URL") or "")
    pdf_url = _pdf_url(item)

    return Article(
        title=title,
        journal=journal,
        first_author=authors[0] if authors else "",
        authors=authors,
        corresponding_authors=[authors[-1]] if authors else [],
        corresponding_author=authors[-1] if authors else "",
        corresponding_inferred=True,
        doi=doi,
        doi_url=doi_url,
        publication_date=publication_date,
        article_type=_clean_text(item.get("type") or "article"),
        abstract=_clean_abstract(item.get("abstract") or ""),
        is_oa=bool(pdf_url),
        pdf_url=pdf_url,
        landing_page_url=_clean_text(item.get("URL") or doi_url),
    )


def _published_date(item: dict[str, Any]) -> str:
    for key in ["published-online", "published-print", "published"]:
        date_parts = (item.get(key) or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            parts = [int(part) for part in date_parts[0]]
            year = parts[0]
            month = parts[1] if len(parts) > 1 else 1
            day = parts[2] if len(parts) > 2 else 1
            return date(year, month, day).isoformat()
    return ""


def _author_name(author: dict[str, Any]) -> str:
    given = _clean_text(author.get("given") or "")
    family = _clean_text(author.get("family") or "")
    name = _clean_text(author.get("name") or "")
    return " ".join(part for part in [given, family] if part) or name


def _pdf_url(item: dict[str, Any]) -> str:
    for link in item.get("link", []) or []:
        url = str(link.get("URL") or "")
        content_type = str(link.get("content-type") or "").casefold()
        if "pdf" in content_type or url.casefold().endswith(".pdf"):
            return url
    return ""


def _request_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    mailto = (params.pop("mailto", "") or DEFAULT_MAILTO).strip()
    params = {"mailto": mailto, **params}
    cache_path = _response_cache_path(path, params)
    cached = _load_response_cache(cache_path)
    if cached is not None:
        return cached

    last_error: requests.RequestException | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            response = requests.get(
                f"{CROSSREF_API}{path}",
                params=params,
                headers=_headers_for_mailto(mailto),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 429 and attempt < REQUEST_RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            data = response.json()
            _save_response_cache(cache_path, data)
            return data
        except requests.RequestException as error:
            last_error = error
            if attempt < REQUEST_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Crossref request failed")


def _headers_for_mailto(mailto: str) -> dict[str, str]:
    return {"User-Agent": f"Nature-track/1.0 (mailto:{mailto})"}


def _per_journal_rows(query: ArticleQuery) -> int:
    journal_count = max(len(query.journals), 1)
    return min(max((query.max_results // journal_count) + 8, 12), 60)


def _format_request_error(error: requests.RequestException) -> str:
    message = str(error).strip()
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None):
        status = f"HTTP {response.status_code}"
        return f"{status} ({message})" if message and message != status else status
    return message or error.__class__.__name__


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


def _load_issn_cache(path: Path = ISSN_CACHE_PATH) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): [str(value) for value in values] for key, values in data.items() if isinstance(values, list)}


def _save_issn_cache(cache: dict[str, list[str]], path: Path = ISSN_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def _article_key(article: Article) -> str:
    doi = article.doi.casefold().strip()
    if doi:
        return f"doi:{doi}"
    return "|".join([article.title.casefold().strip(), article.journal.casefold().strip(), article.publication_date])


def _clean_abstract(value: str) -> str:
    text = re.sub(r"</?jats:[^>]+>", " ", value)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(value))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _first(value: Any) -> str:
    if isinstance(value, list):
        return _clean_text(value[0]) if value else ""
    return _clean_text(value or "")


def _dedupe(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = str(value).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
