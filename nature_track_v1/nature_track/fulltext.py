from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import re
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from nature_track.openalex import Article


REQUEST_TIMEOUT = 30
MIN_FULL_TEXT_CHARS = 2500
MAX_FULL_TEXT_CHARS = 90000

HEADERS = {
    "User-Agent": (
        "Nature-track/1.0 (+local research assistant; "
        "contact: nature-track@example.local)"
    )
}


@dataclass(frozen=True)
class FullTextResult:
    status: str
    source_type: str
    source_url: str
    text: str
    message: str
    discovered_pdf_urls: list[str] = field(default_factory=list)

    @property
    def has_full_text(self) -> bool:
        return self.status == "full_text"


def fetch_full_text(article: Article) -> FullTextResult:
    """Read publisher HTML or open PDF text when available.

    This intentionally uses only public pages and direct open PDF URLs. It does
    not attempt login, paywall bypass, or hidden endpoint access.
    """
    html_candidates = _dedupe([article.doi_url, article.landing_page_url])
    pdf_candidates = _dedupe([article.pdf_url])
    best_html: FullTextResult | None = None

    for url in html_candidates:
        result = _fetch_url_text(url)
        if result.has_full_text:
            return result
        if result.text and (best_html is None or len(result.text) > len(best_html.text)):
            best_html = result
        pdf_candidates.extend(result.discovered_pdf_urls)

    for url in _dedupe(pdf_candidates):
        result = _fetch_pdf_text(url)
        if result.has_full_text:
            return result

    if best_html and best_html.text:
        return FullTextResult(
            status="abstract_or_metadata",
            source_type=best_html.source_type,
            source_url=best_html.source_url,
            text=_trim_text(best_html.text, MAX_FULL_TEXT_CHARS),
            message="Publisher page was readable, but it did not look like full article text.",
        )

    fallback_text = article.abstract.strip()
    if fallback_text:
        return FullTextResult(
            status="abstract_only",
            source_type="openalex",
            source_url=article.doi_url or article.landing_page_url,
            text=fallback_text,
            message="Full text was not publicly readable; using OpenAlex abstract only.",
        )

    return FullTextResult(
        status="metadata_only",
        source_type="metadata",
        source_url=article.doi_url or article.landing_page_url,
        text="",
        message="No public full text or abstract was available.",
    )


def extract_html_text(html: str, base_url: str = "") -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"]):
        node.decompose()

    selectors = [
        "article",
        "main article",
        "main",
        "[role='main']",
        ".c-article-body",
        ".article__body",
        ".article-body",
        ".article-section",
        ".body",
        "#body",
    ]
    candidates = []
    for selector in selectors:
        for node in soup.select(selector):
            text = _normalize_text(node.get_text("\n"))
            if text:
                candidates.append(text)

    if not candidates:
        candidates.append(_normalize_text(soup.get_text("\n")))

    text = max(candidates, key=len, default="")
    return _trim_text(_remove_reference_tail(text), MAX_FULL_TEXT_CHARS)


def _fetch_url_text(url: str) -> FullTextResult:
    if not url:
        return FullTextResult("unavailable", "html", "", "", "No URL was available.")
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as error:
        return FullTextResult("unavailable", "html", url, "", f"Publisher page could not be read: {error}")

    content_type = response.headers.get("content-type", "").casefold()
    final_url = response.url or url
    if "pdf" in content_type or final_url.casefold().endswith(".pdf"):
        return _parse_pdf_response(response.content, final_url)

    pdf_urls = _pdf_links(response.text, final_url)
    text = extract_html_text(response.text, final_url)
    status = "full_text" if _looks_like_full_text(text) else "abstract_or_metadata"
    return FullTextResult(
        status=status,
        source_type="html",
        source_url=final_url,
        text=text,
        message="Publisher HTML was read." if status == "full_text" else "Publisher HTML did not look like full text.",
        discovered_pdf_urls=pdf_urls,
    )


def _fetch_pdf_text(url: str) -> FullTextResult:
    if not url:
        return FullTextResult("unavailable", "pdf", "", "", "No PDF URL was available.")
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as error:
        return FullTextResult("unavailable", "pdf", url, "", f"PDF could not be read: {error}")
    return _parse_pdf_response(response.content, response.url or url)


def _parse_pdf_response(content: bytes, url: str) -> FullTextResult:
    try:
        reader = PdfReader(BytesIO(content))
        pages = [_normalize_text(page.extract_text() or "") for page in reader.pages[:40]]
    except Exception as error:  # pypdf raises several parser-specific exceptions.
        return FullTextResult("unavailable", "pdf", url, "", f"PDF text could not be parsed: {error}")

    text = _trim_text(_remove_reference_tail("\n\n".join(page for page in pages if page)), MAX_FULL_TEXT_CHARS)
    status = "full_text" if _looks_like_full_text(text) else "abstract_or_metadata"
    return FullTextResult(
        status=status,
        source_type="pdf",
        source_url=url,
        text=text,
        message="Open PDF was parsed." if status == "full_text" else "PDF did not contain enough readable article text.",
    )


def _pdf_links(html_text: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    links = [
        node.get("href", "")
        for node in soup.select("a[href], link[href]")
        if ".pdf" in node.get("href", "").casefold()
    ]
    links.extend(
        node.get("content", "")
        for node in soup.select("meta[name='citation_pdf_url'], meta[property='citation_pdf_url']")
        if node.get("content")
    )
    links.extend(re.findall(r"https?://[^\s)>\"]+\.pdf(?:\?[^\s)>\"]*)?", html_text, flags=re.IGNORECASE))
    return _dedupe(urljoin(base_url, link) for link in links)


def _looks_like_full_text(text: str) -> bool:
    lowered = text.casefold()
    section_hits = sum(
        marker in lowered
        for marker in [
            "introduction",
            "methods",
            "materials and methods",
            "results",
            "discussion",
            "conclusion",
            "references",
        ]
    )
    return len(text) >= MIN_FULL_TEXT_CHARS and section_hits >= 2


def _remove_reference_tail(text: str) -> str:
    match = re.search(r"\n\s*(references|acknowledgements|data availability)\s*\n", text, flags=re.IGNORECASE)
    if match and match.start() > 2500:
        return text[: match.start()]
    return text


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    compact = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", compact).strip()


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", maxsplit=1)[0].strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = (value or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
