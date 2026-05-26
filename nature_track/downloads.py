from __future__ import annotations

import re
from pathlib import Path

import requests

from nature_track.openalex import Article


REQUEST_TIMEOUT = 45
MAX_FILENAME_LENGTH = 180
JOURNAL_ABBREVIATIONS = {
    "nature": "N",
    "nature communications": "NC",
    "nature geoscience": "NG",
    "nature climate change": "NCC",
    "nature ecology & evolution": "NEE",
    "nature sustainability": "NS",
    "nature water": "NW",
    "science": "S",
    "science advances": "SA",
    "one earth": "OE",
    "global change biology": "GCB",
    "earth system science data": "ESSD",
    "environmental research letters": "ERL",
    "geophysical research letters": "GRL",
    "journal of geophysical research: biogeosciences": "JGRB",
    "remote sensing of environment": "RSE",
}


def download_article_pdf(article: Article, folder: str) -> Path:
    pdf_urls = _candidate_pdf_urls(article)
    if not pdf_urls:
        raise ValueError("No direct PDF URL is available for this article.")
    target_dir = Path(folder).expanduser()
    if not target_dir.exists():
        raise FileNotFoundError(f"Download folder does not exist: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"Download path is not a folder: {target_dir}")
    target = _unique_path(target_dir / (_article_filename(article) + ".pdf"))

    errors: list[str] = []
    for pdf_url in pdf_urls:
        try:
            response = requests.get(pdf_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.casefold() and not response.content.startswith(b"%PDF"):
                raise ValueError("The download URL did not return a PDF file.")

            target.write_bytes(response.content)
            return target
        except Exception as exc:
            errors.append(f"{pdf_url}: {exc}")

    raise ValueError("No candidate PDF URL returned a PDF file. " + " | ".join(errors[:2]))


def _article_filename(article: Article) -> str:
    author = _safe_part((article.first_author or "Unknown").split()[-1])
    year = (article.publication_date[:4] or "0000")[-2:]
    journal = _safe_part(_journal_abbreviation(article.journal or "Unknown"))
    title = _safe_title(article.title or "Untitled")
    base = f"{author}_{year}_{journal}_{title}"
    return base[:MAX_FILENAME_LENGTH].rstrip(" ._-")


def _safe_part(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace(" ", "_") or "Unknown"


def _safe_title(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    return re.sub(r"\s+", " ", value).strip() or "Untitled"


def _journal_abbreviation(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    if normalized in JOURNAL_ABBREVIATIONS:
        return JOURNAL_ABBREVIATIONS[normalized]
    words = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(word[0].upper() for word in words[:5]) or "Unknown"


def _candidate_pdf_urls(article: Article) -> list[str]:
    urls = [article.pdf_url]
    doi = article.doi.strip()
    doi_suffix = doi.split("/", maxsplit=1)[-1] if "/" in doi else doi
    landing_page = article.landing_page_url.strip()

    if doi.startswith("10.1038/") and doi_suffix:
        urls.extend(
            [
                f"https://www.nature.com/articles/{doi_suffix}.pdf",
                f"https://www.nature.com/articles/{doi_suffix}.pdf?pdf=button%20sticky",
            ]
        )
    if doi.startswith("10.1126/") and doi_suffix:
        urls.append(f"https://www.science.org/doi/pdf/{doi}")
    if doi.startswith("10.1111/") and doi:
        urls.append(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}")
        urls.append(f"https://onlinelibrary.wiley.com/doi/pdf/{doi}")
    if landing_page.endswith(".pdf"):
        urls.append(landing_page)

    return _dedupe_urls(urls)


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen = set()
    result = []
    for url in urls:
        cleaned = (url or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique filename for {path}")
