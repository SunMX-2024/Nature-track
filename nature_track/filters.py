from __future__ import annotations

import re

from nature_track.openalex import Article


NON_RESEARCH_TITLE_PATTERNS = [
    r"^author correction:",
    r"^publisher correction:",
    r"^correction:",
    r"^retraction:",
    r"^books? in brief",
    r"^news",
    r"^career",
    r"^where i work",
]


def parse_keyword_terms(value: str) -> list[str]:
    raw_terms = re.split(r"\n|,|;|\s+OR\s+", value, flags=re.IGNORECASE)
    return [term.casefold().strip() for term in raw_terms if term.strip()]


def filter_articles_by_abstract(
    articles: list[Article],
    keywords: str,
    match_mode: str = "all",
) -> list[Article]:
    terms = parse_keyword_terms(keywords)
    if not terms:
        return articles

    filtered: list[Article] = []
    for article in articles:
        abstract = article.abstract.casefold()
        if not abstract:
            continue

        matches = [term in abstract for term in terms]
        if match_mode == "any" and any(matches):
            filtered.append(article)
        elif match_mode != "any" and all(matches):
            filtered.append(article)

    return filtered


def filter_article_quality(
    articles: list[Article],
    require_abstract: bool = True,
    research_only: bool = True,
) -> list[Article]:
    filtered: list[Article] = []
    for article in articles:
        if require_abstract and not article.abstract:
            continue
        if research_only and not _looks_research_like(article):
            continue
        filtered.append(article)
    return filtered


def _looks_research_like(article: Article) -> bool:
    if not article.abstract:
        return False

    title = article.title.casefold().strip()
    if any(re.search(pattern, title) for pattern in NON_RESEARCH_TITLE_PATTERNS):
        return False

    return len(article.abstract.split()) >= 60
