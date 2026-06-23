from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nature_track.config import DEFAULT_SETTINGS, load_settings, save_settings
from nature_track.filters import (
    filter_article_quality,
    filter_articles_by_abstract,
    filter_search_results,
    keyword_hit_count,
    parse_keyword_terms,
)
from nature_track.openalex import Article, ArticleQuery
from nature_track.search import candidate_search_texts, fetch_candidate_articles_with_diagnostics


APP_NAME = "Nature-track API"
MAX_RESULTS_LIMIT = 200
ARTICLE_TYPES = ["article", "review", "letter", "editorial", "report", "book-chapter", "paratext", "other"]
KEYWORD_MATCH = ["all", "any"]
KEYWORD_SCOPE = ["abstract", "title_abstract", "title"]


app = FastAPI(title=APP_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    journals: list[str] = Field(default_factory=lambda: list(DEFAULT_SETTINGS["journals"]))
    keywords: str = ""
    keyword_match: str = Field(default="all", pattern="^(all|any)$")
    keyword_scope: str = Field(default="abstract", pattern="^(abstract|title_abstract|title)$")
    article_types: list[str] = Field(default_factory=lambda: ["article", "review"])
    days_back: int = Field(default=30, ge=1, le=3650)
    max_results: int = Field(default=30, ge=1, le=MAX_RESULTS_LIMIT)
    require_abstract: bool = True
    research_only: bool = True


class ArticleResponse(BaseModel):
    title: str
    journal: str
    doi: str
    doi_url: str
    publication_date: str
    article_type: str
    abstract: str
    authors: list[str]
    corresponding_authors: list[str]
    is_oa: bool
    pdf_url: str
    landing_page_url: str
    keyword_hits: int


class SearchResponse(BaseModel):
    count: int
    candidate_count: int
    query: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    articles: list[ArticleResponse]


class SettingsResponse(BaseModel):
    settings: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME}


@app.get("/options")
def options() -> dict[str, object]:
    return {
        "journals": _available_journals(),
        "article_types": ARTICLE_TYPES,
        "keyword_match": KEYWORD_MATCH,
        "keyword_scope": KEYWORD_SCOPE,
        "defaults": _public_settings(),
    }


@app.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return SettingsResponse(settings=_public_settings())


@app.put("/settings", response_model=SettingsResponse)
def put_settings(payload: SearchRequest) -> SettingsResponse:
    current = _merged_settings()
    updated = current | {
        "journals": payload.journals,
        "keywords": payload.keywords,
        "keyword_match": payload.keyword_match,
        "keyword_scope": payload.keyword_scope,
        "article_types": payload.article_types,
        "days_back": payload.days_back,
        "max_results": payload.max_results,
        "require_abstract": payload.require_abstract,
        "research_only": payload.research_only,
    }
    save_settings(updated)
    return SettingsResponse(settings=_public_settings(updated))


@app.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    end = date.today()
    start = end - timedelta(days=payload.days_back)
    query = ArticleQuery(
        journals=payload.journals,
        from_date=start,
        to_date=end,
        keywords="",
        article_types=payload.article_types,
        max_results=200,
        max_pages=max((payload.max_results // 20) + 2, 3),
        mailto=_merged_settings().get("openalex_mailto", ""),
    )
    search_result = fetch_candidate_articles_with_diagnostics(query, payload.keywords, payload.keyword_match)
    candidates = search_result.articles
    articles, filter_warnings = filter_search_results(
        candidates,
        payload.keywords,
        payload.keyword_match,
        payload.require_abstract,
        payload.research_only,
        payload.keyword_scope,
        search_result.warnings,
    )
    articles = articles[: payload.max_results]
    return SearchResponse(
        count=len(articles),
        candidate_count=len(candidates),
        query={
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
            "keywords": payload.keywords,
            "terms": parse_keyword_terms(payload.keywords),
            "candidate_searches": candidate_search_texts(payload.keywords, payload.keyword_match),
            "keyword_match": payload.keyword_match,
            "keyword_scope": payload.keyword_scope,
        },
        warnings=search_result.warnings + filter_warnings,
        articles=[_article_response(article, payload) for article in articles],
    )


def _article_response(article: Article, payload: SearchRequest) -> ArticleResponse:
    return ArticleResponse(
        title=article.title,
        journal=article.journal,
        doi=article.doi,
        doi_url=article.doi_url or article.landing_page_url,
        publication_date=article.publication_date,
        article_type=article.article_type,
        abstract=article.abstract,
        authors=article.authors,
        corresponding_authors=article.corresponding_authors,
        is_oa=article.is_oa,
        pdf_url=article.pdf_url,
        landing_page_url=article.landing_page_url,
        keyword_hits=keyword_hit_count(article, payload.keywords, payload.keyword_scope),
    )


def _merged_settings() -> dict[str, Any]:
    return DEFAULT_SETTINGS | load_settings()


def _public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings or _merged_settings()
    return {
        "journals": source.get("journals", DEFAULT_SETTINGS["journals"]),
        "keywords": source.get("keywords", ""),
        "keyword_match": source.get("keyword_match", "all"),
        "keyword_scope": source.get("keyword_scope", "abstract"),
        "article_types": source.get("article_types", DEFAULT_SETTINGS["article_types"]),
        "days_back": int(source.get("days_back", DEFAULT_SETTINGS["days_back"])),
        "max_results": int(source.get("max_results", DEFAULT_SETTINGS["max_results"])),
        "require_abstract": bool(source.get("require_abstract", True)),
        "research_only": bool(source.get("research_only", True)),
    }


def _available_journals() -> list[str]:
    settings = _merged_settings()
    journals: list[str] = []
    journals.extend(DEFAULT_SETTINGS["journals"])
    journals.extend(settings.get("journals", []))
    for group in settings.get("journal_groups", {}).values():
        if isinstance(group, list):
            journals.extend(str(journal) for journal in group)
    return _dedupe(journals)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
