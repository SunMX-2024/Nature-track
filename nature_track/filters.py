from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class KeywordQuery:
    include_groups: list[list[str]]
    exclude_terms: list[str]


def parse_keyword_terms(value: str) -> list[str]:
    query = parse_keyword_query(value)
    return [
        term.casefold()
        for group in query.include_groups
        for term in group
        if term.strip()
    ]


def parse_keyword_query(value: str) -> KeywordQuery:
    include_groups: list[list[str]] = []
    exclude_terms: list[str] = []
    chunks = re.split(r"\n|,|;|\s+\bAND\b\s+", value, flags=re.IGNORECASE)

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        is_exclude = False
        if re.match(r"^(NOT|-)\s*", chunk, flags=re.IGNORECASE):
            is_exclude = True
            chunk = re.sub(r"^(NOT|-)\s*", "", chunk, flags=re.IGNORECASE).strip()

        alternatives = [
            _normalize_keyword_term(part)
            for part in re.split(r"\s+\bOR\b\s+|\|", chunk, flags=re.IGNORECASE)
        ]
        alternatives = [term for term in alternatives if term]
        if not alternatives:
            continue
        if is_exclude:
            exclude_terms.extend(alternatives)
        else:
            include_groups.append(alternatives)

    return KeywordQuery(include_groups=include_groups, exclude_terms=exclude_terms)


def filter_articles_by_abstract(
    articles: list[Article],
    keywords: str,
    match_mode: str = "all",
    scope: str = "abstract",
) -> list[Article]:
    query = parse_keyword_query(keywords)
    if not query.include_groups and not query.exclude_terms:
        return articles

    ranked: list[tuple[int, Article]] = []
    for article in articles:
        search_text = _search_text(article, scope)
        if not search_text:
            continue

        if any(_term_matches(term, search_text) for term in query.exclude_terms):
            continue

        if not query.include_groups:
            ranked.append((0, article))
            continue

        matches = [
            any(_term_matches(term, search_text) for term in alternatives)
            for alternatives in query.include_groups
        ]
        if match_mode == "any" and any(matches):
            ranked.append((sum(matches), article))
        elif match_mode != "any" and all(matches):
            ranked.append((sum(matches), article))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [article for _, article in ranked]


def keyword_hit_count(article: Article, keywords: str, scope: str = "abstract") -> int:
    query = parse_keyword_query(keywords)
    search_text = _search_text(article, scope)
    if not search_text or any(_term_matches(term, search_text) for term in query.exclude_terms):
        return 0
    return sum(
        any(_term_matches(term, search_text) for term in alternatives)
        for alternatives in query.include_groups
    )


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


def _normalize_keyword_term(value: str) -> str:
    term = value.strip()
    if len(term) >= 2 and term[0] == term[-1] and term[0] in {"'", '"'}:
        term = term[1:-1]
    if len(term) >= 2 and ((term[0], term[-1]) == ("{", "}") or (term[0], term[-1]) == ("(", ")")):
        term = term[1:-1]
    return re.sub(r"\s+", " ", term).strip()


def _search_text(article: Article, scope: str) -> str:
    if scope == "title":
        values = [article.title]
    elif scope == "title_abstract":
        values = [article.title, article.abstract]
    else:
        values = [article.abstract]
    return "\n".join(value for value in values if value).casefold()


def _term_matches(term: str, text: str) -> bool:
    pattern = _term_pattern(term)
    return bool(pattern.search(text))


def _term_pattern(term: str) -> re.Pattern[str]:
    parts = re.split(r"\s+", term.casefold())
    escaped_parts = [re.escape(part).replace(r"\*", r"[\w-]*") for part in parts if part]
    body = r"\s+".join(escaped_parts)
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", flags=re.IGNORECASE)
