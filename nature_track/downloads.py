from __future__ import annotations

import re
from pathlib import Path

import requests

from nature_track.openalex import Article


REQUEST_TIMEOUT = 45
MAX_FILENAME_LENGTH = 180


def download_article_pdf(article: Article, folder: str) -> Path:
    if not article.pdf_url:
        raise ValueError("No direct PDF URL is available for this article.")
    target_dir = Path(folder).expanduser()
    if not target_dir.exists():
        raise FileNotFoundError(f"Download folder does not exist: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"Download path is not a folder: {target_dir}")
    target = _unique_path(target_dir / (_article_filename(article) + ".pdf"))

    response = requests.get(article.pdf_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "pdf" not in content_type.casefold() and not response.content.startswith(b"%PDF"):
        raise ValueError("The download URL did not return a PDF file.")

    target.write_bytes(response.content)
    return target


def _article_filename(article: Article) -> str:
    author = _safe_part((article.first_author or "Unknown").split()[-1])
    year = (article.publication_date[:4] or "0000")[-2:]
    journal = _safe_part(article.journal or "Unknown")
    title = _safe_part(article.title or "Untitled")
    base = f"{author}_{year}_{journal}_{title}"
    return base[:MAX_FILENAME_LENGTH].rstrip(" ._-")


def _safe_part(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace(" ", "_") or "Unknown"


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
