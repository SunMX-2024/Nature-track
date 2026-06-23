from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Callable

import requests

from nature_track.filters import openalex_search_text, parse_keyword_query
from nature_track.crossref import fetch_crossref_articles, fetch_crossref_articles_with_diagnostics
from nature_track.openalex import Article, ArticleQuery, fetch_articles


MAX_ANY_REMOTE_SEARCHES = 12
MAX_ANY_REMOTE_PAGES = 2
FALLBACK_MAX_PAGES = 8
REMOTE_ANY_TERM_LIMIT = 2
DEFAULT_PROVIDER = "multi"


@dataclass(frozen=True)
class CandidateSearchResult:
    articles: list[Article]
    warnings: list[str]


def candidate_search_texts(keywords: str, match_mode: str) -> list[str]:
    query = parse_keyword_query(keywords)
    terms = _dedupe(
        term
        for group in query.include_groups
        for term in group
    )

    if not terms:
        return [""]

    if match_mode == "any":
        if len(terms) > REMOTE_ANY_TERM_LIMIT:
            return [""]
        return terms[:MAX_ANY_REMOTE_SEARCHES]

    return [openalex_search_text(keywords)]


def fetch_candidate_articles(
    query: ArticleQuery,
    keywords: str,
    match_mode: str,
    fetch_func: Callable[[ArticleQuery], list[Article]] | None = None,
) -> list[Article]:
    return fetch_candidate_articles_with_diagnostics(query, keywords, match_mode, fetch_func).articles


def fetch_candidate_articles_with_diagnostics(
    query: ArticleQuery,
    keywords: str,
    match_mode: str,
    fetch_func: Callable[[ArticleQuery], list[Article]] | None = None,
) -> CandidateSearchResult:
    if fetch_func is None:
        return _fetch_default_candidate_articles_with_diagnostics(query, keywords, match_mode)

    fetch_func = fetch_func or fetch_multi_provider_articles
    search_texts = candidate_search_texts(keywords, match_mode)
    if len(search_texts) == 1:
        search_text = search_texts[0]
        if keywords.strip() and not search_text:
            articles, error = _fallback_fetch(fetch_func, query)
            warnings = _warning_for_error("journal/date candidate fetch", error)
            if articles:
                warnings.append(
                    "Many keyword concepts detected; using one broader journal/date candidate fetch with local keyword filtering."
                )
            return CandidateSearchResult(articles, warnings)
        articles, error = _fetch_with_error(fetch_func, replace(query, keywords=search_text))
        warnings = _warning_for_error(search_text, error)
        if keywords.strip() and (error or not articles):
            fallback, fallback_error = _fallback_fetch(fetch_func, query)
            warnings.extend(_warning_for_error("unfiltered fallback", fallback_error))
            if fallback:
                warnings.append(
                    "OpenAlex keyword search returned no usable candidates; using broader journal/date candidates with local keyword filtering."
                )
                return CandidateSearchResult(fallback, warnings)
        return CandidateSearchResult(articles, warnings)

    candidates: list[Article] = []
    seen = set()
    warnings: list[str] = []
    pages = max(1, min(query.max_pages, MAX_ANY_REMOTE_PAGES))
    for search_text in search_texts:
        search_query = replace(query, keywords=search_text, max_pages=pages)
        articles, error = _fetch_with_error(fetch_func, search_query)
        warnings.extend(_warning_for_error(search_text, error))
        for article in articles:
            key = _article_key(article)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(article)

    if keywords.strip() and not candidates:
        fallback, fallback_error = _fallback_fetch(fetch_func, query)
        warnings.extend(_warning_for_error("unfiltered fallback", fallback_error))
        if fallback:
            warnings.append(
                "OpenAlex keyword search returned no usable candidates; using broader journal/date candidates with local keyword filtering."
            )
            candidates = fallback

    return CandidateSearchResult(
        sorted(candidates, key=lambda article: article.publication_date, reverse=True),
        warnings,
    )


def _fetch_default_candidate_articles_with_diagnostics(
    query: ArticleQuery,
    keywords: str,
    match_mode: str,
) -> CandidateSearchResult:
    crossref_result = fetch_crossref_articles_with_diagnostics(replace(query, keywords=""))
    openalex_result = _fetch_provider_candidates(query, keywords, match_mode, fetch_articles, "OpenAlex")

    articles = _merge_articles([crossref_result.articles, openalex_result.articles])
    warnings = [
        *(f"Crossref: {warning}" for warning in crossref_result.warnings),
        *openalex_result.warnings,
    ]

    if crossref_result.articles:
        warnings.append(f"Crossref supplied {len(crossref_result.articles)} journal/date candidates.")
    if openalex_result.articles:
        warnings.append(f"OpenAlex supplied {len(openalex_result.articles)} supplemental candidates.")
    if crossref_result.articles and any("HTTP 429" in warning for warning in openalex_result.warnings):
        warnings.append("OpenAlex is rate-limited; continuing with Crossref candidates.")

    return CandidateSearchResult(articles, warnings)


def _fetch_provider_candidates(
    query: ArticleQuery,
    keywords: str,
    match_mode: str,
    fetch_func: Callable[[ArticleQuery], list[Article]],
    provider_name: str,
) -> CandidateSearchResult:
    result = fetch_candidate_articles_with_diagnostics(query, keywords, match_mode, fetch_func)
    return CandidateSearchResult(
        result.articles,
        [
            warning if warning.startswith(provider_name) else warning.replace("OpenAlex", provider_name, 1)
            for warning in result.warnings
        ],
    )


def fetch_multi_provider_articles(query: ArticleQuery) -> list[Article]:
    return _merge_articles([
        _safe_fetch(fetch_crossref_articles, query),
        _safe_fetch(fetch_articles, query),
    ])


def _merge_articles(groups: list[list[Article]]) -> list[Article]:
    articles: list[Article] = []
    seen = set()
    for group in groups:
        for article in group:
            key = _article_key(article)
            if key in seen:
                continue
            seen.add(key)
            articles.append(article)
    return sorted(articles, key=lambda article: article.publication_date, reverse=True)


def _safe_fetch(fetch_func: Callable[[ArticleQuery], list[Article]], query: ArticleQuery) -> list[Article]:
    articles, _ = _fetch_with_error(fetch_func, query)
    return articles


def _fetch_with_error(
    fetch_func: Callable[[ArticleQuery], list[Article]],
    query: ArticleQuery,
) -> tuple[list[Article], str]:
    try:
        return fetch_func(query), ""
    except requests.RequestException as error:
        return [], _format_request_error(error)


def _fallback_fetch(
    fetch_func: Callable[[ArticleQuery], list[Article]],
    query: ArticleQuery,
) -> tuple[list[Article], str]:
    fallback_pages = max(query.max_pages, min(FALLBACK_MAX_PAGES, max(query.max_pages, 1) + 2))
    return _fetch_with_error(fetch_func, replace(query, keywords="", max_pages=fallback_pages))


def _warning_for_error(search_text: str, error: str) -> list[str]:
    if not error:
        return []
    label = search_text or "all records"
    return [f"OpenAlex search failed for '{label}': {error}"]


def _format_request_error(error: requests.RequestException) -> str:
    message = str(error).strip()
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None):
        status = f"HTTP {response.status_code}"
        return f"{status} ({message})" if message and message != status else status
    return message or error.__class__.__name__


def _article_key(article: Article) -> str:
    doi = article.doi.casefold().strip()
    if doi:
        return f"doi:{doi}"
    return "|".join(
        [
            article.title.casefold().strip(),
            article.journal.casefold().strip(),
            article.publication_date,
        ]
    )


def _dedupe(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = str(value).strip().casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
