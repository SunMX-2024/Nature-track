from __future__ import annotations

import unittest

from nature_track.crossref import _load_issn_cache, _parse_crossref_article, _published_date


class CrossrefTests(unittest.TestCase):
    def test_parse_crossref_article_maps_core_fields(self) -> None:
        item = {
            "DOI": "10.1038/example",
            "URL": "https://doi.org/10.1038/example",
            "title": ["Protected areas increase forest carbon"],
            "container-title": ["Nature Climate Change"],
            "published-online": {"date-parts": [[2026, 2, 3]]},
            "type": "journal-article",
            "abstract": "<jats:p>Protected areas increased forest carbon.</jats:p>",
            "author": [{"given": "Ada", "family": "Lovelace"}, {"given": "Grace", "family": "Hopper"}],
            "link": [{"URL": "https://example.org/paper.pdf", "content-type": "application/pdf"}],
        }

        article = _parse_crossref_article(item)

        self.assertEqual(article.doi, "10.1038/example")
        self.assertEqual(article.title, "Protected areas increase forest carbon")
        self.assertEqual(article.journal, "Nature Climate Change")
        self.assertEqual(article.publication_date, "2026-02-03")
        self.assertEqual(article.authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(article.corresponding_author, "Grace Hopper")
        self.assertEqual(article.pdf_url, "https://example.org/paper.pdf")
        self.assertEqual(article.abstract, "Protected areas increased forest carbon.")

    def test_published_date_defaults_missing_month_day(self) -> None:
        self.assertEqual(_published_date({"published": {"date-parts": [[2026]]}}), "2026-01-01")

    def test_load_issn_cache_normalizes_values(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "crossref_issns.json"
            cache_path.write_text('{"nature": ["0028-0836"]}', encoding="utf-8")

            self.assertEqual(_load_issn_cache(cache_path), {"nature": ["0028-0836"]})


if __name__ == "__main__":
    unittest.main()
