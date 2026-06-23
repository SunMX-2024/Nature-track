from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from nature_track.openalex import Article


def article(title: str, abstract: str) -> Article:
    return Article(
        title=title,
        journal="Global Change Biology",
        first_author="A",
        authors=["A"],
        corresponding_authors=["A"],
        corresponding_author="A",
        corresponding_inferred=False,
        doi="10.1/test",
        doi_url="https://doi.org/10.1/test",
        publication_date="2026-01-01",
        article_type="article",
        abstract=abstract,
        is_oa=True,
        pdf_url="https://example.org/paper.pdf",
        landing_page_url="https://example.org/paper",
    )


class ApiTests(unittest.TestCase):
    def test_health(self) -> None:
        client = TestClient(app)

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_search_uses_candidate_fetch(self) -> None:
        from nature_track.search import CandidateSearchResult

        def fake_fetch_candidate_articles(query, keywords, match_mode):
            self.assertEqual(keywords, "forest")
            self.assertEqual(match_mode, "any")
            return CandidateSearchResult(
                [article("Forest carbon", "Forest carbon gains increased in protected areas.")],
                ["Crossref supplied 1 journal/date candidates."],
            )

        client = TestClient(app)
        with patch("api.main.fetch_candidate_articles_with_diagnostics", fake_fetch_candidate_articles):
            response = client.post(
                "/search",
                json={
                    "journals": ["Global Change Biology"],
                    "keywords": "forest",
                    "keyword_match": "any",
                    "keyword_scope": "abstract",
                    "article_types": ["article"],
                    "days_back": 30,
                    "max_results": 10,
                    "require_abstract": True,
                    "research_only": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["candidate_count"], 1)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["articles"][0]["keyword_hits"], 1)
        self.assertEqual(body["warnings"], ["Crossref supplied 1 journal/date candidates."])


if __name__ == "__main__":
    unittest.main()
