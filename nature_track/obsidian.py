from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from nature_track.ai_summary import HEILMEIER_SECTIONS
from nature_track.fulltext import FullTextResult
from nature_track.openalex import Article


GRAPH_GROUPS = {
    "topics": "Topics",
    "methods": "Methods",
    "data": "Data",
    "journal": "Journals",
}


def write_obsidian_note(
    article: Article,
    summary: dict[str, Any],
    full_text: FullTextResult,
    vault_path: str,
    root_folder: str = "Nature-track",
) -> Path:
    vault = Path(vault_path).expanduser()
    if not vault.exists() or not vault.is_dir():
        raise ValueError("Obsidian vault path does not exist or is not a folder.")

    root = vault / _clean_folder(root_folder or "Nature-track")
    papers_dir = root / "Papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    graph_terms = summary.get("graph_terms") if isinstance(summary.get("graph_terms"), dict) else {}
    links = {
        group: _write_term_notes(root, group, graph_terms.get(group, []))
        for group in GRAPH_GROUPS
    }

    note_path = papers_dir / _paper_filename(article)
    note_path.write_text(
        _render_paper_note(article, summary, full_text, links),
        encoding="utf-8",
    )
    return note_path


def obsidian_open_uri(note_path: str | Path, vault_path: str) -> str:
    vault = Path(vault_path).expanduser().resolve()
    note = Path(note_path).expanduser().resolve()
    try:
        relative = note.relative_to(vault).as_posix()
    except ValueError:
        relative = note.stem
    return f"obsidian://open?vault={quote(vault.name)}&file={quote(relative)}"


def paper_notes(vault_path: str, root_folder: str = "Nature-track") -> list[Path]:
    vault = Path(vault_path).expanduser()
    papers_dir = vault / _clean_folder(root_folder or "Nature-track") / "Papers"
    if not papers_dir.exists() or not papers_dir.is_dir():
        return []
    return sorted(
        papers_dir.glob("*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _write_term_notes(root: Path, group: str, terms: Any) -> list[str]:
    folder_name = GRAPH_GROUPS[group]
    folder = root / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    links: list[str] = []
    for term in _terms(terms):
        file_stem = _safe_filename(term)
        path = folder / f"{file_stem}.md"
        if not path.exists():
            path.write_text(_render_term_note(group, term), encoding="utf-8")
        links.append(f"[[{_wikilink_path(path, root.parent)}|{term}]]")
    return links


def _render_paper_note(
    article: Article,
    summary: dict[str, Any],
    full_text: FullTextResult,
    links: dict[str, list[str]],
) -> str:
    frontmatter = {
        "type": "paper",
        "doi": article.doi,
        "journal": article.journal,
        "publication_date": article.publication_date,
        "readable_status": full_text.status,
        "source_type": full_text.source_type,
        "source_url": full_text.source_url,
        "confidence": str(summary.get("confidence", "")),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    authors = "; ".join(article.authors[:12])
    return "\n".join(
        [
            _yaml(frontmatter),
            f"# {article.title or 'Untitled paper'}",
            "",
            f"**Journal:** {article.journal or 'Unknown'}",
            f"**Date:** {article.publication_date or 'Unknown'}",
            f"**DOI:** {article.doi_url or article.doi or 'Unknown'}",
            f"**Authors:** {authors or 'Unknown'}",
            f"**Readable source:** {full_text.message}",
            "",
            "## Graph",
            f"- Topics: {_join_links(links.get('topics', []))}",
            f"- Methods: {_join_links(links.get('methods', []))}",
            f"- Data: {_join_links(links.get('data', []))}",
            f"- Journal: {_join_links(links.get('journal', []))}",
            "",
            _render_heilmeier(summary),
            "",
            "## Evidence quotes",
            _bullets(summary.get("evidence_quotes", [])),
            "",
            "## Abstract",
            article.abstract or "No abstract available.",
            "",
        ]
    ).strip() + "\n"


def _render_heilmeier(summary: dict[str, Any]) -> str:
    heilmeier = summary.get("heilmeier") if isinstance(summary.get("heilmeier"), dict) else {}
    fallback = _legacy_heilmeier(summary)
    sections = []
    for index, (key, title) in enumerate(HEILMEIER_SECTIONS, start=1):
        value = heilmeier.get(key) or fallback.get(key)
        sections.append(f"## {index}. {title}\n{_render_heilmeier_answer(value)}")
    return "\n\n".join(sections)


def _legacy_heilmeier(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "q1_trying_to_do": summary.get("research_question") or _first(summary.get("story_line")),
        "q2_problem_current_limits": _clean_join(
            [
                summary.get("research_question"),
                _prefix("Study system", summary.get("study_system")),
                _prefix("Limits", summary.get("limitations")),
            ]
        ),
        "q3_new_approach_method": _clean_join(
            [
                _prefix("Methods", summary.get("methods")),
                _prefix("Data", summary.get("data")),
            ]
        ),
        "q4_who_cares_impact": summary.get("relevance_to_my_work"),
        "q5_risks": summary.get("limitations"),
        "q6_cost": "",
        "q7_experiments_results": summary.get("conclusions") or summary.get("story_line"),
    }


def _render_heilmeier_answer(value: Any) -> str:
    if isinstance(value, dict):
        lead = _clean_text(value.get("lead") or value.get("answer") or value.get("summary") or value.get("title"))
        details = _as_text_list(value.get("details") or value.get("bullets") or value.get("items"))
        extra = []
        for key, item in value.items():
            if key in {"lead", "answer", "summary", "title", "details", "bullets", "items"}:
                continue
            text = _clean_text(item)
            if text:
                extra.append(f"{key}: {text}")
        details.extend(extra)
    else:
        details = _as_text_list(value)
        lead = details.pop(0) if details else ""

    rows = [lead or "Not identified.", "", _bullets(details)]
    return "\n".join(rows).strip()


def _render_term_note(group: str, term: str) -> str:
    return "\n".join(
        [
            _yaml({"type": group.rstrip("s"), "created": datetime.now().strftime("%Y-%m-%d %H:%M")}),
            f"# {term}",
            "",
            "Linked papers will appear as backlinks in Obsidian.",
            "",
        ]
    )


def _yaml(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if value is None or value == "":
            continue
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def _bullets(items: Any) -> str:
    rows = [f"- {str(item).strip()}" for item in items if str(item).strip()] if isinstance(items, list) else []
    return "\n".join(rows) if rows else "- Not identified."


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value for text in _as_text_list(item)]
    text = _clean_text(value)
    return [text] if text else []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for key in ["name", "category", "evidence", "lead", "summary", "description"]:
            if value.get(key):
                parts.append(str(value[key]))
        if not parts:
            parts = [f"{key}: {item}" for key, item in value.items() if item]
        return " | ".join(part.strip() for part in parts if part and str(part).strip())
    if isinstance(value, list):
        return "; ".join(_as_text_list(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def _first(value: Any) -> str:
    items = _as_text_list(value)
    return items[0] if items else ""


def _prefix(label: str, value: Any) -> str:
    text = _clean_text(value)
    return f"{label}: {text}" if text else ""


def _clean_join(values: list[Any]) -> str:
    return " ".join(text for value in values if (text := _clean_text(value)))


def _join_links(links: list[str]) -> str:
    return ", ".join(links) if links else "Not identified"


def _terms(values: Any) -> list[str]:
    if isinstance(values, str):
        raw = [values]
    elif isinstance(values, list):
        raw = []
        for value in values:
            if isinstance(value, dict):
                raw.append(str(value.get("name") or value.get("term") or value.get("label") or ""))
            else:
                raw.append(str(value))
    else:
        raw = []

    seen = set()
    result = []
    for value in raw:
        term = re.sub(r"\s+", " ", value).strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(term)
    return result[:12]


def _paper_filename(article: Article) -> str:
    year = (article.publication_date or "0000")[:4] or "0000"
    base = f"{year} - {article.title or article.doi or 'Untitled paper'}"
    return f"{_safe_filename(base)[:150]}.md"


def _safe_filename(value: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', " ", value)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Untitled"


def _clean_folder(value: str) -> str:
    return str(Path(value.strip().strip("\\/")))


def _wikilink_path(path: Path, vault: Path) -> str:
    relative = path.relative_to(vault).with_suffix("")
    return relative.as_posix()
