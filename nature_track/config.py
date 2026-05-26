from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "journals": [
        "Nature",
        "Nature Geoscience",
        "Nature Climate Change",
        "Nature Communications",
        "Science",
        "Science Advances",
        "One Earth",
        "Global Change Biology",
    ],
    "keywords": "",
    "keyword_match": "all",
    "article_types": ["article", "review"],
    "require_abstract": True,
    "research_only": True,
    "days_back": 30,
    "max_results": 50,
    "digest": {
        "journals": [
            "Nature",
            "Nature Geoscience",
            "Nature Climate Change",
            "Nature Communications",
            "Science",
            "Science Advances",
            "One Earth",
            "Global Change Biology",
        ],
        "keywords": "",
        "keyword_match": "all",
        "article_types": ["article", "review"],
        "require_abstract": True,
        "research_only": True,
        "days_back": 30,
        "max_results": 50,
    },
    "schedule": {
        "enabled": False,
        "frequency": "weekly",
        "weekday": "Monday",
        "time": "08:00",
    },
    "email": {
        "provider": "QQ Mail",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "sender": "",
        "recipient": "",
        "use_tls": True,
    },
}


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
