from __future__ import annotations

import logging
import numpy as np
from typing import Any

from core import state

logger = logging.getLogger(__name__)

# Minimum cosine similarity score to accept a FAISS match
_MIN_SCORE = 0.3
# Lower threshold for competencies with short text entries (SQL, DSA)
_MIN_SCORE_SQL = 0.15
_MIN_SCORE_DSA = 0.15

# ─────────────────────────────────────────────────────────────────────────────
# AIML Dataset Registry
# Maps topic signals → preferred catalog IDs + required tags.
# Registry lookup runs BEFORE FAISS and ignores difficulty filtering so that
# well-known named datasets (iris, titanic, mnist …) are always returned
# correctly regardless of the requested difficulty level.
# ─────────────────────────────────────────────────────────────────────────────
_AIML_REGISTRY: list[dict] = [
    {
        "topic_signals": ["iris", "iris flower", "iris classification", "iris dataset"],
        "preferred_ids": ["sklearn-iris"],
        "required_tags": ["flowers"],
        "forbidden_ids": ["seaborn-penguins", "hf-beans"],
    },
    {
        "topic_signals": ["penguin", "palmer penguin"],
        "preferred_ids": ["seaborn-penguins"],
        "required_tags": ["biology"],
        "forbidden_ids": ["sklearn-iris"],
    },
    {
        "topic_signals": ["titanic", "titanic survival", "passenger survival"],
        "preferred_ids": ["seaborn-titanic", "openml-titanic", "openml-titanic-survival"],
        "required_tags": ["titanic"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["mnist", "handwritten digit", "digit recognition"],
        "preferred_ids": ["keras-mnist", "openml-mnist-784", "sklearn-digits"],
        "required_tags": ["digits"],
        "forbidden_ids": ["keras-fashion-mnist"],
    },
    {
        "topic_signals": ["fashion mnist", "clothing classification", "apparel classification"],
        "preferred_ids": ["keras-fashion-mnist"],
        "required_tags": ["fashion"],
        "forbidden_ids": ["keras-mnist"],
    },
    {
        "topic_signals": ["cifar", "cifar-10", "cifar10", "object recognition"],
        "preferred_ids": ["keras-cifar10"],
        "required_tags": ["object-recognition"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["customer churn", "churn prediction", "churn analysis", "churn detection"],
        "preferred_ids": ["openml-telco-churn", "openml-bank-churn"],
        "required_tags": ["churn"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["employee attrition", "hr attrition", "staff turnover", "workforce attrition"],
        "preferred_ids": ["openml-hr-attrition"],
        "required_tags": ["attrition"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["fraud detection", "credit card fraud", "transaction fraud"],
        "preferred_ids": ["openml-fraud-detection"],
        "required_tags": ["fraud"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["diabetes prediction", "diabetes detection", "diabetes classification"],
        "preferred_ids": ["openml-pima-diabetes", "sklearn-diabetes"],
        "required_tags": ["diabetes"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["heart disease", "cardiac prediction", "heart attack", "cardiovascular"],
        "preferred_ids": ["openml-heart-disease"],
        "required_tags": ["heart-disease"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["breast cancer", "cancer detection", "tumor classification", "malignant benign", "cancer prediction"],
        "preferred_ids": ["sklearn-breast-cancer"],
        "required_tags": ["breast-cancer"],
        "forbidden_ids": ["openml-lung-cancer", "openml-covid-symptoms"],
    },
    {
        "topic_signals": ["house price", "housing price", "real estate prediction", "home price"],
        "preferred_ids": ["sklearn-california-housing"],
        "required_tags": ["real-estate"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["sentiment analysis", "review sentiment", "opinion mining"],
        "preferred_ids": ["hf-imdb", "hf-sst2", "keras-imdb"],
        "required_tags": ["sentiment"],
        "forbidden_ids": [],
    },
    {
        "topic_signals": ["spam detection", "email spam", "sms spam"],
        "preferred_ids": ["hf-spam-detection"],
        "required_tags": ["spam"],
        "forbidden_ids": [],
    },
]


def _registry_lookup_aiml(topic: str, concepts: list[str], catalog: list[dict]) -> dict | None:
    """
    Check the AIML registry for a known topic signal match.
    Returns the best matching catalog entry, or None if no registry entry matches.
    Deliberately ignores difficulty — named datasets should always be returned
    regardless of the requested difficulty level.
    """
    topic_lower = topic.lower().strip()
    all_text = topic_lower + " " + " ".join(c.lower() for c in concepts)

    for entry in _AIML_REGISTRY:
        if not any(sig in all_text for sig in entry["topic_signals"]):
            continue

        required_tags = set(entry.get("required_tags", []))
        forbidden_ids = set(entry.get("forbidden_ids", []))
        preferred_ids = entry.get("preferred_ids", [])

        # Try preferred IDs first — exact match
        for pid in preferred_ids:
            for ds in catalog:
                ds_id = ds.get("id", "")
                if ds_id == pid and ds_id not in forbidden_ids:
                    logger.info(
                        "Registry exact match: '%s' (id=%s) for topic='%s'",
                        ds.get("name", ""), ds_id, topic,
                    )
                    return ds

        # Fall back to required_tags scan
        for ds in catalog:
            if ds.get("id", "") in forbidden_ids:
                continue
            ds_tags = {t.lower() for t in ds.get("tags", [])}
            if required_tags and required_tags.issubset(ds_tags):
                logger.info(
                    "Registry tag match: '%s' (required_tags=%s) for topic='%s'",
                    ds.get("name", ""), required_tags, topic,
                )
                return ds

        # Signal matched but no valid catalog entry — return None so caller
        # does NOT fall through to FAISS (which would return the wrong dataset)
        logger.warning(
            "Registry signal matched '%s' but no catalog entry satisfies "
            "required_tags=%s — will use synthetic",
            topic, required_tags,
        )
        return None  # explicit: synthetic > wrong dataset

    return None  # no registry entry matched — proceed to FAISS


def search(
    competency: str,
    topic: str,
    difficulty: str,
    concepts: list[str],
    top_k: int = 5,
) -> dict | None:
    """Search FAISS index for best matching entry."""

    # ── Step 0: Registry lookup (AIML only) ──────────────────────────────────
    if competency == "aiml":
        catalog = state.catalogs.get(competency, [])
        registry_match = _registry_lookup_aiml(topic, concepts, catalog)
        if registry_match is not None:
            return {
                "matched": registry_match,
                "score": 1.0,
                "method": "registry",
                "competency": competency,
            }
        # registry_match == None means either:
        #   a) no registry entry matched → fall through to FAISS (safe)
        #   b) registry entry matched but no valid catalog entry → _registry_lookup_aiml
        #      already logged a warning; we still fall through to FAISS here because
        #      the caller (generate_aiml_library) will use synthetic if FAISS also fails.

    if competency not in state.indexes:
        logger.warning("No index loaded for competency='%s'", competency)
        return _keyword_fallback(competency, topic, difficulty, concepts)

    query = f"{topic} {' '.join(concepts)} {difficulty}"

    try:
        vec = state.embed_model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        ).astype(np.float32)

        # Search larger pool to increase chance of finding difficulty + concept match
        search_k = min(top_k * 20, state.indexes[competency].ntotal)
        scores, indices = state.indexes[competency].search(vec, search_k)
        meta = state.metadata[competency]
        catalog = state.catalogs[competency]

        for idx, score in zip(indices[0], scores[0]):
            if idx < 0 or idx >= len(meta):
                continue

            # Skip low-confidence matches
            min_score = _MIN_SCORE_SQL if competency == "sql" else _MIN_SCORE_DSA if competency == "dsa" else _MIN_SCORE
            if float(score) < min_score:
                continue

            entry_meta = meta[idx]

            # Difficulty filter — skip if no difficulty in metadata (e.g. cloud)
            meta_diff = entry_meta.get("difficulty", "")
            if meta_diff:
                if isinstance(meta_diff, list):
                    meta_diff = meta_diff[0] if meta_diff else ""
                if meta_diff.lower() != difficulty.lower():
                    continue

            # Find full catalog entry (need it for concept filtering)
            stored_index = entry_meta.get("index", idx)
            entry_id = entry_meta.get("id", "")

            full_entry = None
            if entry_id:
                full_entry = next((e for e in catalog if e.get("id") == entry_id), None)
            if full_entry is None and stored_index < len(catalog):
                full_entry = catalog[stored_index]

            if not full_entry:
                continue

            # Concept filter (e.g. sql_category) — if concepts provided, at least one must match
            if concepts:
                entry_category = full_entry.get("sql_category", "").lower()
                entry_tags = [t.lower() for t in full_entry.get("tags", [])]
                entry_topics = [t.lower() for t in full_entry.get("topics", [])]
                concepts_lower = [c.lower() for c in concepts]
                
                # Check if any concept matches sql_category, tags, or topics
                if not any(
                    c == entry_category or c in entry_tags or c in entry_topics
                    for c in concepts_lower
                ):
                    continue

            # Return matched entry
            if full_entry:
                logger.info(
                    "FAISS match: '%s' score=%.3f competency='%s'",
                    full_entry.get("name") or full_entry.get("title") or full_entry.get("concept", ""),
                    float(score),
                    competency,
                )
                return {
                    "matched": full_entry,
                    "score": round(float(score), 4),
                    "method": "faiss",
                    "competency": competency,
                }

        logger.info("No FAISS match above threshold for '%s' difficulty='%s' — trying keyword", competency, difficulty)

    except Exception as e:
        logger.error("FAISS search failed for '%s': %s", competency, e)

    return _keyword_fallback(competency, topic, difficulty, concepts)


def _keyword_fallback(
    competency: str,
    topic: str,
    difficulty: str,
    concepts: list[str],
) -> dict | None:
    """Keyword-based fallback when FAISS is unavailable or returns no match."""
    catalog = state.catalogs.get(competency, [])
    if not catalog:
        return None

    keywords = [topic.lower()] + [c.lower() for c in concepts]
    difficulty_lower = difficulty.lower()

    for entry in catalog:
        # Handle difficulty as list or string — skip filter if entry has no difficulty
        entry_diff = entry.get("difficulty", "")
        if entry_diff:
            if isinstance(entry_diff, list):
                entry_diff = entry_diff[0] if entry_diff else ""
            if str(entry_diff).lower() != difficulty_lower:
                continue
        searchable = " ".join([
            entry.get("name", ""),
            entry.get("title", ""),
            entry.get("description", ""),
            entry.get("problem_description", ""),
            entry.get("context", ""),
            entry.get("concept", ""),
            entry.get("core_idea", ""),
            entry.get("service", ""),
            entry.get("sql_category", ""),
            " ".join(entry.get("tags", [])),
            " ".join(entry.get("topics", [])),
        ]).lower()

        # Concept filter: for SQL, concepts map directly to sql_category
        # Use it as a PREFERENCE not a hard filter — first pass with concept match,
        # second pass without if nothing found
        if concepts:
            concepts_lower = [c.lower() for c in concepts]
            entry_category = entry.get("sql_category", "").lower()
            entry_tags = [t.lower() for t in entry.get("tags", [])]
            entry_topics = [t.lower() for t in entry.get("topics", [])]
            concept_matched = any(
                c == entry_category or c in entry_tags or c in entry_topics
                for c in concepts_lower
            )
            # Also check if any topic word matches sql_category
            topic_words = [w for w in topic.lower().split() if len(w) > 3]
            topic_category_match = any(w == entry_category or w in entry_category for w in topic_words)
            if not concept_matched and not topic_category_match:
                continue

        if any(kw in searchable for kw in keywords):
            logger.info("Keyword match: '%s' competency='%s'", entry.get("name") or entry.get("title"), competency)
            return {
                "matched": entry,
                "score": 0.0,
                "method": "keyword",
                "competency": competency,
            }

        # Also match on individual words from the topic (e.g. "window functions" → "window")
        topic_words = [w for w in topic.lower().split() if len(w) > 3]
        if topic_words and any(w in searchable for w in topic_words):
            logger.info("Keyword word-match: '%s' competency='%s'", entry.get("name") or entry.get("title"), competency)
            return {
                "matched": entry,
                "score": 0.0,
                "method": "keyword",
                "competency": competency,
            }

    # Second pass — relax concept filter, just match on topic/category
    topic_words_all = [w for w in topic.lower().split() if len(w) > 3]
    for entry in catalog:
        entry_diff = entry.get("difficulty", "")
        if entry_diff:
            if isinstance(entry_diff, list):
                entry_diff = entry_diff[0] if entry_diff else ""
            if str(entry_diff).lower() != difficulty_lower:
                continue
        entry_category = entry.get("sql_category", "").lower()
        if concepts:
            concepts_lower = [c.lower() for c in concepts]
            if any(c == entry_category for c in concepts_lower):
                logger.info("Keyword category-match (pass2): '%s'", entry.get("title", ""))
                return {"matched": entry, "score": 0.0, "method": "keyword", "competency": competency}
        if topic_words_all and any(w == entry_category for w in topic_words_all):
            logger.info("Keyword topic-category-match (pass2): '%s'", entry.get("title", ""))
            return {"matched": entry, "score": 0.0, "method": "keyword", "competency": competency}

    return None
