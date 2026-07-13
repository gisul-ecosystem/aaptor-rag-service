"""
Ingest technical MCQs from QuizAPI.io into the RAG service as mcq_catalog.

Default mode fetches QuizAPI questions, normalizes them, and posts them to the
local aaptor-rag-service ingest endpoint. Set --direct-mongo to write directly
to MongoDB and rebuild the FAISS index in-process.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.settings import get_settings
from db import mongo
from services.rebuild import rebuild_index


QUIZAPI_URL = "https://quizapi.io/api/v1/questions"
DEFAULT_CATEGORIES = [
    "Linux",
    "DevOps",
    "Docker",
    "Kubernetes",
    "Programming",
    "PHP",
    "Python",
    "JavaScript",
    "MySQL",
    "CMS",
    "Code",
]
DEFAULT_DIFFICULTIES = ["Easy", "Medium", "Hard"]
ANSWER_KEYS = ["answer_a", "answer_b", "answer_c", "answer_d", "answer_e", "answer_f"]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return html.unescape(str(value)).strip()


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in cleaned.split("-") if part)


def _stable_id(question: str, source_id: Any) -> str:
    raw = f"quizapi:{source_id}:{question}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    if source_id:
        return f"quizapi-{source_id}-{digest}"
    return f"quizapi-{digest}"


def _normalize_question(item: dict[str, Any]) -> dict[str, Any] | None:
    question = _clean_text(item.get("question") or item.get("text"))
    if not question:
        return None

    options: list[dict[str, Any]] = []

    answers = item.get("answers") or {}
    if isinstance(answers, list):
        for index, answer in enumerate(answers[:6]):
            if not isinstance(answer, dict):
                continue
            text = _clean_text(answer.get("text"))
            if not text:
                continue
            options.append(
                {
                    "label": chr(ord("A") + index),
                    "text": text,
                    "isCorrect": bool(answer.get("isCorrect")),
                }
            )
    elif isinstance(answers, dict):
        correct_answers = item.get("correct_answers") or {}
        for index, answer_key in enumerate(ANSWER_KEYS):
            text = _clean_text(answers.get(answer_key))
            if not text:
                continue
            is_correct = str(correct_answers.get(f"{answer_key}_correct", "false")).lower() == "true"
            options.append(
                {
                    "label": chr(ord("A") + index),
                    "text": text,
                    "isCorrect": is_correct,
                }
            )

    if len(options) < 4:
        return None

    if sum(1 for option in options if option["isCorrect"]) != 1:
        return None

    options = options[:4]
    if sum(1 for option in options if option["isCorrect"]) != 1:
        return None

    category = _clean_text(item.get("category")) or "Technical"
    difficulty = (_clean_text(item.get("difficulty")) or "Medium").capitalize()
    if difficulty not in {"Easy", "Medium", "Hard"}:
        difficulty = "Medium"

    tags = []
    for tag in item.get("tags") or []:
        name = _clean_text(tag.get("name") if isinstance(tag, dict) else tag)
        if name:
            tags.append(name)

    explanation = _clean_text(item.get("explanation")) or _clean_text(item.get("description"))
    if not explanation:
        correct = next(option["text"] for option in options if option["isCorrect"])
        explanation = f"The correct answer is {correct}."

    source_id = item.get("id")
    doc_id = _stable_id(question, source_id)
    topic_parts = [category, *tags]

    return {
        "id": doc_id,
        "source": "quizapi.io",
        "source_id": str(source_id or item.get("quizId") or ""),
        "title": question[:160],
        "question": question,
        "description": _clean_text(item.get("description")),
        "options": options,
        "explanation": explanation,
        "difficulty": difficulty,
        "category": category,
        "domain": category.lower(),
        "tags": tags,
        "topics": topic_parts,
        "multiple_correct_answers": False,
        "quiz_id": _clean_text(item.get("quizId")),
        "quiz_title": _clean_text(item.get("quizTitle")),
        "source_url": "https://quizapi.io",
    }


async def _fetch_batch(
    client: httpx.AsyncClient,
    api_key: str,
    category: str,
    difficulty: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]] | None:
    response = await client.get(
        QUIZAPI_URL,
        params={
            "api_key": api_key,
            "category": category,
            "difficulty": difficulty.lower(),
            "limit": limit,
            "offset": offset,
            "single_answer_only": "true",
        },
    )
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "")
        message = "[RATE_LIMIT] QuizAPI returned 429 Too Many Requests"
        if retry_after:
            message += f"; retry_after={retry_after}s"
        print(message)
        return None
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected QuizAPI response for {category}/{difficulty}: {data!r}")
    return data


async def fetch_quizapi_entries(
    api_key: str,
    categories: list[str],
    difficulties: list[str],
    limit: int,
    max_pages: int,
    pause_seconds: float,
) -> list[dict[str, Any]]:
    entries_by_id: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for category in categories:
            for difficulty in difficulties:
                for page in range(max_pages):
                    offset = page * limit
                    print(
                        f"[FETCH] category={category} difficulty={difficulty} "
                        f"limit={limit} offset={offset}"
                    )
                    batch = await _fetch_batch(client, api_key, category, difficulty, limit, offset)
                    if batch is None:
                        print(
                            "[STOP] rate limit reached; returning collected entries "
                            f"total_unique={len(entries_by_id)}"
                        )
                        return list(entries_by_id.values())
                    if not batch:
                        print(f"[STOP] empty page category={category} difficulty={difficulty} offset={offset}")
                        break

                    kept = 0
                    before = len(entries_by_id)
                    for item in batch:
                        normalized = _normalize_question(item)
                        if normalized:
                            entries_by_id[normalized["id"]] = normalized
                            kept += 1
                    added = len(entries_by_id) - before
                    print(
                        f"[OK] received={len(batch)} normalized={kept} "
                        f"added={added} total_unique={len(entries_by_id)}"
                    )
                    if len(batch) < limit:
                        print(f"[STOP] final page category={category} difficulty={difficulty}")
                        break
                    if pause_seconds > 0:
                        time.sleep(pause_seconds)
    return list(entries_by_id.values())


async def ingest_via_service(entries: list[dict[str, Any]], service_url: str, admin_api_key: str) -> dict[str, Any]:
    headers = {"x-api-key": admin_api_key} if admin_api_key else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        response = await client.post(
            f"{service_url.rstrip('/')}/api/v1/ingest/mcq",
            json={"entries": entries},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


async def ingest_direct_mongo(entries: list[dict[str, Any]]) -> dict[str, Any]:
    upserted = mongo.upsert_entries("mcq", entries)
    rebuilt = await rebuild_index("mcq")
    return {"competency": "mcq", "upserted": upserted, **rebuilt}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest QuizAPI.io questions into mcq_catalog")
    parser.add_argument("--api-key", default=os.getenv("QUIZAPI_KEY", ""), help="QuizAPI.io API key")
    parser.add_argument("--category", action="append", dest="categories", help="Category to fetch; can repeat")
    parser.add_argument("--difficulty", action="append", dest="difficulties", help="Difficulty to fetch; can repeat")
    parser.add_argument("--limit", type=int, default=20, help="Questions per category/difficulty request")
    parser.add_argument("--max-pages", type=int, default=1, help="Pages to fetch per category/difficulty")
    parser.add_argument("--pause-seconds", type=float, default=0.5, help="Delay between QuizAPI calls")
    parser.add_argument("--service-url", default=os.getenv("RAG_SERVICE_URL", "http://127.0.0.1:7003"))
    parser.add_argument("--admin-api-key", default=os.getenv("ADMIN_API_KEY", ""))
    parser.add_argument("--direct-mongo", action="store_true", help="Write directly to MongoDB and rebuild locally")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and normalize without ingesting")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("QUIZAPI_KEY is required. Pass --api-key or set QUIZAPI_KEY.")

    categories = args.categories or DEFAULT_CATEGORIES
    difficulties = args.difficulties or DEFAULT_DIFFICULTIES
    entries = await fetch_quizapi_entries(
        api_key=args.api_key,
        categories=categories,
        difficulties=difficulties,
        limit=args.limit,
        max_pages=args.max_pages,
        pause_seconds=args.pause_seconds,
    )

    print(f"[SUMMARY] normalized_entries={len(entries)}")
    if args.dry_run:
        return

    if args.direct_mongo:
        settings = get_settings()
        print(f"[INGEST] direct MongoDB uri={settings.mongodb_uri} db={settings.mongodb_db_name}")
        result = await ingest_direct_mongo(entries)
    else:
        print(f"[INGEST] service={args.service_url}")
        result = await ingest_via_service(entries, args.service_url, args.admin_api_key)
    print(f"[DONE] {result}")


if __name__ == "__main__":
    asyncio.run(main())
