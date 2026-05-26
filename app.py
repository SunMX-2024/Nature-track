from __future__ import annotations

from datetime import date, time, timedelta
import subprocess

import pandas as pd
import streamlit as st

from nature_track.config import DEFAULT_SETTINGS, load_settings, save_settings
from nature_track.emailer import EMAIL_PROVIDERS, EmailSettings, send_digest_email
from nature_track.filters import filter_article_quality, filter_articles_by_abstract
from nature_track.filters import parse_keyword_terms
from nature_track.openalex import ArticleQuery, fetch_articles
from nature_track.usage import frequent_keywords, load_usage, record_keywords, record_usage


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


def _settings_payload() -> dict:
    return {
        "journals": st.session_state.selected_journals,
        "keywords": st.session_state.keywords.strip(),
        "keyword_match": st.session_state.keyword_match,
        "article_types": st.session_state.article_types,
        "require_abstract": st.session_state.require_abstract,
        "research_only": st.session_state.research_only,
        "days_back": st.session_state.days_back,
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
            "article_types": st.session_state.digest_article_types,
            "require_abstract": st.session_state.digest_require_abstract,
            "research_only": st.session_state.digest_research_only,
            "days_back": st.session_state.digest_days_back,
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
    st.session_state.setdefault("custom_journal", "")
    st.session_state.setdefault("keywords", defaults["keywords"])
    st.session_state.setdefault("keyword_match", defaults.get("keyword_match", "all"))
    st.session_state.setdefault("article_types", defaults["article_types"])
    st.session_state.setdefault("require_abstract", bool(defaults.get("require_abstract", True)))
    st.session_state.setdefault("research_only", bool(defaults.get("research_only", True)))
    st.session_state.setdefault("days_back", int(defaults["days_back"]))
    st.session_state.setdefault("max_results", int(defaults["max_results"]))
    st.session_state.setdefault("schedule_enabled", bool(schedule["enabled"]))
    st.session_state.setdefault("schedule_frequency", schedule["frequency"])
    st.session_state.setdefault("schedule_weekday", schedule["weekday"])
    st.session_state.setdefault("schedule_time", _parse_time(schedule["time"]))
    st.session_state.setdefault("digest_journals", _dedupe(digest["journals"]))
    st.session_state.setdefault("digest_custom_journal", "")
    st.session_state.setdefault("digest_keywords", digest["keywords"])
    st.session_state.setdefault("digest_keyword_match", digest.get("keyword_match", "all"))
    st.session_state.setdefault("digest_article_types", digest["article_types"])
    st.session_state.setdefault("digest_require_abstract", bool(digest.get("require_abstract", True)))
    st.session_state.setdefault("digest_research_only", bool(digest.get("research_only", True)))
    st.session_state.setdefault("digest_days_back", int(digest["days_back"]))
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
    start = end - timedelta(days=st.session_state.days_back)
    return ArticleQuery(
        journals=st.session_state.selected_journals,
        from_date=start,
        to_date=end,
        keywords="",
        article_types=st.session_state.article_types,
        max_results=200,
        max_pages=max((st.session_state.max_results // 20) + 2, 3),
    )


def _build_digest_query() -> ArticleQuery:
    end = date.today()
    start = end - timedelta(days=st.session_state.digest_days_back)
    return ArticleQuery(
        journals=st.session_state.digest_journals,
        from_date=start,
        to_date=end,
        keywords="",
        article_types=st.session_state.digest_article_types,
        max_results=200,
        max_pages=max((st.session_state.digest_max_results // 20) + 2, 3),
    )


def _parse_time(value: str) -> time:
    try:
        hour, minute = value.split(":", maxsplit=1)
        return time(hour=int(hour), minute=int(minute))
    except (AttributeError, TypeError, ValueError):
        return time(hour=8, minute=0)


def _filter_results(articles, keywords: str, keyword_match: str, require_abstract: bool, research_only: bool):
    return filter_articles_by_abstract(
        filter_article_quality(articles, require_abstract, research_only),
        keywords,
        keyword_match,
    )


def _append_keyword(key: str, target: str = "keywords") -> None:
    existing = getattr(st.session_state, target, "")
    terms = parse_keyword_terms(existing)
    if key.casefold() not in {term.casefold() for term in terms}:
        st.session_state[target] = (existing.rstrip() + "\n" + key).strip()


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
    return sorted(_dedupe(sum(JOURNAL_GROUPS.values(), []) + extra))


def _format_authors(article) -> str:
    corresponding = {name.casefold() for name in article.corresponding_authors}
    authors = []
    for name in article.authors:
        suffix = "*" if name.casefold() in corresponding else ""
        authors.append(f"{name}{suffix}")
    if not authors and article.first_author:
        authors.append(article.first_author)
    return ", ".join(authors)


def _render_article(article) -> None:
    title = article.title or "Untitled article"
    expander_label = f"{title}    |    {article.journal}" if article.journal else title
    with st.expander(expander_label):
        meta = " | ".join(
            part
            for part in [
                article.publication_date,
                article.article_type,
                "Open access" if article.is_oa else "Non-OA or unknown",
            ]
            if part
        )
        st.markdown(f"<div class='article-meta'>{meta}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='article-abstract'>{article.abstract or 'No abstract available from OpenAlex.'}</div>",
            unsafe_allow_html=True,
        )
        authors = _format_authors(article)
        if authors:
            st.markdown(
                f"<div class='article-authors'>{authors}</div>",
                unsafe_allow_html=True,
            )
        spacer, doi_col, download_col = st.columns([4.2, 0.9, 1.1])
        if article.doi_url:
            doi_col.link_button("DOI", article.doi_url, use_container_width=True)
        target_url = article.pdf_url or article.landing_page_url
        if target_url:
            download_col.link_button("Download", target_url, use_container_width=True)


def _render_usage_fab() -> None:
    usage = load_usage()
    email_pushes = int(usage["test_pushes"]) + int(usage["scheduled_pushes"])
    st.markdown(
        f"""
        <div class="usage-fab">
            <details>
                <summary title="Usage statistics">☆</summary>
                <div class="usage-panel">
                    <div class="usage-title">Usage</div>
                    <div><span>Views</span><strong>{usage["views"]}</strong></div>
                    <div><span>Searches</span><strong>{usage["searches"]}</strong></div>
                    <div><span>Articles seen</span><strong>{usage["articles_seen"]}</strong></div>
                    <div><span>Email pushes</span><strong>{email_pushes}</strong></div>
                    <p>Last view: {usage["last_view_at"] or "none"}</p>
                    <p>Last search: {usage["last_search_at"] or "none"}</p>
                    <p>Last push: {usage["last_push_at"] or "none"}</p>
                </div>
            </details>
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

    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; max-width: 1280px;}
        div[data-testid="stMetric"] {border: 1px solid #e4e9ee; padding: 0.35rem 0.45rem; border-radius: 6px; background: #fbfcfd;}
        div[data-testid="stMetric"] label {font-size: 0.72rem !important; color: #6d7782 !important;}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {font-size: 1rem !important;}
        .stButton > button {border-radius: 6px;}
        div[data-testid="stExpander"] details summary p {
            font-size: 1.18rem !important;
            font-weight: 750 !important;
            line-height: 1.35 !important;
        }
        div[data-testid="stExpander"] details {
            border-radius: 6px !important;
        }
        .article-meta {
            display: block;
            text-align: right;
            font-size: 0.95rem;
            color: #7a8490;
            padding-bottom: 0.45rem;
        }
        .article-abstract {
            font-size: 1.08rem;
            line-height: 1.72;
            color: #152536;
            margin: 0.35rem 0 0.9rem;
        }
        .article-authors {
            font-size: 0.98rem;
            line-height: 1.55;
            color: #4f5d69;
            border-top: 1px solid #edf0f2;
            padding-top: 0.65rem;
            margin: 0.4rem 0 0.85rem;
        }
        .compact-download div[data-testid="stDownloadButton"] button {
            min-height: 2rem;
            padding: 0.25rem 0.65rem;
            font-size: 0.86rem;
        }
        .usage-fab {
            position: fixed;
            right: 1.1rem;
            bottom: 1.1rem;
            z-index: 9999;
            font-family: inherit;
        }
        .usage-fab summary {
            list-style: none;
            width: 2.6rem;
            height: 2.6rem;
            border-radius: 50%;
            border: 1px solid #d8e0e7;
            background: #ffffff;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.14);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.35rem;
            color: #2d4054;
        }
        .usage-fab summary::-webkit-details-marker {display: none;}
        .usage-panel {
            position: absolute;
            right: 0;
            bottom: 3.1rem;
            width: 15rem;
            border: 1px solid #d8e0e7;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 14px 32px rgba(15, 23, 42, 0.16);
            padding: 0.85rem;
            color: #1f2f3d;
        }
        .usage-title {
            font-weight: 750;
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
            color: #74808c;
            font-size: 0.78rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _render_usage_fab()
    st.title(APP_TITLE)
    st.caption("Track recent Earth and environmental science papers from target journals.")

    with st.sidebar:
        st.subheader("Tracker")
        journal_tabs = st.tabs(list(JOURNAL_GROUPS.keys()))
        for tab, journals in zip(journal_tabs, JOURNAL_GROUPS.values(), strict=True):
            with tab:
                for journal in journals:
                    if st.button(journal, key=f"add_{journal}", use_container_width=True):
                        st.session_state.selected_journals = _dedupe(
                            st.session_state.selected_journals + [journal]
                        )
                        st.rerun()

        add_cols = st.columns([3, 1])
        add_cols[0].text_input("Add journal", key="custom_journal", placeholder="e.g. Biogeosciences")
        if add_cols[1].button("Add", use_container_width=True):
            st.session_state.selected_journals = _dedupe(
                st.session_state.selected_journals + [st.session_state.custom_journal]
            )
            st.session_state.custom_journal = ""
            st.rerun()

        st.multiselect(
            "Selected journals",
            options=_journal_options(st.session_state.selected_journals),
            key="selected_journals",
        )

        st.text_area(
            "Abstract keywords",
            key="keywords",
            placeholder="carbon cycle\ndrought\nsoil respiration",
            height=90,
            help="Matched locally against article abstracts after journal/date/type filtering.",
        )
        common_keywords = frequent_keywords()
        if common_keywords:
            st.caption("Frequent keywords")
            keyword_cols = st.columns(2)
            for index, keyword in enumerate(common_keywords):
                if keyword_cols[index % 2].button(keyword, key=f"kw_{keyword}", use_container_width=True):
                    _append_keyword(keyword)
                    st.rerun()
        st.radio(
            "Keyword match",
            ["all", "any"],
            key="keyword_match",
            horizontal=True,
            format_func=lambda value: "Match all" if value == "all" else "Match any",
        )
        st.number_input("Publication window, days", min_value=1, max_value=3650, step=1, key="days_back")
        st.multiselect("Article types", ARTICLE_TYPES, key="article_types")
        st.toggle("Require abstract", key="require_abstract")
        st.toggle(
            "Research-like only",
            key="research_only",
            help="Filters out records without substantial abstracts and common correction/news-like titles.",
        )
        st.number_input("Max results", min_value=5, max_value=200, step=5, key="max_results")

        st.divider()
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

        st.divider()
        st.subheader("Auto delivery")
        st.toggle("Enable scheduled digest", key="schedule_enabled")
        st.selectbox(
            "Frequency",
            ["weekly", "daily"],
            key="schedule_frequency",
            format_func=lambda value: "Weekly" if value == "weekly" else "Daily",
        )
        if st.session_state.schedule_frequency == "weekly":
            st.selectbox("Weekday", WEEKDAYS, key="schedule_weekday")
        st.time_input("Send time", key="schedule_time")

        with st.expander("Digest content", expanded=True):
            if st.button("Copy current tracker filters", use_container_width=True):
                st.session_state.digest_journals = st.session_state.selected_journals
                st.session_state.digest_keywords = st.session_state.keywords
                st.session_state.digest_keyword_match = st.session_state.keyword_match
                st.session_state.digest_article_types = st.session_state.article_types
                st.session_state.digest_require_abstract = st.session_state.require_abstract
                st.session_state.digest_research_only = st.session_state.research_only
                st.session_state.digest_days_back = st.session_state.days_back
                st.session_state.digest_max_results = st.session_state.max_results
                st.rerun()

            st.multiselect(
                "Digest journals",
                options=_journal_options(st.session_state.digest_journals),
                key="digest_journals",
            )
            digest_add_cols = st.columns([3, 1])
            digest_add_cols[0].text_input(
                "Add digest journal",
                key="digest_custom_journal",
                placeholder="e.g. Biogeosciences",
            )
            if digest_add_cols[1].button("Add", key="add_digest_journal", use_container_width=True):
                st.session_state.digest_journals = _dedupe(
                    st.session_state.digest_journals + [st.session_state.digest_custom_journal]
                )
                st.session_state.digest_custom_journal = ""
                st.rerun()

            st.text_area(
                "Digest abstract keywords",
                key="digest_keywords",
                placeholder="carbon cycle\ndrought\nsoil respiration",
                height=90,
            )
            st.radio(
                "Digest keyword match",
                ["all", "any"],
                key="digest_keyword_match",
                horizontal=True,
                format_func=lambda value: "Match all" if value == "all" else "Match any",
            )
            st.multiselect("Digest article types", ARTICLE_TYPES, key="digest_article_types")
            st.toggle("Digest require abstract", key="digest_require_abstract")
            st.toggle(
                "Digest research-like only",
                key="digest_research_only",
                help="Filters out records without substantial abstracts and common correction/news-like titles.",
            )
            st.number_input(
                "Digest window, days",
                min_value=1,
                max_value=3650,
                step=1,
                key="digest_days_back",
            )
            st.number_input(
                "Digest max results",
                min_value=5,
                max_value=200,
                step=5,
                key="digest_max_results",
            )

        save_col, send_col = st.columns(2)
        if save_col.button("Save settings", use_container_width=True):
            save_settings(_settings_payload())
            st.success("Saved.")

        if send_col.button("Send test digest", use_container_width=True):
            query = _build_digest_query()
            articles = _filter_results(
                fetch_articles(query),
                st.session_state.digest_keywords,
                st.session_state.digest_keyword_match,
                st.session_state.digest_require_abstract,
                st.session_state.digest_research_only,
            )[: st.session_state.digest_max_results]
            email_settings = _email_settings_from_payload(_settings_payload())
            send_digest_email(email_settings, query, articles)
            record_usage(test_pushes=1)
            st.success("Digest sent.")

        if st.button("Save and register schedule", use_container_width=True, disabled=not st.session_state.schedule_enabled):
            save_settings(_settings_payload())
            result = _register_schedule()
            if result.returncode == 0:
                st.success("Scheduled digest registered.")
            else:
                st.error(result.stderr or result.stdout or "Failed to register scheduled task.")

    top = st.columns([2, 1, 1, 1])
    top[0].markdown("#### Latest publications")
    query = _build_query()
    top[1].metric("Journals", len(query.journals))
    top[2].metric("Window", f"{query.from_date:%m-%d} to {query.to_date:%m-%d}")
    top[3].metric("Types", len(query.article_types) or "All")

    fetch = st.button("Refresh results", type="primary")
    if fetch or "articles" not in st.session_state:
        with st.spinner("Fetching OpenAlex records..."):
            st.session_state.articles = _filter_results(
                fetch_articles(query),
                st.session_state.keywords,
                st.session_state.keyword_match,
                st.session_state.require_abstract,
                st.session_state.research_only,
            )[: st.session_state.max_results]
            record_usage(searches=1, articles_seen=len(st.session_state.articles))
            record_keywords(parse_keyword_terms(st.session_state.keywords))

    articles = st.session_state.articles
    if not articles:
        st.warning("No matching articles found. Try a wider date window or fewer filters.")
        return

    st.dataframe(_result_table(articles), use_container_width=True, hide_index=True)
    csv_cols = st.columns([5, 1])
    with csv_cols[1]:
        st.markdown("<div class='compact-download'>", unsafe_allow_html=True)
        st.download_button(
            "Download CSV",
            _result_table(articles).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"nature-track-{query.to_date.isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
    st.divider()

    for article in articles:
        _render_article(article)


if __name__ == "__main__":
    main()
