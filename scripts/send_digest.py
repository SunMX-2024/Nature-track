from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nature_track.config import DEFAULT_SETTINGS, load_settings
from nature_track.emailer import EmailSettings, send_digest_email
from nature_track.filters import filter_article_quality, filter_articles_by_abstract
from nature_track.openalex import ArticleQuery, fetch_articles
from nature_track.usage import record_usage


def main() -> None:
    settings = DEFAULT_SETTINGS | load_settings()
    settings["email"] = DEFAULT_SETTINGS["email"] | settings.get("email", {})
    settings["digest"] = DEFAULT_SETTINGS["digest"] | settings.get("digest", {})
    digest = settings["digest"]

    end = date.today()
    start = end - timedelta(days=digest["days_back"])
    query = ArticleQuery(
        journals=digest["journals"],
        from_date=start,
        to_date=end,
        keywords=digest["keywords"],
        article_types=digest["article_types"],
        max_results=min(digest["max_results"] * 3, 200),
    )
    articles = filter_articles_by_abstract(
        filter_article_quality(
            fetch_articles(query),
            digest.get("require_abstract", True),
            digest.get("research_only", True),
        ),
        digest["keywords"],
        digest.get("keyword_match", "all"),
    )[: digest["max_results"]]
    email = settings["email"]
    send_digest_email(
        EmailSettings(
            smtp_host=email["smtp_host"],
            smtp_port=email["smtp_port"],
            smtp_user=email["smtp_user"],
            smtp_password=email["smtp_password"],
            sender=email["sender"],
            recipient=email["recipient"],
            use_tls=email["use_tls"],
        ),
        query,
        articles,
    )
    record_usage(scheduled_pushes=1)
    print(f"Sent Nature-track digest with {len(articles)} articles.")


if __name__ == "__main__":
    main()
