from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import requests

from nature_track.filters import filter_articles_by_abstract, openalex_search_text, parse_keyword_terms
from nature_track.openalex import Article, ArticleQuery
from nature_track.config import load_settings, save_settings
from nature_track.search import (
    candidate_search_texts,
    fetch_candidate_articles,
    fetch_candidate_articles_with_diagnostics,
    fetch_multi_provider_articles,
)
from nature_track.usage import frequent_keyword_entries, record_keywords


def article(title: str, abstract: str, doi: str = "", publication_date: str = "2026-01-01") -> Article:
    return Article(
        title=title,
        journal="Global Change Biology",
        first_author="A",
        authors=["A"],
        corresponding_authors=["A"],
        corresponding_author="A",
        corresponding_inferred=False,
        doi=doi,
        doi_url="",
        publication_date=publication_date,
        article_type="article",
        abstract=abstract,
        is_oa=False,
        pdf_url="",
        landing_page_url="",
    )


class KeywordTests(unittest.TestCase):
    def test_keyword_query_parses_lines_or_and_not_terms(self) -> None:
        query = "protected area OR conservation area\nNOT crop"

        self.assertEqual(parse_keyword_terms(query), ["protected area", "conservation area"])
        self.assertEqual(openalex_search_text(query), "protected area conservation area")

    def test_openalex_search_text_deduplicates_terms(self) -> None:
        query = "forest\nprotected area\nforest"

        self.assertEqual(openalex_search_text(query), "forest protected area")

    def test_candidate_searches_use_each_keyword_for_any_mode(self) -> None:
        query = "grassland\nforest"

        self.assertEqual(candidate_search_texts(query, "any"), ["grassland", "forest"])
        self.assertEqual(candidate_search_texts(query, "all"), ["grassland forest"])

    def test_many_any_keywords_use_broad_single_candidate_fetch(self) -> None:
        query = "grassland\nforest\nprotected area"

        self.assertEqual(candidate_search_texts(query, "any"), [""])

    def test_fetch_candidate_articles_merges_any_mode_remote_results(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=5,
        )
        calls = []

        def fake_fetch(query: ArticleQuery) -> list[Article]:
            calls.append((query.keywords, query.max_pages))
            if query.keywords == "forest":
                return [
                    article("A", "Forest carbon gains.", doi="10.1/a", publication_date="2026-01-02"),
                    article("B", "Forest edge effects.", doi="10.1/b", publication_date="2026-01-01"),
                ]
            if query.keywords == "grassland":
                return [
                    article("A duplicate", "Duplicate DOI.", doi="10.1/a", publication_date="2026-01-02"),
                    article("C", "Grassland productivity.", doi="10.1/c", publication_date="2025-12-31"),
                ]
            return []

        results = fetch_candidate_articles(base_query, "forest\ngrassland", "any", fake_fetch)

        self.assertEqual(calls, [("forest", 2), ("grassland", 2)])
        self.assertEqual([item.doi for item in results], ["10.1/a", "10.1/b", "10.1/c"])

    def test_many_any_keywords_fetch_once_without_remote_keyword_search(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=5,
        )
        calls = []

        def fake_fetch(query: ArticleQuery) -> list[Article]:
            calls.append((query.keywords, query.max_pages))
            return [
                article("A", "Forest carbon gains.", doi="10.1/a", publication_date="2026-01-02"),
                article("B", "Protected areas improved biodiversity.", doi="10.1/b", publication_date="2026-01-01"),
            ]

        result = fetch_candidate_articles_with_diagnostics(
            base_query,
            "forest\nprotected area\nbiodiversity",
            "any",
            fake_fetch,
        )

        self.assertEqual(calls, [("", 7)])
        self.assertEqual([item.doi for item in result.articles], ["10.1/a", "10.1/b"])
        self.assertTrue(any("Many keyword concepts" in warning for warning in result.warnings))

    def test_multi_provider_merges_crossref_and_openalex_results(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=5,
        )
        calls = []

        def fake_crossref(query: ArticleQuery) -> list[Article]:
            calls.append(("crossref", query.keywords))
            return [
                article("A", "Crossref forest article.", doi="10.1/a", publication_date="2026-01-02"),
                article("B", "Crossref grassland article.", doi="10.1/b", publication_date="2026-01-01"),
            ]

        def fake_openalex(query: ArticleQuery) -> list[Article]:
            calls.append(("openalex", query.keywords))
            return [
                article("B duplicate", "Duplicate DOI.", doi="10.1/b", publication_date="2026-01-01"),
                article("C", "OpenAlex protected area article.", doi="10.1/c", publication_date="2025-12-31"),
            ]

        import nature_track.search as search_module

        original_crossref = search_module.fetch_crossref_articles
        original_openalex = search_module.fetch_articles
        try:
            search_module.fetch_crossref_articles = fake_crossref
            search_module.fetch_articles = fake_openalex
            results = fetch_multi_provider_articles(base_query)
        finally:
            search_module.fetch_crossref_articles = original_crossref
            search_module.fetch_articles = original_openalex

        self.assertEqual([item.doi for item in results], ["10.1/a", "10.1/b", "10.1/c"])
        self.assertEqual(calls, [("crossref", ""), ("openalex", "")])

    def test_fetch_candidate_articles_keeps_results_when_one_any_query_times_out(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=5,
        )

        def fake_fetch(query: ArticleQuery) -> list[Article]:
            if query.keywords == "forest":
                raise requests.Timeout("timeout")
            return [article("C", "Grassland productivity.", doi="10.1/c", publication_date="2025-12-31")]

        results = fetch_candidate_articles(base_query, "forest\ngrassland", "any", fake_fetch)

        self.assertEqual([item.doi for item in results], ["10.1/c"])

    def test_fetch_candidate_articles_falls_back_when_keyword_search_fails(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=2,
        )
        calls = []

        def fake_fetch(query: ArticleQuery) -> list[Article]:
            calls.append(query.keywords)
            if query.keywords:
                raise requests.HTTPError("HTTP 429")
            return [
                article("A", "Protected areas increased forest carbon.", doi="10.1/a"),
                article("B", "Grassland productivity changed.", doi="10.1/b"),
            ]

        result = fetch_candidate_articles_with_diagnostics(base_query, "protected area", "all", fake_fetch)
        matches = filter_articles_by_abstract(result.articles, "protected area", "all", "abstract")

        self.assertEqual(calls, ["protected area", ""])
        self.assertEqual([item.doi for item in matches], ["10.1/a"])
        self.assertTrue(any("broader journal/date candidates" in warning for warning in result.warnings))

    def test_fetch_candidate_articles_falls_back_when_keyword_search_returns_empty(self) -> None:
        base_query = ArticleQuery(
            journals=["Global Change Biology"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            max_results=20,
            max_pages=2,
        )
        calls = []

        def fake_fetch(query: ArticleQuery) -> list[Article]:
            calls.append(query.keywords)
            if query.keywords:
                return []
            return [article("A", "Protected areas increased forest carbon.", doi="10.1/a")]

        result = fetch_candidate_articles(base_query, "protected area", "all", fake_fetch)

        self.assertEqual(calls, ["protected area", ""])
        self.assertEqual([item.doi for item in result], ["10.1/a"])

    def test_any_all_and_not_filtering(self) -> None:
        articles = [
            article("A", "Protected areas increased forest carbon in tropical reserves."),
            article("B", "Protected areas changed crop yields near farms."),
            article("C", "Forest carbon changed without conservation language."),
        ]

        all_matches = filter_articles_by_abstract(articles, "protected area\nforest\nNOT crop", "all", "abstract")
        any_matches = filter_articles_by_abstract(articles, "protected area\nforest\nNOT crop", "any", "abstract")

        self.assertEqual([item.title for item in all_matches], ["A"])
        self.assertEqual([item.title for item in any_matches], ["A", "C"])

    def test_phrase_matching_accepts_plural_and_hyphen_variants(self) -> None:
        articles = [
            article("A", "Forest carbon gains increased inside protected areas."),
            article("B", "A protected-area network changed land use."),
            article("C", "Protection without the target phrase."),
        ]

        matches = filter_articles_by_abstract(articles, "protected area", "all", "abstract")

        self.assertEqual([item.title for item in matches], ["A", "B"])

    def test_keyword_memory_merges_legacy_counts_and_records_recent_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usage_path = Path(tmpdir) / "usage.json"
            usage_path.write_text(
                json.dumps({"keyword_counts": {"forest": 2, "grassland": 1}}),
                encoding="utf-8",
            )

            record_keywords(["Grassland", "protected area", ""], usage_path)
            entries = frequent_keyword_entries(10, usage_path)

        self.assertEqual(
            [(entry["term"], entry["count"]) for entry in entries[:3]],
            [("grassland", 2), ("forest", 2), ("protected area", 1)],
        )
        self.assertTrue(entries[0]["last_used_at"])

    def test_keyword_memory_sorts_by_count_then_recent_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usage_path = Path(tmpdir) / "usage.json"
            usage_path.write_text(
                json.dumps(
                    {
                        "keyword_memory": {
                            "forest": {"count": 3, "last_used_at": "2026-01-01 08:00"},
                            "grassland": {"count": 3, "last_used_at": "2026-01-02 08:00"},
                            "drought": {"count": 1, "last_used_at": "2026-01-03 08:00"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            entries = frequent_keyword_entries(10, usage_path)

        self.assertEqual([entry["term"] for entry in entries], ["grassland", "forest", "drought"])

    def test_saved_settings_keep_last_keyword_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            save_settings({"keywords": "protected area"}, settings_path)

            settings = load_settings(settings_path)

        self.assertEqual(settings["keywords"], "protected area")


if __name__ == "__main__":
    unittest.main()
