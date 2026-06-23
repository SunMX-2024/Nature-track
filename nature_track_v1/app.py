from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from html import escape
from itertools import groupby
import json
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from nature_track.ai_summary import DeepSeekSettings, summarize_article
from nature_track.config import DEFAULT_SETTINGS, load_settings, save_settings
from nature_track.downloads import download_article_pdf
from nature_track.emailer import EMAIL_PROVIDERS, EmailSettings, send_digest_email
from nature_track.filters import filter_article_quality, filter_articles_by_abstract
from nature_track.filters import filter_search_results
from nature_track.filters import keyword_hit_count
from nature_track.filters import parse_keyword_terms
from nature_track.fulltext import fetch_full_text
from nature_track.obsidian import obsidian_open_uri, paper_notes, write_obsidian_note
from nature_track.openalex import ArticleQuery
from nature_track.search import fetch_candidate_articles, fetch_candidate_articles_with_diagnostics
from nature_track.usage import (
    frequent_keyword_entries,
    load_usage,
    record_keywords,
    record_read_article,
    record_usage,
)


APP_TITLE = "Nature-track"
DEFAULT_JOURNALS = [
    "Nature",
    "Nature Geoscience",
    "Nature Climate Change",
    "Nature Communications",
    "Science",
    "Science Advances",
    "One Earth",
    "Global Change Biology",
]

JOURNAL_GROUPS = {
    "Nature family": [
        "Nature",
        "Nature Geoscience",
        "Nature Climate Change",
        "Nature Communications",
        "Nature Ecology & Evolution",
        "Nature Sustainability",
        "Nature Water",
    ],
    "Science family": ["Science", "Science Advances"],
    "Earth and environment": [
        "One Earth",
        "Global Change Biology",
        "Earth System Science Data",
        "Environmental Research Letters",
        "Geophysical Research Letters",
        "Journal of Geophysical Research: Biogeosciences",
        "Remote Sensing of Environment",
    ],
}

JOURNAL_BUTTON_LABELS = {
    "Nature Geoscience": "Geo",
    "Nature Climate Change": "Climate",
    "Nature Communications": "Comms",
    "Nature Ecology & Evolution": "E&E",
    "Nature Sustainability": "Sustain.",
    "Science Advances": "Advances",
    "Global Change Biology": "GCB",
    "Earth System Science Data": "ESSD",
    "Environmental Research Letters": "ERL",
    "Geophysical Research Letters": "GRL",
    "Journal of Geophysical Research: Biogeosciences": "JGR Bio",
    "Remote Sensing of Environment": "RSE",
}

JOURNAL_TAB_LABELS = {
    "Nature family": "Nature",
    "Science family": "Science",
    "Earth and environment": "Earth/env",
    "Custom": "Custom",
}

CUSTOM_JOURNAL_GROUP = "Custom"

ARTICLE_TYPES = [
    "article",
    "review",
    "letter",
    "editorial",
    "report",
    "book-chapter",
    "paratext",
    "other",
]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

TIME_WINDOW_UNITS = {
    "days": 1,
    "weeks": 7,
    "months": 30,
    "years": 365,
}

TIME_WINDOW_LABELS = {
    "days": "Days",
    "weeks": "Weeks",
    "months": "Months",
    "years": "Years",
}


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


def _default_journal_groups() -> dict[str, list[str]]:
    return {group: list(journals) for group, journals in JOURNAL_GROUPS.items()}


def _merge_journal_groups(saved_groups: dict | None, legacy_custom: list[str] | None = None) -> dict[str, list[str]]:
    groups = _default_journal_groups()
    for group, journals in (saved_groups or {}).items():
        if isinstance(journals, list):
            groups[str(group)] = _dedupe([str(journal) for journal in journals])
    legacy = _dedupe([str(journal) for journal in legacy_custom or []])
    if legacy:
        groups[CUSTOM_JOURNAL_GROUP] = _dedupe(groups.get(CUSTOM_JOURNAL_GROUP, []) + legacy)
    groups.setdefault(CUSTOM_JOURNAL_GROUP, [])
    return {group: journals for group, journals in groups.items() if group in JOURNAL_TAB_LABELS or journals}


def _valid_time_unit(unit: str | None) -> str:
    return unit if unit in TIME_WINDOW_UNITS else "days"


def _session_window_days(value_key: str, unit_key: str) -> int:
    value = max(1, int(st.session_state.get(value_key, 1)))
    unit = _valid_time_unit(st.session_state.get(unit_key))
    return min(value * TIME_WINDOW_UNITS[unit], 3650)


def _settings_payload() -> dict:
    openalex_mailto = st.session_state.openalex_mailto.strip() or st.session_state.sender.strip()
    return {
        "journals": st.session_state.selected_journals,
        "keywords": st.session_state.keywords.strip(),
        "keyword_match": st.session_state.keyword_match,
        "keyword_scope": st.session_state.keyword_scope,
        "custom_journals": st.session_state.custom_journals,
        "journal_groups": st.session_state.journal_groups,
        "active_journal_group": st.session_state.active_journal_group,
        "article_types": st.session_state.article_types,
        "require_abstract": st.session_state.require_abstract,
        "research_only": st.session_state.research_only,
        "download_dir": st.session_state.download_dir.strip(),
        "openalex_mailto": openalex_mailto,
        "deepseek": {
            "api_key": st.session_state.deepseek_api_key,
            "model": st.session_state.deepseek_model.strip() or "deepseek-v4-pro",
        },
        "obsidian": {
            "vault_path": st.session_state.obsidian_vault_path.strip(),
            "root_folder": st.session_state.obsidian_root_folder.strip() or "Nature-track",
        },
        "days_back": _session_window_days("window_value", "window_unit"),
        "window_value": st.session_state.window_value,
        "window_unit": st.session_state.window_unit,
        "max_results": st.session_state.max_results,
        "schedule": {
            "enabled": st.session_state.schedule_enabled,
            "frequency": st.session_state.schedule_frequency,
            "weekday": st.session_state.schedule_weekday,
            "time": st.session_state.schedule_time.strftime("%H:%M"),
        },
        "digest": {
            "journals": st.session_state.digest_journals,
            "keywords": st.session_state.digest_keywords.strip(),
            "keyword_match": st.session_state.digest_keyword_match,
            "keyword_scope": st.session_state.digest_keyword_scope,
            "custom_journals": st.session_state.digest_custom_journals,
            "journal_groups": st.session_state.digest_journal_groups,
            "article_types": st.session_state.digest_article_types,
            "require_abstract": st.session_state.digest_require_abstract,
            "research_only": st.session_state.digest_research_only,
            "days_back": _session_window_days("digest_window_value", "digest_window_unit"),
            "window_value": st.session_state.digest_window_value,
            "window_unit": st.session_state.digest_window_unit,
            "max_results": st.session_state.digest_max_results,
        },
        "email": {
            "provider": st.session_state.email_provider,
            "smtp_host": st.session_state.smtp_host.strip(),
            "smtp_port": st.session_state.smtp_port,
            "smtp_user": st.session_state.smtp_user.strip(),
            "smtp_password": st.session_state.smtp_password,
            "sender": st.session_state.sender.strip(),
            "recipient": st.session_state.recipient.strip(),
            "use_tls": st.session_state.use_tls,
        },
    }


def _openalex_mailto() -> str:
    return st.session_state.openalex_mailto.strip() or st.session_state.sender.strip()


def _save_current_settings() -> None:
    save_settings(_settings_payload())


def _email_settings_from_payload(payload: dict) -> EmailSettings:
    email = payload["email"]
    return EmailSettings(
        smtp_host=email["smtp_host"],
        smtp_port=email["smtp_port"],
        smtp_user=email["smtp_user"],
        smtp_password=email["smtp_password"],
        sender=email["sender"],
        recipient=email["recipient"],
        use_tls=email["use_tls"],
    )


def _apply_initial_state(settings: dict) -> None:
    defaults = DEFAULT_SETTINGS | settings
    email = DEFAULT_SETTINGS["email"] | settings.get("email", {})
    deepseek = DEFAULT_SETTINGS["deepseek"] | settings.get("deepseek", {})
    obsidian = DEFAULT_SETTINGS["obsidian"] | settings.get("obsidian", {})
    schedule = DEFAULT_SETTINGS["schedule"] | settings.get("schedule", {})
    digest = DEFAULT_SETTINGS["digest"] | settings.get("digest", {})
    defaults["article_types"] = [
        article_type for article_type in defaults["article_types"] if article_type in ARTICLE_TYPES
    ]
    digest["article_types"] = [
        article_type for article_type in digest["article_types"] if article_type in ARTICLE_TYPES
    ]

    st.session_state.setdefault("journals_text", "\n".join(defaults["journals"]))
    st.session_state.setdefault("selected_journals", _dedupe(defaults["journals"]))
    st.session_state.setdefault(
        "journal_groups",
        _merge_journal_groups(defaults.get("journal_groups"), defaults.get("custom_journals", [])),
    )
    st.session_state.setdefault("active_journal_group", defaults.get("active_journal_group", "Nature family"))
    st.session_state.setdefault("custom_journals", _dedupe(defaults.get("custom_journals", [])))
    st.session_state.setdefault("custom_journal", "")
    st.session_state.setdefault("keywords", defaults["keywords"])
    st.session_state.setdefault("keyword_match", defaults.get("keyword_match", "all"))
    st.session_state.setdefault("keyword_scope", defaults.get("keyword_scope", "abstract"))
    st.session_state.setdefault("article_types", defaults["article_types"])
    st.session_state.setdefault("require_abstract", bool(defaults.get("require_abstract", True)))
    st.session_state.setdefault("research_only", bool(defaults.get("research_only", True)))
    st.session_state.setdefault("download_dir", defaults.get("download_dir", ""))
    st.session_state.setdefault("openalex_mailto", defaults.get("openalex_mailto", ""))
    st.session_state.setdefault("deepseek_api_key", deepseek.get("api_key", ""))
    st.session_state.setdefault("deepseek_model", deepseek.get("model", "deepseek-v4-pro"))
    st.session_state.setdefault("obsidian_vault_path", obsidian.get("vault_path", ""))
    st.session_state.setdefault("obsidian_root_folder", obsidian.get("root_folder", "Nature-track"))
    st.session_state.setdefault("days_back", int(defaults["days_back"]))
    st.session_state.setdefault("window_value", int(defaults.get("window_value", defaults["days_back"])))
    st.session_state.setdefault("window_unit", _valid_time_unit(defaults.get("window_unit", "days")))
    st.session_state.setdefault("max_results", int(defaults["max_results"]))
    st.session_state.setdefault("schedule_enabled", bool(schedule["enabled"]))
    st.session_state.setdefault("schedule_frequency", schedule["frequency"])
    st.session_state.setdefault("schedule_weekday", schedule["weekday"])
    st.session_state.setdefault("schedule_time", _parse_time(schedule["time"]))
    st.session_state.setdefault("digest_journals", _dedupe(digest["journals"]))
    st.session_state.setdefault(
        "digest_journal_groups",
        _merge_journal_groups(digest.get("journal_groups"), digest.get("custom_journals", [])),
    )
    st.session_state.setdefault("digest_custom_journals", _dedupe(digest.get("custom_journals", [])))
    st.session_state.setdefault("digest_custom_journal", "")
    st.session_state.setdefault("digest_shortcut_group", st.session_state.get("active_journal_group", "Nature family"))
    st.session_state.setdefault("digest_keywords", digest["keywords"])
    st.session_state.setdefault("digest_keyword_match", digest.get("keyword_match", "all"))
    st.session_state.setdefault("digest_keyword_scope", digest.get("keyword_scope", "abstract"))
    st.session_state.setdefault("digest_article_types", digest["article_types"])
    st.session_state.setdefault("digest_require_abstract", bool(digest.get("require_abstract", True)))
    st.session_state.setdefault("digest_research_only", bool(digest.get("research_only", True)))
    st.session_state.setdefault("digest_days_back", int(digest["days_back"]))
    st.session_state.setdefault("digest_window_value", int(digest.get("window_value", digest["days_back"])))
    st.session_state.setdefault("digest_window_unit", _valid_time_unit(digest.get("window_unit", "days")))
    st.session_state.setdefault("digest_max_results", int(digest["max_results"]))
    st.session_state.setdefault("email_provider", email.get("provider", "QQ Mail"))
    st.session_state.setdefault("show_advanced_smtp", False)
    st.session_state.setdefault("smtp_host", email["smtp_host"])
    st.session_state.setdefault("smtp_port", int(email["smtp_port"]))
    st.session_state.setdefault("smtp_user", email["smtp_user"])
    st.session_state.setdefault("smtp_password", email["smtp_password"])
    st.session_state.setdefault("sender", email["sender"])
    st.session_state.setdefault("recipient", email["recipient"])
    st.session_state.setdefault("use_tls", bool(email["use_tls"]))


def _build_query() -> ArticleQuery:
    end = date.today()
    st.session_state.days_back = _session_window_days("window_value", "window_unit")
    start = end - timedelta(days=st.session_state.days_back)
    return ArticleQuery(
        journals=st.session_state.selected_journals,
        from_date=start,
        to_date=end,
        keywords="",
        article_types=st.session_state.article_types,
        max_results=200,
        max_pages=max((st.session_state.max_results // 20) + 2, 3),
        mailto=_openalex_mailto(),
    )


def _build_digest_query() -> ArticleQuery:
    end = date.today()
    st.session_state.digest_days_back = _session_window_days("digest_window_value", "digest_window_unit")
    start = end - timedelta(days=st.session_state.digest_days_back)
    return ArticleQuery(
        journals=st.session_state.digest_journals,
        from_date=start,
        to_date=end,
        keywords="",
        article_types=st.session_state.digest_article_types,
        max_results=200,
        max_pages=max((st.session_state.digest_max_results // 20) + 2, 3),
        mailto=_openalex_mailto(),
    )


def _parse_time(value: str) -> time:
    try:
        hour, minute = value.split(":", maxsplit=1)
        return time(hour=int(hour), minute=int(minute))
    except (AttributeError, TypeError, ValueError):
        return time(hour=8, minute=0)


def _filter_results(
    articles,
    keywords: str,
    keyword_match: str,
    require_abstract: bool,
    research_only: bool,
    keyword_scope: str = "abstract",
):
    return filter_articles_by_abstract(
        filter_article_quality(articles, require_abstract, research_only),
        keywords,
        keyword_match,
        keyword_scope,
    )


def _append_keyword(key: str, target: str = "keywords") -> None:
    existing = getattr(st.session_state, target, "")
    terms = parse_keyword_terms(existing)
    if key.casefold() not in {term.casefold() for term in terms}:
        st.session_state[target] = (existing.rstrip() + "\n" + key).strip()


def _select_frequent_keyword(source_key: str, target_key: str = "keywords") -> None:
    keyword = st.session_state.get(source_key, "")
    if not keyword:
        return
    _append_keyword(keyword, target_key)
    st.session_state[source_key] = ""
    _save_current_settings()


def _add_custom_journal(
    source_key: str,
    target_key: str,
    groups_key: str = "journal_groups",
    group_key: str = "active_journal_group",
) -> None:
    journal = st.session_state.get(source_key, "").strip()
    if not journal:
        return
    st.session_state[target_key] = _dedupe(st.session_state.get(target_key, []) + [journal])
    _add_journal_to_group(journal, group_key, groups_key)
    st.session_state[source_key] = ""
    save_settings(_settings_payload())


def _register_schedule() -> subprocess.CompletedProcess[str]:
    frequency = st.session_state.schedule_frequency
    time_value = st.session_state.schedule_time.strftime("%H:%M")
    args = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts\\register_windows_task.ps1",
        "-Frequency",
        frequency,
        "-Time",
        time_value,
    ]
    if frequency == "weekly":
        args.extend(["-WeeklyDay", st.session_state.schedule_weekday])

    return subprocess.run(
        args,
        cwd=".",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _result_table(articles) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Article": article.compact_label,
                "DOI": article.doi or "",
                "Date": article.publication_date or "",
                "Type": article.article_type or "",
                "Access": "OA" if article.is_oa else "",
            }
            for article in articles
        ]
    )


def _journal_options(extra: list[str]) -> list[str]:
    group_values: list[str] = []
    for journals in st.session_state.get("journal_groups", _default_journal_groups()).values():
        group_values.extend(journals)
    for journals in st.session_state.get("digest_journal_groups", {}).values():
        group_values.extend(journals)
    return sorted(_dedupe(group_values + extra))


def _all_preset_journals() -> set[str]:
    return {journal.casefold() for journals in JOURNAL_GROUPS.values() for journal in journals}


def _custom_quick_journals(values: list[str]) -> list[str]:
    preset = _all_preset_journals()
    return [journal for journal in _dedupe(values) if journal.casefold() not in preset]


def _sync_legacy_custom_journals() -> None:
    custom = st.session_state.get("journal_groups", {}).get(CUSTOM_JOURNAL_GROUP, [])
    st.session_state.custom_journals = _dedupe(custom)


def _sync_digest_legacy_custom_journals() -> None:
    custom = st.session_state.get("digest_journal_groups", {}).get(CUSTOM_JOURNAL_GROUP, [])
    st.session_state.digest_custom_journals = _dedupe(custom)


def _add_journal_to_group(journal: str, group_key: str = "active_journal_group", groups_key: str = "journal_groups") -> None:
    normalized = journal.strip()
    if not normalized:
        return
    group = st.session_state.get(group_key) or CUSTOM_JOURNAL_GROUP
    groups = {name: list(journals) for name, journals in st.session_state.get(groups_key, {}).items()}
    groups.setdefault(group, [])
    groups[group] = _dedupe(groups[group] + [normalized])
    st.session_state[groups_key] = groups
    if groups_key == "journal_groups":
        _sync_legacy_custom_journals()
    elif groups_key == "digest_journal_groups":
        _sync_digest_legacy_custom_journals()


def _move_journal_between_groups(journal: str, target_group: str, groups_key: str = "journal_groups") -> None:
    normalized = journal.strip()
    if not normalized or not target_group:
        return
    groups = {name: list(journals) for name, journals in st.session_state.get(groups_key, {}).items()}
    for group, journals in list(groups.items()):
        groups[group] = [item for item in journals if item.casefold() != normalized.casefold()]
    groups.setdefault(target_group, [])
    groups[target_group] = _dedupe(groups[target_group] + [normalized])
    st.session_state[groups_key] = groups
    if groups_key == "journal_groups":
        _sync_legacy_custom_journals()
    elif groups_key == "digest_journal_groups":
        _sync_digest_legacy_custom_journals()


def _format_authors(article) -> str:
    corresponding = {name.casefold() for name in article.corresponding_authors}
    authors = []
    for name in article.authors:
        suffix = "*" if name.casefold() in corresponding else ""
        authors.append(f"{name}{suffix}")
    if not authors and article.first_author:
        authors.append(article.first_author)
    return ", ".join(authors)


def _article_archive_payload(article) -> dict:
    return {
        "title": article.title,
        "journal": article.journal,
        "publication_date": article.publication_date,
        "article_type": article.article_type,
        "doi": article.doi,
        "doi_url": article.doi_url,
        "pdf_url": article.pdf_url,
        "landing_page_url": article.landing_page_url,
        "authors": article.authors,
        "corresponding_authors": article.corresponding_authors,
    }


def _record_read_and_offer_link(article, action: str, url: str, saved_path: str = "", message: str = "Archived.") -> None:
    payload = _article_archive_payload(article)
    if saved_path:
        payload["saved_path"] = saved_path
    record_read_article(payload, action)
    st.session_state.last_action_message = {
        "title": article.title,
        "action": action,
        "url": url,
        "saved_path": saved_path,
        "message": message,
    }
    if url and not saved_path:
        st.session_state.pending_open_url = url


def _open_pending_url_for(article) -> None:
    message = st.session_state.get("last_action_message", {})
    pending_url = st.session_state.get("pending_open_url", "")
    if not pending_url or message.get("title") != article.title:
        return

    components.html(
        f"""
        <script>
        const target = {json.dumps(pending_url)};
        setTimeout(() => {{
            const opened = window.open(target, "_blank", "noopener,noreferrer");
            if (!opened && window.parent) {{
                window.parent.open(target, "_blank", "noopener,noreferrer");
            }}
        }}, 50);
        </script>
        """,
        height=0,
    )
    st.session_state.pending_open_url = ""


def _result_table_with_hits(articles, keywords: str, scope: str) -> pd.DataFrame:
    table = _result_table(articles)
    if keywords.strip():
        table.insert(
            1,
            "Keyword hits",
            [keyword_hit_count(article, keywords, scope) for article in articles],
        )
    return table


def _download_and_archive(article) -> None:
    if not st.session_state.download_dir.strip():
        st.session_state.download_prompt = True
        st.session_state.last_download_error = "Set a local download folder in the sidebar first."
        st.session_state.download_error_title = article.title
        return
    try:
        saved_path = download_article_pdf(article, st.session_state.download_dir)
    except Exception as exc:
        _record_read_and_offer_link(
            article,
            "Download",
            article.landing_page_url or article.doi_url,
            message="Archived, but no downloadable PDF URL was found for this article.",
        )
        st.session_state.last_download_error = str(exc)
        st.session_state.download_error_title = article.title
        return

    _record_read_and_offer_link(article, "Download", article.pdf_url, str(saved_path))
    st.session_state.last_action_message["message"] = f"Archived and saved to {saved_path}"
    st.session_state.last_download_error = ""
    st.session_state.download_error_title = ""


def _summarize_and_export_article(article) -> None:
    api_key = st.session_state.deepseek_api_key.strip()
    vault_path = st.session_state.obsidian_vault_path.strip()
    if not api_key:
        st.session_state.ai_summary_message = {
            "title": article.title,
            "level": "warning",
            "text": "Add your DeepSeek API key in AI + Obsidian first.",
        }
        return
    if not vault_path:
        st.session_state.ai_summary_message = {
            "title": article.title,
            "level": "warning",
            "text": "Add your Obsidian vault path in AI + Obsidian first.",
        }
        return

    record_read_article(_article_archive_payload(article), "AI summary")
    try:
        full_text = fetch_full_text(article)
        summary = summarize_article(
            article,
            full_text,
            DeepSeekSettings(
                api_key=api_key,
                model=st.session_state.deepseek_model.strip() or "deepseek-v4-pro",
            ),
        )
        note_path = write_obsidian_note(
            article,
            summary,
            full_text,
            vault_path,
            st.session_state.obsidian_root_folder.strip() or "Nature-track",
        )
    except Exception as exc:
        st.session_state.ai_summary_message = {
            "title": article.title,
            "level": "error",
            "text": f"AI summary failed: {exc}",
        }
        return

    st.session_state.ai_summary_message = {
        "title": article.title,
        "level": "success",
        "text": f"Saved Obsidian note: {note_path}",
        "note_path": str(note_path),
        "obsidian_uri": obsidian_open_uri(note_path, vault_path),
    }


def _source_summary(journals: list[str]) -> str:
    if not journals:
        return "No journals selected"
    visible = ", ".join(journals[:3])
    extra = len(journals) - 3
    return f"{visible} +{extra}" if extra > 0 else visible


def _keyword_summary(keywords: str) -> str:
    terms = parse_keyword_terms(keywords)
    if not terms:
        return "No keyword filter"
    visible = ", ".join(terms[:3])
    extra = len(terms) - 3
    return f"{visible} +{extra}" if extra > 0 else visible


def _short_label(value: str, limit: int = 18) -> str:
    label = JOURNAL_BUTTON_LABELS.get(value, value)
    return label if len(label) <= limit else f"{label[: limit - 1].rstrip()}."


def _render_journal_buttons(journals: list[str], target_key: str, key_prefix: str) -> None:
    for start in range(0, len(journals), 3):
        journal_cols = st.columns(3)
        for col, journal in zip(journal_cols, journals[start : start + 3], strict=False):
            label = _short_label(journal)
            if col.button(label, key=f"{key_prefix}_{journal}", use_container_width=True, help=f"Add {journal}."):
                st.session_state[target_key] = _dedupe(st.session_state[target_key] + [journal])
                st.rerun()


def _render_keyword_memory(target_key: str = "keywords") -> None:
    entries = frequent_keyword_entries(24)
    if not entries:
        return

    terms = [entry["term"] for entry in entries]
    counts = {entry["term"]: int(entry.get("count", 0)) for entry in entries}
    picker_key = f"{target_key}_frequent_picker"
    st.caption("Frequent")
    st.selectbox(
        "Frequent keywords",
        ["", *terms],
        key=picker_key,
        format_func=lambda term: "Select a keyword" if not term else f"{term} ({counts.get(term, 0)})",
        label_visibility="collapsed",
        on_change=_select_frequent_keyword,
        args=(picker_key, target_key),
    )


def _render_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --paper: #ebe9e1;
            --paper-wash: #d7d8cb;
            --wash-deep: #bcc2b5;
            --surface: rgba(250, 249, 244, 0.74);
            --surface-solid: #faf9f4;
            --surface-raised: rgba(255, 254, 249, 0.86);
            --control: rgba(224, 225, 216, 0.72);
            --ink: #252a27;
            --ink-soft: #59615b;
            --ink-muted: #7b827a;
            --line-soft: rgba(79, 88, 81, 0.12);
            --line: rgba(79, 88, 81, 0.22);
            --moss: #6f7c70;
            --moss-deep: #4e5b51;
            --moss-soft: #dfe1d7;
            --lake: #66746d;
            --brass: #8c8172;
            --danger: #8d625d;
            --glass: rgba(255, 255, 250, 0.46);
            --shadow-soft: 0 18px 46px rgba(62, 68, 61, 0.13);
            --shadow-float: 0 28px 72px rgba(62, 68, 61, 0.18);
            --radius-sm: 7px;
            --radius-md: 12px;
            --radius-lg: 16px;
        }
        html, body, [class*="css"] {
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
            color: var(--ink);
        }
        .stApp {
            background:
                radial-gradient(780px 440px at 8% 4%, rgba(188, 194, 181, 0.55), transparent 62%),
                radial-gradient(620px 360px at 92% 8%, rgba(215, 216, 203, 0.68), transparent 60%),
                radial-gradient(760px 500px at 48% 92%, rgba(205, 207, 195, 0.46), transparent 66%),
                linear-gradient(120deg, rgba(255, 255, 250, 0.64), rgba(230, 229, 219, 0.32)),
                var(--paper);
        }
        .block-container {
            max-width: 1320px;
            padding-top: 1.35rem;
            padding-bottom: 4.5rem;
        }
        section[data-testid="stSidebar"] {
            background: rgba(235, 233, 225, 0.72);
            backdrop-filter: blur(18px);
            border-right: 1px solid var(--line);
            box-shadow: 12px 0 38px rgba(80, 86, 78, 0.08);
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            padding-top: 0.75rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        section[data-testid="stSidebar"] h3 {
            margin: 0.2rem 0 0.35rem;
            font-size: 0.95rem;
        }
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            margin-bottom: 0.35rem;
        }
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] [data-baseweb="form-control"] label {
            color: var(--ink-soft);
            font-size: 0.76rem;
            font-weight: 720;
        }
        section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
            gap: 0.42rem;
        }
        section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
            gap: 0.42rem;
        }
        section[data-testid="stSidebar"] .stTabs [data-baseweb="tab-list"] {
            gap: 0.15rem;
            border-bottom: 1px solid var(--line-soft);
        }
        section[data-testid="stSidebar"] .stTabs [data-baseweb="tab"] {
            height: 2rem;
            padding: 0 0.5rem;
            font-size: 0.76rem;
            font-weight: 700;
            border-radius: var(--radius-sm) var(--radius-sm) 0 0;
        }
        section[data-testid="stSidebar"] .stButton > button {
            min-height: 1.95rem;
            padding: 0.25rem 0.42rem;
            font-size: 0.78rem;
            line-height: 1.1;
            background: rgba(250, 249, 244, 0.58);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
        }
        section[data-testid="stSidebar"] .sidebar-primary button {
            background: var(--moss-deep) !important;
            border-color: var(--moss-deep) !important;
            color: #fffdf8 !important;
        }
        section[data-testid="stSidebar"] .sidebar-compact-actions button {
            min-height: 1.85rem;
        }
        section[data-testid="stSidebar"] div[data-testid="stExpander"] details {
            background: var(--glass) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.42);
        }
        section[data-testid="stSidebar"] div[data-testid="stExpander"] details summary {
            padding-top: 0.45rem !important;
            padding-bottom: 0.45rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stExpander"] details summary p {
            font-size: 0.86rem !important;
        }
        section[data-testid="stSidebar"] div[data-testid="stMultiSelect"] [data-baseweb="tag"] {
            max-width: 9.5rem;
        }
        section[data-testid="stSidebar"] textarea {
            min-height: 5.5rem !important;
        }
        .sidebar-section-title {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 0.5rem;
            border-top: 1px solid var(--line-soft);
            padding-top: 0.7rem;
            margin-top: 0.65rem;
            color: var(--ink);
            font-size: 0.78rem;
            font-weight: 780;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }
        .sidebar-section-title:first-child {
            border-top: 0;
            padding-top: 0;
            margin-top: 0;
        }
        .sidebar-section-title span {
            color: var(--ink-muted);
            font-size: 0.72rem;
            font-weight: 650;
            text-transform: none;
        }
        .sidebar-hint {
            color: var(--ink-muted);
            font-size: 0.74rem;
            line-height: 1.35;
            margin: -0.1rem 0 0.25rem;
        }
        h1, h2, h3 {
            letter-spacing: 0;
            color: var(--ink);
        }
        .stMarkdown a {
            color: var(--lake);
        }
        .radar-header {
            border-bottom: 1px solid var(--line);
            padding: 1rem 1.1rem 1.15rem;
            margin-bottom: 1rem;
            border-radius: var(--radius-lg);
            background: linear-gradient(145deg, rgba(255, 255, 250, 0.62), rgba(241, 240, 232, 0.34));
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(18px);
            position: relative;
            overflow: hidden;
        }
        .radar-header::after {
            content: "";
            position: absolute;
            inset: auto 1.2rem 0 1.2rem;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(79, 88, 81, 0.22), transparent);
        }
        .radar-kicker {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            color: var(--ink-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
            position: relative;
            z-index: 1;
        }
        .radar-mark {
            width: 1.75rem;
            height: 1.75rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-sm);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: var(--moss-deep);
            background: rgba(255, 255, 250, 0.52);
            font-weight: 800;
            letter-spacing: 0;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
        }
        .radar-title {
            margin: 0;
            font-size: 1.75rem;
            line-height: 1.08;
            font-weight: 760;
            color: var(--ink);
            position: relative;
            z-index: 1;
        }
        .query-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0;
            margin-top: 1.25rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            overflow: hidden;
            background: rgba(255, 255, 250, 0.42);
            backdrop-filter: blur(16px);
            position: relative;
            z-index: 1;
        }
        .query-cell {
            min-height: 5rem;
            padding: 0.85rem 0.95rem;
            border-right: 1px solid var(--line-soft);
        }
        .query-cell:last-child {
            border-right: 0;
        }
        .query-label {
            color: var(--ink-muted);
            font-size: 0.72rem;
            font-weight: 750;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.38rem;
        }
        .query-value {
            color: var(--ink);
            font-size: 0.95rem;
            line-height: 1.35;
            font-weight: 620;
        }
        .result-deck {
            display: grid;
            grid-template-columns: 1.35fr repeat(3, 1fr);
            gap: 0.75rem;
            margin: 0.65rem 0 0.9rem;
        }
        .result-tile {
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            background: linear-gradient(145deg, rgba(255, 255, 250, 0.7), rgba(239, 239, 230, 0.46));
            padding: 0.9rem 1rem;
            min-height: 5.7rem;
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(16px);
            position: relative;
            overflow: hidden;
        }
        .result-tile.primary {
            background: linear-gradient(145deg, rgba(78, 91, 81, 0.96), rgba(111, 124, 112, 0.86));
            color: #f8f5ec;
            border-color: rgba(78, 91, 81, 0.58);
        }
        .result-kicker {
            color: var(--ink-muted);
            font-size: 0.72rem;
            font-weight: 750;
            letter-spacing: 0;
            text-transform: uppercase;
        }
        .result-tile.primary .result-kicker {
            color: #c8d7cf;
        }
        .result-number {
            margin-top: 0.35rem;
            font-size: 1.65rem;
            line-height: 1.05;
            font-weight: 760;
            color: inherit;
        }
        .result-note {
            margin-top: 0.32rem;
            color: var(--ink-soft);
            font-size: 0.82rem;
            line-height: 1.35;
        }
        .result-tile.primary .result-note {
            color: #dfe8e2;
        }
        .section-rule {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border-top: 1px solid var(--line);
            padding-top: 0.85rem;
            margin-top: 1.1rem;
            margin-bottom: 0.45rem;
        }
        .section-rule h2 {
            margin: 0;
            font-size: 1rem;
            line-height: 1.2;
            font-weight: 760;
        }
        .section-rule span {
            color: var(--ink-muted);
            font-size: 0.82rem;
        }
        .article-meta {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 0.45rem;
            color: var(--ink-muted);
            padding-bottom: 0.65rem;
        }
        .article-meta span {
            border: 1px solid var(--line-soft);
            border-radius: 999px;
            background: rgba(255, 255, 250, 0.54);
            padding: 0.2rem 0.48rem;
            font-size: 0.76rem;
            font-weight: 700;
            backdrop-filter: blur(10px);
        }
        .article-abstract {
            font-size: 1.02rem;
            line-height: 1.72;
            color: var(--ink);
            margin: 0.35rem 0 0.9rem;
        }
        .article-authors {
            font-size: 0.92rem;
            line-height: 1.55;
            color: var(--ink-soft);
            border-top: 1px solid var(--line-soft);
            padding-top: 0.68rem;
            margin: 0.45rem 0 0.9rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid var(--line);
            padding: 0.5rem 0.58rem;
            border-radius: var(--radius-sm);
            background: var(--surface-raised);
        }
        div[data-testid="stMetric"] label {
            font-size: 0.72rem !important;
            color: var(--ink-muted) !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            font-size: 1rem !important;
            color: var(--ink) !important;
        }
        .stButton > button,
        div[data-testid="stDownloadButton"] button {
            border-radius: var(--radius-sm);
            border-color: var(--line);
            min-height: 2.35rem;
            font-weight: 650;
            background: rgba(250, 249, 244, 0.72);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
        }
        .stButton > button:hover,
        div[data-testid="stDownloadButton"] button:hover {
            border-color: rgba(78, 91, 81, 0.42);
            color: var(--moss-deep);
            background: rgba(255, 255, 250, 0.9);
        }
        .stButton > button[kind="primary"] {
            background: var(--moss-deep);
            border-color: var(--moss-deep);
            color: #fffdf8;
        }
        div[data-testid="stExpander"] details {
            border: 1px solid var(--line) !important;
            border-radius: var(--radius-md) !important;
            background: rgba(255, 255, 250, 0.56);
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(16px);
        }
        div[data-testid="stExpander"] details summary {
            padding-top: 0.75rem !important;
            padding-bottom: 0.75rem !important;
        }
        div[data-testid="stExpander"] details summary p {
            font-size: 1.02rem !important;
            font-weight: 740 !important;
            line-height: 1.38 !important;
            color: var(--ink) !important;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            overflow: hidden;
            box-shadow: var(--shadow-soft);
            background: rgba(255, 255, 250, 0.48);
            backdrop-filter: blur(14px);
        }
        input, textarea, select {
            background-color: var(--control) !important;
        }
        .compact-download div[data-testid="stDownloadButton"] button {
            min-height: 2rem;
            padding: 0.25rem 0.65rem;
            font-size: 0.86rem;
        }
        .empty-state {
            border: 1px dashed rgba(78, 91, 81, 0.34);
            border-radius: var(--radius-lg);
            background: rgba(255, 255, 250, 0.5);
            padding: 1.25rem;
            margin-top: 1rem;
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(14px);
        }
        .empty-state strong {
            display: block;
            color: var(--ink);
            margin-bottom: 0.35rem;
        }
        .empty-state span {
            color: var(--ink-soft);
            font-size: 0.92rem;
        }
        .usage-fab {
            position: fixed;
            right: 1.1rem;
            bottom: 1.1rem;
            z-index: 9999;
            font-family: inherit;
        }
        .fab-button {
            width: 2.6rem;
            height: 2.6rem;
            border-radius: 50%;
            border: 1px solid var(--line);
            background: rgba(255, 255, 250, 0.68);
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(14px);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.02rem;
            font-weight: 800;
            color: var(--moss);
            line-height: 1;
            padding: 0;
        }
        .fab-button:hover {
            border-color: rgba(78, 91, 81, 0.42);
            color: var(--ink);
        }
        .archive-fab {
            position: fixed;
            right: 4.2rem;
            bottom: 1.1rem;
            z-index: 9999;
            font-family: inherit;
        }
        .archive-icon {
            position: relative;
            width: 1.15rem;
            height: 0.85rem;
            border: 1.8px solid currentColor;
            border-radius: 3px;
            display: block;
        }
        .archive-icon::before {
            content: "";
            position: absolute;
            left: 0.12rem;
            top: -0.36rem;
            width: 0.52rem;
            height: 0.32rem;
            border: 1.8px solid currentColor;
            border-bottom: 0;
            border-radius: 3px 3px 0 0;
            background: rgba(255, 255, 250, 0.78);
        }
        .usage-panel,
        .archive-panel {
            position: fixed;
            inset: auto 1.1rem 4.2rem auto;
            right: 1.1rem;
            bottom: 4.2rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            background: rgba(250, 249, 244, 0.76);
            box-shadow: var(--shadow-float);
            backdrop-filter: blur(18px);
            padding: 0.85rem;
            color: var(--ink);
        }
        .usage-panel {
            width: 15rem;
        }
        .archive-panel {
            width: 24rem;
            max-width: calc(100vw - 2rem);
        }
        .usage-title {
            font-weight: 760;
            margin-bottom: 0.45rem;
        }
        .usage-panel div:not(.usage-title) {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.18rem 0;
            font-size: 0.92rem;
        }
        .usage-panel p {
            margin: 0.35rem 0 0;
            color: var(--ink-muted);
            font-size: 0.78rem;
        }
        .archive-title {
            border-top: 1px solid var(--line-soft);
            padding-top: 0.55rem;
            margin-top: 0.55rem;
        }
        .read-archive {
            list-style: none;
            padding: 0;
            margin: 0.2rem 0 0.55rem;
            max-height: 20rem;
            overflow-y: auto;
        }
        .archive-month {
            border-top: 1px solid var(--line-soft);
            padding-top: 0.35rem;
            margin-top: 0.35rem;
        }
        .archive-month summary {
            cursor: pointer;
            font-weight: 700;
            font-size: 0.9rem;
        }
        .read-archive li {
            border-bottom: 1px solid var(--line-soft);
            padding: 0.42rem 0;
        }
        .read-archive a {
            display: block;
            color: var(--lake);
            font-size: 0.82rem;
            line-height: 1.25;
            text-decoration: none;
        }
        .read-archive a:hover {
            text-decoration: underline;
        }
        .read-archive span {
            display: block;
            color: var(--ink-muted);
            font-size: 0.72rem;
            margin-top: 0.15rem;
        }
        @media (max-width: 900px) {
            .query-strip,
            .result-deck {
                grid-template-columns: 1fr 1fr;
            }
            .query-cell:nth-child(2) {
                border-right: 0;
            }
            .query-cell:nth-child(-n+2) {
                border-bottom: 1px solid var(--line-soft);
            }
        }
        @media (max-width: 640px) {
            .query-strip,
            .result-deck {
                grid-template-columns: 1fr;
            }
            .query-cell {
                border-right: 0;
                border-bottom: 1px solid var(--line-soft);
            }
            .query-cell:last-child {
                border-bottom: 0;
            }
            .radar-title {
                font-size: 1.55rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_app_header(query: ArticleQuery) -> None:
    schedule = "Schedule off"
    if st.session_state.schedule_enabled:
        if st.session_state.schedule_frequency == "weekly":
            schedule = f"Weekly {st.session_state.schedule_weekday} {st.session_state.schedule_time:%H:%M}"
        else:
            schedule = f"Daily {st.session_state.schedule_time:%H:%M}"
    st.markdown(
        f"""
        <section class="radar-header">
            <div class="radar-kicker"><span class="radar-mark">N</span><span>Local literature radar</span></div>
            <h1 class="radar-title">Nature-track</h1>
            <div class="query-strip">
                <div class="query-cell">
                    <div class="query-label">Sources</div>
                    <div class="query-value">{escape(_source_summary(query.journals))}</div>
                </div>
                <div class="query-cell">
                    <div class="query-label">Window</div>
                    <div class="query-value">{query.from_date:%Y-%m-%d} to {query.to_date:%Y-%m-%d}</div>
                </div>
                <div class="query-cell">
                    <div class="query-label">Signal</div>
                    <div class="query-value">{escape(_keyword_summary(st.session_state.keywords))}</div>
                </div>
                <div class="query-cell">
                    <div class="query-label">Delivery</div>
                    <div class="query-value">{escape(schedule)}</div>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_result_overview(articles, query: ArticleQuery) -> None:
    oa_count = sum(1 for article in articles if article.is_oa)
    pdf_count = sum(1 for article in articles if article.pdf_url)
    journals = len({article.journal for article in articles if article.journal})
    read_count = len(load_usage().get("read_articles", []))
    st.markdown(
        f"""
        <div class="result-deck">
            <div class="result-tile primary">
                <div class="result-kicker">Matching papers</div>
                <div class="result-number">{len(articles)}</div>
                <div class="result-note">Limit {st.session_state.max_results}; OpenAlex window {query.from_date:%m-%d} to {query.to_date:%m-%d}</div>
            </div>
            <div class="result-tile">
                <div class="result-kicker">Journals hit</div>
                <div class="result-number">{journals}</div>
                <div class="result-note">{len(query.journals)} sources are being watched</div>
            </div>
            <div class="result-tile">
                <div class="result-kicker">Open access</div>
                <div class="result-number">{oa_count}</div>
                <div class="result-note">{pdf_count} records expose direct PDF links</div>
            </div>
            <div class="result-tile">
                <div class="result-kicker">Read archive</div>
                <div class="result-number">{read_count}</div>
                <div class="result-note">Stored locally from DOI and PDF actions</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_empty_state() -> None:
    has_rate_limit = any("HTTP 429" in warning for warning in st.session_state.get("search_warnings", []))
    if has_rate_limit:
        st.markdown(
            """
            <div class="empty-state">
                <strong>OpenAlex is rate-limiting this machine right now.</strong>
                <span>The query did not reach the article-matching stage. Wait 10-20 minutes before refreshing again, or switch networks. Your keyword settings are not the cause of this empty result.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        """
        <div class="empty-state">
            <strong>No matching articles found.</strong>
            <span>Try widening the date window, switching keyword match to any concept, or relaxing abstract/type filters.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_article(article, index: int) -> None:
    title = article.title or "Untitled article"
    meta_parts = [part for part in [article.journal, article.publication_date, article.article_type] if part]
    expander_label = f"{title}    |    {' / '.join(meta_parts)}" if meta_parts else title
    with st.expander(expander_label):
        badges = "".join(
            f"<span>{escape(part)}</span>"
            for part in [
                article.publication_date,
                article.article_type,
                "Open access" if article.is_oa else "OA unknown",
                "PDF available" if article.pdf_url else "",
            ]
            if part
        )
        st.markdown(f"<div class='article-meta'>{badges}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='article-abstract'>{escape(article.abstract or 'No abstract available from OpenAlex.')}</div>",
            unsafe_allow_html=True,
        )
        authors = _format_authors(article)
        if authors:
            st.markdown(
                f"<div class='article-authors'>{escape(authors)}</div>",
                unsafe_allow_html=True,
        )
        spacer, ai_col, doi_col, download_col = st.columns([3.1, 1.2, 0.8, 1.1])
        if ai_col.button(
            "Summarize",
            key=f"summarize_{index}_{article.doi or article.title}",
            use_container_width=True,
            help="Read public full text when available, summarize with DeepSeek, and save an Obsidian graph note.",
        ):
            with st.spinner("Reading publisher page and writing Obsidian note..."):
                _summarize_and_export_article(article)
        if article.doi_url:
            if doi_col.button("DOI", key=f"doi_{index}_{article.doi or article.title}", use_container_width=True):
                _record_read_and_offer_link(
                    article,
                    "DOI",
                    article.landing_page_url or article.doi_url,
                    message="Archived and opening paper page.",
                )
        if article.pdf_url or article.landing_page_url or article.doi_url:
            if download_col.button(
                "Download",
                key=f"download_{index}_{article.doi or article.title}",
                use_container_width=True,
            ):
                _download_and_archive(article)

        if st.session_state.get("last_action_message", {}).get("title") == article.title:
            message = st.session_state.last_action_message
            st.success(message["message"])
            if message.get("url") and not message.get("saved_path"):
                _open_pending_url_for(article)
                st.markdown(
                    f"<small>If the browser blocks it: <a href='{escape(message['url'])}' target='_blank' rel='noreferrer'>open page</a></small>",
                    unsafe_allow_html=True,
                )
        if st.session_state.get("last_download_error") and st.session_state.get("download_error_title") == article.title:
            st.warning(st.session_state.last_download_error)
        if st.session_state.get("ai_summary_message", {}).get("title") == article.title:
            summary_message = st.session_state.ai_summary_message
            level = summary_message.get("level")
            text = summary_message.get("text", "")
            if level == "success":
                st.success(text)
                if summary_message.get("obsidian_uri"):
                    st.markdown(
                        f"<small><a href='{escape(summary_message['obsidian_uri'])}' target='_self'>Open in Obsidian</a></small>",
                        unsafe_allow_html=True,
                    )
            elif level == "warning":
                st.warning(text)
            else:
                st.error(text)


def _render_usage_fab() -> None:
    usage = load_usage()
    email_pushes = int(usage["test_pushes"]) + int(usage["scheduled_pushes"])
    st.markdown(
        f"""
        <div class="usage-fab">
            <button class="fab-button" popovertarget="usage-popover" title="Usage statistics">&#9734;</button>
        </div>
        <div id="usage-popover" class="usage-panel" popover>
            <div class="usage-title">Usage</div>
            <div><span>Views</span><strong>{usage["views"]}</strong></div>
            <div><span>Searches</span><strong>{usage["searches"]}</strong></div>
            <div><span>Articles seen</span><strong>{usage["articles_seen"]}</strong></div>
            <div><span>Email pushes</span><strong>{email_pushes}</strong></div>
            <p>Last view: {usage["last_view_at"] or "none"}</p>
            <p>Last search: {usage["last_search_at"] or "none"}</p>
            <p>Last push: {usage["last_push_at"] or "none"}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _render_archive_fab() -> None:
    read_articles = load_usage().get("read_articles", [])
    groups: list[tuple[str, list[dict]]] = []
    sorted_articles = sorted(read_articles, key=lambda item: item.get("last_read_at", ""), reverse=True)
    for month, items in groupby(sorted_articles, key=lambda item: (item.get("last_read_at", "")[:7] or "Unknown")):
        groups.append((month, list(items)))

    if groups:
        sections = []
        for month, items in groups:
            entries = []
            for item in items:
                url = escape(item.get("saved_path") or item.get("landing_page_url") or item.get("doi_url") or item.get("pdf_url") or "#")
                title = escape(item.get("title") or "Untitled")
                journal = escape(item.get("journal") or "Unknown journal")
                read_at = escape(item.get("last_read_at") or "")
                saved = escape(item.get("saved_path") or "")
                saved_text = f"<span>Saved: {saved}</span>" if saved else ""
                entries.append(
                    f'<li><a href="{url}" target="_blank" rel="noreferrer">{title}</a>'
                    f'<span>{journal} &middot; {read_at}</span>{saved_text}</li>'
                )
            sections.append(
                f'<details class="archive-month" open><summary>{escape(month)} ({len(items)})</summary>'
                f'<ul class="read-archive">{"".join(entries)}</ul></details>'
            )
        body = "".join(sections)
    else:
        body = "<p>No archived reads yet.</p>"

    st.markdown(
        f"""
        <div class="archive-fab">
            <button class="fab-button" popovertarget="archive-popover" title="Read archive">
                <span class="archive-icon" aria-hidden="true"></span>
            </button>
        </div>
        <div id="archive-popover" class="archive-panel" popover>
            <div class="usage-title">Read archive</div>
            {body}
        </div>
        """,
        unsafe_allow_html=True,
    )

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="N", layout="wide")
    _apply_initial_state(load_settings())
    if "view_recorded" not in st.session_state:
        record_usage(views=1)
        st.session_state.view_recorded = True

    _render_styles()
    _render_usage_fab()
    _render_archive_fab()

    with st.sidebar:
        st.markdown(
            f"""
            <div class="sidebar-section-title">Sources <span>{len(st.session_state.selected_journals)} selected</span></div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sidebar-hint">Add watched journals first. Short labels keep the control surface scan-friendly.</div>',
            unsafe_allow_html=True,
        )
        quick_groups = st.session_state.journal_groups
        group_names = list(quick_groups)
        if st.session_state.active_journal_group not in group_names:
            st.session_state.active_journal_group = group_names[0]
        st.radio(
            "Journal group",
            group_names,
            key="active_journal_group",
            horizontal=True,
            format_func=lambda value: JOURNAL_TAB_LABELS.get(value, value),
            label_visibility="collapsed",
        )
        _render_journal_buttons(
            quick_groups.get(st.session_state.active_journal_group, []),
            "selected_journals",
            f"add_{st.session_state.active_journal_group}",
        )

        add_cols = st.columns([3, 1])
        add_cols[0].text_input("Custom journal", key="custom_journal", placeholder="Biogeosciences")
        add_cols[1].button(
            "Add",
            use_container_width=True,
            help=f"Add to {JOURNAL_TAB_LABELS.get(st.session_state.active_journal_group, st.session_state.active_journal_group)}.",
            on_click=_add_custom_journal,
            args=("custom_journal", "selected_journals", "journal_groups", "active_journal_group"),
        )

        with st.expander("Organize journals", expanded=False):
            all_group_journals = _dedupe(sum(st.session_state.journal_groups.values(), []))
            if all_group_journals:
                move_cols = st.columns([1.5, 1])
                selected_move_journal = move_cols[0].selectbox(
                    "Journal",
                    all_group_journals,
                    key="move_journal",
                    label_visibility="collapsed",
                )
                selected_target_group = move_cols[1].selectbox(
                    "Move to",
                    group_names,
                    key="move_target_group",
                    format_func=lambda value: JOURNAL_TAB_LABELS.get(value, value),
                    label_visibility="collapsed",
                )
                if st.button("Move journal", use_container_width=True):
                    _move_journal_between_groups(selected_move_journal, selected_target_group)
                    save_settings(_settings_payload())
                    st.rerun()
            else:
                st.caption("No journal shortcuts yet.")

        st.multiselect(
            "Selected journals",
            options=_journal_options(st.session_state.selected_journals),
            key="selected_journals",
        )

        st.markdown(
            '<div class="sidebar-section-title">Signal <span>keywords</span></div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            "Keyword query",
            key="keywords",
            placeholder="carbon cycle OR carbon sink\ndrought\nNOT crop",
            height=96,
            help="One line is one concept. Use OR for synonyms and NOT or - to exclude terms. Matching uses word/phrase boundaries, not loose substring matching.",
            on_change=_save_current_settings,
        )
        _render_keyword_memory("keywords")

        with st.expander("Filter limits", expanded=False):
            range_cols = st.columns([1, 1, 1])
            range_cols[0].number_input("Window", min_value=1, max_value=3650, step=1, key="window_value")
            range_cols[1].selectbox(
                "Unit",
                list(TIME_WINDOW_UNITS),
                key="window_unit",
                format_func=lambda value: TIME_WINDOW_LABELS[value],
            )
            range_cols[2].number_input("Max", min_value=5, max_value=200, step=5, key="max_results")
            st.multiselect("Article types", ARTICLE_TYPES, key="article_types")
            toggle_cols = st.columns(2)
            toggle_cols[0].toggle("Require abstract", key="require_abstract")
            toggle_cols[1].toggle(
                "Research only",
                key="research_only",
                help="Filters out records without substantial abstracts and common correction/news-like titles.",
            )

        st.radio(
            "Keyword match",
            ["all", "any"],
            key="keyword_match",
            horizontal=True,
            format_func=lambda value: "All concepts" if value == "all" else "Any concept",
            help="All concepts is stricter. Any concept is broader and may include more weakly related papers.",
        )
        st.radio(
            "Search field",
            ["abstract", "title_abstract", "title"],
            key="keyword_scope",
            horizontal=True,
            format_func=lambda value: {
                "abstract": "Abstract",
                "title_abstract": "Title + abstract",
                "title": "Title only",
            }[value],
            help="Title only is most precise but may miss relevant papers. Abstract is usually the best balance.",
        )

        st.markdown(
            '<div class="sidebar-section-title">Output <span>local + email</span></div>',
            unsafe_allow_html=True,
        )
        with st.expander("Local downloads", expanded=bool(st.session_state.get("download_prompt"))):
            st.text_input(
                "Download folder",
                key="download_dir",
                placeholder="e.g. F:\\Nature_track\\downloads",
            )
            st.caption("Used when an article has a direct open-access PDF URL.")
            if st.button("Save download folder", use_container_width=True):
                folder = st.session_state.download_dir.strip()
                if not folder:
                    st.warning("Enter a local folder path first.")
                elif not Path(folder).exists():
                    st.warning("This folder does not exist. Create it first or paste an existing folder path.")
                elif not Path(folder).is_dir():
                    st.warning("This path is not a folder.")
                else:
                    save_settings(_settings_payload())
                    st.session_state.download_prompt = False
                    st.session_state.last_download_error = ""
                    st.success("Download folder saved.")
            if st.session_state.get("last_download_error"):
                st.warning(st.session_state.last_download_error)

        with st.expander("OpenAlex access", expanded=False):
            st.text_input(
                "Contact email",
                key="openalex_mailto",
                placeholder="your.email@example.com",
                help="Optional but recommended. Sent as the OpenAlex mailto parameter to reduce anonymous-rate-limit issues.",
            )
            if st.button("Save OpenAlex email", use_container_width=True):
                save_settings(_settings_payload())
                st.success("OpenAlex email saved.")

        with st.expander(
            "AI + Obsidian",
            expanded=bool(st.session_state.get("ai_summary_message", {}).get("level") in {"warning", "error"}),
        ):
            st.text_input(
                "DeepSeek API key",
                key="deepseek_api_key",
                type="password",
                placeholder="sk-...",
                help="Stored only in local data/settings.json.",
            )
            st.text_input(
                "DeepSeek model",
                key="deepseek_model",
                placeholder="deepseek-v4-pro",
                help="Default expert mode uses deepseek-v4-pro with thinking enabled and max reasoning effort.",
            )
            st.text_input(
                "Obsidian vault path",
                key="obsidian_vault_path",
                placeholder="e.g. D:\\Obsidian\\MyVault",
            )
            st.text_input(
                "Obsidian root folder",
                key="obsidian_root_folder",
                placeholder="Nature-track",
            )
            st.caption("Creates linked notes under Papers, Topics, Methods, Data, and Journals.")
            if st.button("Save AI settings", use_container_width=True):
                vault = st.session_state.obsidian_vault_path.strip()
                if vault and not Path(vault).is_dir():
                    st.warning("Obsidian vault path does not exist or is not a folder.")
                else:
                    save_settings(_settings_payload())
                    st.success("AI + Obsidian settings saved.")

        with st.expander("Email digest", expanded=False):
            provider = st.selectbox("Sender provider", list(EMAIL_PROVIDERS), key="email_provider")
            provider_config = EMAIL_PROVIDERS[provider]
            if provider != "Custom":
                st.session_state.smtp_host = provider_config["smtp_host"]
                st.session_state.smtp_port = provider_config["smtp_port"]
                st.session_state.use_tls = provider_config["use_tls"]

            st.text_input("Sender email", key="sender", placeholder="your_email@qq.com")
            st.text_input(
                "Authorization code",
                key="smtp_password",
                type="password",
                help="Use the mailbox SMTP authorization code or app password, not the normal login password.",
            )
            st.text_input("Recipient email", key="recipient", placeholder="receiver@example.com")
            st.session_state.smtp_user = st.session_state.sender

            if st.checkbox("Show advanced SMTP", key="show_advanced_smtp"):
                st.text_input("SMTP host", key="smtp_host", placeholder="smtp.example.com")
                st.number_input("SMTP port", min_value=1, max_value=65535, key="smtp_port")
                st.toggle("Use TLS", key="use_tls")
                st.caption("Built-in sender accounts are not used; local tools need your mailbox authorization.")

        with st.expander("Scheduled digest", expanded=False):
            st.toggle("Enable schedule", key="schedule_enabled")
            schedule_cols = st.columns(2)
            schedule_cols[0].selectbox(
                "Frequency",
                ["weekly", "daily"],
                key="schedule_frequency",
                format_func=lambda value: "Weekly" if value == "weekly" else "Daily",
            )
            if st.session_state.schedule_frequency == "weekly":
                schedule_cols[1].selectbox("Weekday", WEEKDAYS, key="schedule_weekday")
            else:
                schedule_cols[1].time_input("Send time", key="schedule_time")
            if st.session_state.schedule_frequency == "weekly":
                st.time_input("Send time", key="schedule_time")

            if st.button("Copy current tracker filters", use_container_width=True):
                st.session_state.digest_journals = st.session_state.selected_journals
                st.session_state.digest_custom_journals = st.session_state.custom_journals
                st.session_state.digest_journal_groups = st.session_state.journal_groups
                st.session_state.digest_keywords = st.session_state.keywords
                st.session_state.digest_keyword_match = st.session_state.keyword_match
                st.session_state.digest_keyword_scope = st.session_state.keyword_scope
                st.session_state.digest_article_types = st.session_state.article_types
                st.session_state.digest_require_abstract = st.session_state.require_abstract
                st.session_state.digest_research_only = st.session_state.research_only
                st.session_state.digest_days_back = _session_window_days("window_value", "window_unit")
                st.session_state.digest_window_value = st.session_state.window_value
                st.session_state.digest_window_unit = st.session_state.window_unit
                st.session_state.digest_max_results = st.session_state.max_results
                st.rerun()

            st.multiselect(
                "Digest journals",
                options=_journal_options(st.session_state.digest_journals),
                key="digest_journals",
            )
            digest_group = st.selectbox(
                "Digest shortcut group",
                list(st.session_state.journal_groups),
                key="digest_shortcut_group",
                format_func=lambda value: JOURNAL_TAB_LABELS.get(value, value),
            )
            _render_journal_buttons(
                st.session_state.journal_groups.get(digest_group, []),
                "digest_journals",
                "digest_shortcut",
            )
            digest_add_cols = st.columns([3, 1])
            digest_add_cols[0].text_input(
                "Add digest journal",
                key="digest_custom_journal",
                placeholder="e.g. Biogeosciences",
            )
            digest_add_cols[1].button(
                "Add",
                key="add_digest_journal",
                use_container_width=True,
                on_click=_add_custom_journal,
                args=("digest_custom_journal", "digest_journals", "journal_groups", "digest_shortcut_group"),
            )

            st.text_area(
                "Digest keyword query",
                key="digest_keywords",
                placeholder="carbon cycle OR carbon sink\ndrought\nNOT crop",
                height=110,
                on_change=_save_current_settings,
            )
            st.radio(
                "Digest keyword match",
                ["all", "any"],
                key="digest_keyword_match",
                horizontal=True,
                format_func=lambda value: "All concepts" if value == "all" else "Any concept",
            )
            st.radio(
                "Digest search field",
                ["abstract", "title_abstract", "title"],
                key="digest_keyword_scope",
                horizontal=True,
                format_func=lambda value: {
                    "abstract": "Abstract",
                    "title_abstract": "Title + abstract",
                    "title": "Title only",
                }[value],
            )
            st.multiselect("Digest article types", ARTICLE_TYPES, key="digest_article_types")
            st.toggle("Digest require abstract", key="digest_require_abstract")
            st.toggle(
                "Digest research-like only",
                key="digest_research_only",
                help="Filters out records without substantial abstracts and common correction/news-like titles.",
            )
            digest_range_cols = st.columns([1, 1, 1])
            digest_range_cols[0].number_input(
                "Digest window",
                min_value=1,
                max_value=3650,
                step=1,
                key="digest_window_value",
            )
            digest_range_cols[1].selectbox(
                "Digest unit",
                list(TIME_WINDOW_UNITS),
                key="digest_window_unit",
                format_func=lambda value: TIME_WINDOW_LABELS[value],
            )
            digest_range_cols[2].number_input(
                "Digest max",
                min_value=5,
                max_value=200,
                step=5,
                key="digest_max_results",
            )

        save_col, send_col = st.columns(2)
        save_clicked = save_col.button("Save", type="primary", use_container_width=True)
        if save_clicked:
            save_settings(_settings_payload())
            st.success("Saved.")

        if send_col.button("Test email", use_container_width=True):
            query = _build_digest_query()
            articles = _filter_results(
                fetch_candidate_articles(query, st.session_state.digest_keywords, st.session_state.digest_keyword_match),
                st.session_state.digest_keywords,
                st.session_state.digest_keyword_match,
                st.session_state.digest_require_abstract,
                st.session_state.digest_research_only,
                st.session_state.digest_keyword_scope,
            )[: st.session_state.digest_max_results]
            email_settings = _email_settings_from_payload(_settings_payload())
            send_digest_email(email_settings, replace(query, keywords=st.session_state.digest_keywords), articles)
            record_usage(test_pushes=1)
            st.success("Digest sent.")

        if st.button("Register schedule", use_container_width=True, disabled=not st.session_state.schedule_enabled):
            save_settings(_settings_payload())
            result = _register_schedule()
            if result.returncode == 0:
                st.success("Scheduled digest registered.")
            else:
                st.error(result.stderr or result.stdout or "Failed to register scheduled task.")

    query = _build_query()
    _render_app_header(query)

    action_cols = st.columns([5, 1])
    action_cols[0].markdown(
        """
        <div class="section-rule">
            <h2>Latest publications</h2>
            <span>Sorted by publication date from OpenAlex</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    fetch = action_cols[1].button("Refresh results", type="primary", use_container_width=True)
    if fetch or "articles" not in st.session_state:
        with st.spinner("Fetching OpenAlex records..."):
            search_result = fetch_candidate_articles_with_diagnostics(
                query,
                st.session_state.keywords,
                st.session_state.keyword_match,
            )
            filtered_articles, filter_warnings = filter_search_results(
                search_result.articles,
                st.session_state.keywords,
                st.session_state.keyword_match,
                st.session_state.require_abstract,
                st.session_state.research_only,
                st.session_state.keyword_scope,
                search_result.warnings,
            )
            st.session_state.articles = filtered_articles[: st.session_state.max_results]
            st.session_state.search_warnings = search_result.warnings + filter_warnings
            record_usage(searches=1, articles_seen=len(st.session_state.articles))
            record_keywords(parse_keyword_terms(st.session_state.keywords))

    articles = st.session_state.articles
    for warning in _visible_search_warnings(st.session_state.get("search_warnings", [])):
        st.warning(warning)
    if not articles:
        _render_empty_state()
        return

    _render_result_overview(articles, query)
    result_table = _result_table_with_hits(articles, st.session_state.keywords, st.session_state.keyword_scope)
    st.dataframe(result_table, use_container_width=True, hide_index=True)
    csv_cols = st.columns([5, 1])
    with csv_cols[1]:
        st.markdown("<div class='compact-download'>", unsafe_allow_html=True)
        st.download_button(
            "Download CSV",
            result_table.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"nature-track-{query.to_date.isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.divider()
    st.markdown(
        """
        <div class="section-rule">
            <h2>Article details</h2>
            <span>Abstracts, links, downloads, and AI notes</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for index, article in enumerate(articles):
        _render_article(article, index)
    _render_notes_panel()


def _render_notes_panel() -> None:
    vault_path = st.session_state.obsidian_vault_path.strip()
    root_folder = st.session_state.obsidian_root_folder.strip() or "Nature-track"
    if not vault_path:
        return

    notes = paper_notes(vault_path, root_folder)
    st.divider()
    st.markdown(
        """
        <div class="section-rule">
            <h2>Notes</h2>
            <span>Local Obsidian paper notes</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not notes:
        st.caption("No paper notes yet. Click Summarize on an article to create one.")
        return

    labels = [_note_label(path) for path in notes]
    selected_label = st.selectbox("Paper notes", labels, label_visibility="collapsed")
    selected_note = notes[labels.index(selected_label)]
    note_text = selected_note.read_text(encoding="utf-8")
    open_uri = obsidian_open_uri(selected_note, vault_path)
    action_cols = st.columns([4, 1])
    action_cols[0].caption(str(selected_note))
    action_cols[1].markdown(
        f"<a href='{escape(open_uri)}' target='_self'>Open in Obsidian</a>",
        unsafe_allow_html=True,
    )
    st.markdown(_trim_frontmatter(note_text))


def _note_label(path: Path) -> str:
    return path.stem


def _trim_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text


def _visible_search_warnings(warnings: list[str]) -> list[str]:
    visible = []
    for warning in warnings:
        if "Crossref supplied" in warning and not any("OpenAlex is rate-limited" in item for item in warnings):
            continue
        if warning.startswith("OpenAlex search failed") and any("continuing with Crossref" in item for item in warnings):
            continue
        visible.append(warning)
    return visible[:3]


if __name__ == "__main__":
    main()
