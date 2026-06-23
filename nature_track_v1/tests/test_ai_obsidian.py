from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nature_track.ai_summary import DeepSeekSettings, _request_payload
from nature_track.fulltext import FullTextResult, extract_html_text
from nature_track.obsidian import obsidian_open_uri, paper_notes, write_obsidian_note
from nature_track.openalex import Article


def article() -> Article:
    return Article(
        title="Protected areas increase forest carbon",
        journal="Nature Climate Change",
        first_author="A",
        authors=["A", "B"],
        corresponding_authors=["B"],
        corresponding_author="B",
        corresponding_inferred=False,
        doi="10.1038/test",
        doi_url="https://doi.org/10.1038/test",
        publication_date="2026-01-01",
        article_type="article",
        abstract="Protected areas increased forest carbon in tropical forests.",
        is_oa=True,
        pdf_url="",
        landing_page_url="https://example.org/paper",
        topics=["Conservation"],
        concepts=["Forests"],
        keywords=["protected area"],
    )


class AiObsidianTests(unittest.TestCase):
    def test_extract_html_text_prefers_article_body(self) -> None:
        html = """
        <html><body>
          <nav>Navigation</nav>
          <article>
            <h1>Title</h1>
            <p>Introduction text.</p>
            <p>Methods text.</p>
            <p>Results text.</p>
          </article>
        </body></html>
        """

        text = extract_html_text(html)

        self.assertIn("Introduction text.", text)
        self.assertIn("Methods text.", text)
        self.assertNotIn("Navigation", text)

    def test_deepseek_payload_requests_json_graph_terms(self) -> None:
        full_text = FullTextResult(
            status="full_text",
            source_type="html",
            source_url="https://example.org/paper",
            text="Introduction. Methods. Results. Discussion.",
            message="ok",
        )

        payload = _request_payload(article(), full_text, DeepSeekSettings(api_key="secret"))

        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "max")
        user_text = payload["messages"][1]["content"]
        self.assertIn("Heilmeier", user_text)
        self.assertIn("q1_trying_to_do", user_text)
        self.assertIn("q7_experiments_results", user_text)
        self.assertIn("What are you trying to do?", user_text)
        self.assertIn("graph_terms", user_text)
        self.assertIn("topics, methods, data, journal", user_text)

    def test_obsidian_writer_creates_linked_paper_and_term_notes(self) -> None:
        summary = {
            "confidence": "high",
            "heilmeier": {
                "q1_trying_to_do": {
                    "lead": "The paper asks whether protected areas help forests store more carbon.",
                    "details": ["It frames protected areas as a conservation intervention."],
                },
                "q2_problem_current_limits": {
                    "lead": "Protected-area effectiveness is difficult to separate from background forest change.",
                    "details": ["The supplied text contrasts protected and comparable unprotected forests."],
                },
                "q3_new_approach_method": {
                    "lead": "The paper uses remote-sensing trend analysis to compare carbon outcomes.",
                    "details": ["No explicit equation is supplied in the test text."],
                },
                "q4_who_cares_impact": {
                    "lead": "Conservation planners care because carbon benefits can support protected-area policy.",
                    "details": ["My analysis is, the note is relevant to protected-area effectiveness."],
                },
                "q5_risks": {
                    "lead": "The main risk is attribution uncertainty.",
                    "details": ["Short observation periods can miss delayed effects."],
                },
                "q6_cost": {
                    "lead": "The cost is mainly remote-sensing data processing and reproducible analysis effort.",
                    "details": ["No compute cost is supplied in the test text."],
                },
                "q7_experiments_results": {
                    "lead": "The headline result is that protection improved carbon outcomes.",
                    "details": ["The test text does not supply benchmark metrics."],
                },
            },
            "evidence_quotes": ["protected areas increased forest carbon"],
            "graph_terms": {
                "topics": ["protected area", "forest"],
                "methods": ["remote-sensing trend analysis"],
                "data": ["tree cover"],
                "journal": ["Nature Climate Change"],
            },
        }
        full_text = FullTextResult(
            status="full_text",
            source_type="html",
            source_url="https://example.org/paper",
            text="Introduction. Methods. Results. Discussion.",
            message="Publisher HTML was read.",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            note_path = write_obsidian_note(article(), summary, full_text, tmpdir)
            note = Path(note_path).read_text(encoding="utf-8")

            self.assertTrue(note_path.exists())
            self.assertIn("## 1. What are you trying to do?", note)
            self.assertIn("## 7. What are the experiments and results?", note)
            self.assertIn("The paper asks whether protected areas help forests store more carbon.", note)
            self.assertIn("[[Nature-track/Topics/protected area|protected area]]", note)
            self.assertIn("[[Nature-track/Methods/remote-sensing trend analysis|remote-sensing trend analysis]]", note)
            self.assertTrue((Path(tmpdir) / "Nature-track" / "Data" / "tree cover.md").exists())
            self.assertTrue((Path(tmpdir) / "Nature-track" / "Journals" / "Nature Climate Change.md").exists())

    def test_obsidian_open_uri_and_paper_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            note = vault / "Nature-track" / "Papers" / "2026 - Test paper.md"
            note.parent.mkdir(parents=True)
            note.write_text("# Test paper\n", encoding="utf-8")

            uri = obsidian_open_uri(note, vault)
            notes = paper_notes(str(vault))

        self.assertIn("obsidian://open?", uri)
        self.assertIn("vault=", uri)
        self.assertIn("Nature-track/Papers/2026%20-%20Test%20paper.md", uri)
        self.assertEqual([path.name for path in notes], ["2026 - Test paper.md"])


if __name__ == "__main__":
    unittest.main()
