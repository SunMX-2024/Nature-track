from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import requests

from nature_track.fulltext import FullTextResult
from nature_track.openalex import Article


DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_REASONING_EFFORT = "max"
REQUEST_TIMEOUT = 90
HEILMEIER_SECTIONS = [
    ("q1_trying_to_do", "What are you trying to do?"),
    ("q2_problem_current_limits", "What is the problem, how is it done today, and what are the limits?"),
    (
        "q3_new_approach_method",
        "What is new in the approach, including core idea, math, method, and why it should succeed?",
    ),
    ("q4_who_cares_impact", "Who cares? If successful, what difference does it make?"),
    ("q5_risks", "What are the risks?"),
    ("q6_cost", "How much will it cost?"),
    ("q7_experiments_results", "What are the experiments and results?"),
]


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    model: str = DEFAULT_MODEL
    language: str = "Chinese, keep technical terms in English where clearer"


def summarize_article(article: Article, full_text: FullTextResult, settings: DeepSeekSettings) -> dict[str, Any]:
    if not settings.api_key.strip():
        raise ValueError("DeepSeek API key is missing.")
    payload = _request_payload(article, full_text, settings)
    response = requests.post(
        DEEPSEEK_CHAT_URL,
        headers={
            "Authorization": f"Bearer {settings.api_key.strip()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    summary = _parse_json_content(content)
    return _normalize_summary(summary, article, full_text)


def _request_payload(article: Article, full_text: FullTextResult, settings: DeepSeekSettings) -> dict[str, Any]:
    article_packet = {
        "title": article.title,
        "journal": article.journal,
        "publication_date": article.publication_date,
        "doi": article.doi,
        "doi_url": article.doi_url,
        "landing_page_url": article.landing_page_url,
        "openalex_topics": article.topics,
        "openalex_concepts": article.concepts,
        "openalex_keywords": article.keywords,
        "abstract": article.abstract,
        "text_status": full_text.status,
        "text_source_type": full_text.source_type,
        "text_source_url": full_text.source_url,
        "readable_text": full_text.text,
    }
    system = (
        "You are a rigorous Earth-system, ecology, conservation, and remote-sensing paper analyst. "
        "Return only valid JSON. Follow a modified Heilmeier's Catechism structure. "
        "Do not create a separate summary section. Do not invent details, numbers, equations, "
        "baselines, or results that are not supported by the supplied text. "
        "If the supplied text is abstract-only or metadata-only, mark confidence as low and say so."
    )
    user = f"""
Summarize this paper for a personal Obsidian knowledge graph.
Write in: {settings.language}.

Required JSON object shape:
{{
  "confidence": "high | medium | low",
  "readable_status": "full_text | abstract_or_metadata | abstract_only | metadata_only",
  "heilmeier": {{
    "q1_trying_to_do": {{"lead": "string", "details": ["string"]}},
    "q2_problem_current_limits": {{"lead": "string", "details": ["string"]}},
    "q3_new_approach_method": {{"lead": "string", "details": ["string"]}},
    "q4_who_cares_impact": {{"lead": "string", "details": ["string"]}},
    "q5_risks": {{"lead": "string", "details": ["string"]}},
    "q6_cost": {{"lead": "string", "details": ["string"]}},
    "q7_experiments_results": {{"lead": "string", "details": ["string"]}}
  }},
  "graph_terms": {{"topics": ["string"], "methods": ["string"], "data": ["string"], "journal": ["string"]}},
  "evidence_quotes": ["up to 5 short quoted phrases copied from the supplied text"]
}}

Heilmeier rules:
- Question 1. What are you trying to do?
- Q1: Open with one plain-language sentence describing the paper's contribution. Avoid jargon and acronyms unless you define them.
- Question 2. What is the problem, how is it done today, and what are the limits of current practice?
- Q2: Explain the scientific problem, current practice at the time of the paper, and the limits of current practice.
- Question 3. What is new in the approach, including core idea, math, and method, and why does the paper claim it will succeed?
- Q3: This is the technical core. Cover the central technical move, mathematical objects or equations if present, how the method works, and why the paper claims it should succeed. If no math is present in the supplied text, say that explicitly.
- Question 4. Who cares? If successful, what difference does it make?
- Q4: Explain who benefits and the likely impact. Because you cannot run web search here, do not cite or claim post-publication adoption unless supplied in the text. Prefix your own judgment with an explicit first-person marker in the requested output language, equivalent to "My analysis is,".
- Question 5. What are the risks?
- Q5: Cover risks acknowledged by the paper and risks you infer. Prefix your own judgment with an explicit first-person marker in the requested output language, equivalent to "My analysis is,".
- Question 6. How much will it cost?
- Q6: Interpret cost as compute, data, field effort, engineering effort, or reproducibility burden, whichever fits the paper. Use only numbers supplied in the text. Prefix your own judgment with an explicit first-person marker in the requested output language, equivalent to "My analysis is,".
- Question 7. What are the experiments and results?
- Q7: Cover experiments, datasets, baselines, metrics, headline results, and any gap between claims and evidence.
- Do not put personal evaluation in Q1 or Q3.
- Each question must start with a one-sentence lead, then short details. If evidence is missing, write that it was not identified instead of guessing.

Graph term rules:
- graph_terms must include arrays named topics, methods, data, journal.
- topics should be broad enough to connect papers, e.g. protected area, grassland, forest, carbon sink, drought, restoration, biodiversity, land-use change.
- methods should name concrete models when present. If no model is named, summarize by analysis strategy and data type, e.g. remote-sensing trend analysis, field experiment, meta-analysis, SEM, machine learning, deep learning, causal inference, statistical regression.
- data should name source or type, e.g. TMF, tree cover, tree height, LST, MODIS, Landsat, GEDI, statistical data, literature review data, field sampling data.
- journal should be the journal name.

Article packet:
{json.dumps(article_packet, ensure_ascii=False)}
""".strip()
    return {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 3500,
        "stream": False,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
    }


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_summary(summary: dict[str, Any], article: Article, full_text: FullTextResult) -> dict[str, Any]:
    if not isinstance(summary, dict):
        summary = {}

    summary["heilmeier"] = _normalize_heilmeier(summary)
    graph_terms = summary.get("graph_terms") if isinstance(summary.get("graph_terms"), dict) else {}
    graph_terms["journal"] = _listify(graph_terms.get("journal") or article.journal)
    graph_terms["topics"] = _dedupe(_listify(graph_terms.get("topics")) + _fallback_topics(article))
    graph_terms["methods"] = _dedupe(_listify(graph_terms.get("methods")))
    graph_terms["data"] = _dedupe(_listify(graph_terms.get("data")))
    summary["graph_terms"] = graph_terms
    summary["journal"] = summary.get("journal") or article.journal
    summary["readable_status"] = summary.get("readable_status") or full_text.status
    summary["confidence"] = summary.get("confidence") or ("high" if full_text.has_full_text else "low")
    for key in ["evidence_quotes"]:
        summary[key] = summary.get(key) if isinstance(summary.get(key), list) else _listify(summary.get(key))
    return summary


def _normalize_heilmeier(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = summary.get("heilmeier") if isinstance(summary.get("heilmeier"), dict) else {}
    fallback = _legacy_heilmeier(summary)
    normalized = {}
    for key, _title in HEILMEIER_SECTIONS:
        normalized[key] = _normalize_heilmeier_section(raw.get(key) or fallback.get(key))
    return normalized


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


def _normalize_heilmeier_section(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        lead = _clean_text(value.get("lead") or value.get("answer") or value.get("summary") or value.get("title"))
        details = _detail_list(value.get("details") or value.get("bullets") or value.get("items"))
        extra = []
        for key, item in value.items():
            if key in {"lead", "answer", "summary", "title", "details", "bullets", "items"}:
                continue
            text = _clean_text(item)
            if text:
                extra.append(f"{key}: {text}")
        details.extend(extra)
        if not lead and details:
            lead = details.pop(0)
        return {"lead": lead, "details": details}

    details = _detail_list(value)
    if details:
        return {"lead": details[0], "details": details[1:]}
    return {"lead": "", "details": []}


def _detail_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value for text in _detail_list(item)]
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
        return "; ".join(_detail_list(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def _first(value: Any) -> str:
    items = _detail_list(value)
    return items[0] if items else ""


def _prefix(label: str, value: Any) -> str:
    text = _clean_text(value)
    return f"{label}: {text}" if text else ""


def _clean_join(values: list[Any]) -> str:
    return " ".join(text for value in values if (text := _clean_text(value)))


def _fallback_topics(article: Article) -> list[str]:
    return _dedupe([*article.keywords[:4], *article.concepts[:4], *article.topics[:4]])


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("term") or item.get("label")
                if name:
                    result.append(str(name))
            else:
                result.append(str(item))
        return [item.strip() for item in result if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


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

