from __future__ import annotations

import logging
import random
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import state
from core.state import COMPETENCIES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieve-bulk"])


class BulkRetrieveRequest(BaseModel):
    competency: str
    topic: str
    difficulty: str = "Medium"
    concepts: list[str] = []
    count: int = 5  # number of different problems to return


@router.post("/api/v1/retrieve/bulk")
async def retrieve_bulk(req: BulkRetrieveRequest):
    """
    Return N different matching problems for bulk question generation.
    Uses FAISS to find top candidates, then returns `count` unique ones.
    Falls back to random sampling from catalog if FAISS doesn't have enough.
    """
    if req.competency not in COMPETENCIES:
        raise HTTPException(status_code=400, detail=f"Unknown competency: {req.competency}")

    count = max(1, min(req.count, 50))
    results = _bulk_search(req.competency, req.topic, req.difficulty, req.concepts, count)

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No matches found for competency='{req.competency}' topic='{req.topic}' difficulty='{req.difficulty}'"
        )

    return {
        "competency": req.competency,
        "count": len(results),
        "matches": results,
    }


def _bulk_search(
    competency: str,
    topic: str,
    difficulty: str,
    concepts: list[str],
    count: int,
) -> list[dict]:
    """Return up to `count` unique matching problems."""
    catalog = state.catalogs.get(competency, [])
    if not catalog:
        return []

    difficulty_lower = difficulty.lower()
    results = []
    seen_titles = set()
    seen_indexes = set()

    # Try FAISS first
    if competency in state.indexes:
        try:
            query = f"{topic} {' '.join(concepts)} {difficulty}"
            vec = state.embed_model.encode(
                [query], convert_to_numpy=True, normalize_embeddings=True
            ).astype(np.float32)

            # Search large pool — use count*50 to have plenty after difficulty + concept filtering
            search_k = min(count * 50, state.indexes[competency].ntotal)
            scores, indices = state.indexes[competency].search(vec, search_k)
            meta = state.metadata[competency]

            for idx, score in zip(indices[0], scores[0]):
                if len(results) >= count:
                    break
                if idx < 0 or idx >= len(meta):
                    continue
                if float(score) < 0.1:
                    continue

                entry_meta = meta[idx]
                meta_diff = entry_meta.get("difficulty", "")
                if meta_diff:
                    if isinstance(meta_diff, list):
                        meta_diff = meta_diff[0] if meta_diff else ""
                    if meta_diff.lower() != difficulty_lower:
                        continue

                # Get full entry
                stored_index = entry_meta.get("index", idx)
                entry_id = entry_meta.get("id", "")
                full_entry = None
                if entry_id:
                    full_entry = next((e for e in catalog if e.get("id") == entry_id), None)
                if full_entry is None and stored_index < len(catalog):
                    full_entry = catalog[stored_index]

                if full_entry:
                    title = full_entry.get("title", full_entry.get("name", ""))

                    # Concept filter — if concepts provided, at least one must match sql_category/tags/topics
                    if concepts:
                        concepts_lower = [c.lower() for c in concepts]
                        entry_category = full_entry.get("sql_category", "").lower()
                        entry_tags = [t.lower() for t in full_entry.get("tags", [])]
                        entry_topics = [t.lower() for t in full_entry.get("topics", [])]
                        # Abbreviation map for common DSA concepts
                        abbrev_map = {
                            "bfs": "breadth", "dfs": "depth", "dp": "dynamic",
                            "bs": "binary search", "ll": "linked list"
                        }
                        expanded = [abbrev_map.get(c, c) for c in concepts_lower]
                        if not any(
                            c == entry_category or
                            any(c in tag or tag in c or e in tag for tag in entry_tags for e in [expanded[i]] for i, orig in enumerate(concepts_lower) if orig == c) or
                            any(c in tag or tag in c for tag in entry_tags) or
                            any(c in topic or topic in c for topic in entry_topics) or
                            any(e in tag for tag in entry_tags for e in expanded)
                            for c in concepts_lower
                        ):
                            continue

                    # Deduplicate by both title AND catalog position to handle index mismatches
                    if title not in seen_titles and stored_index not in seen_indexes:
                        seen_titles.add(title)
                        seen_indexes.add(stored_index)
                        results.append({
                            "matched": full_entry,
                            "score": round(float(score), 4),
                            "method": "faiss",
                        })
        except Exception as e:
            logger.error("FAISS bulk search error: %s", e)  # fall through to random sampling

    # If not enough from FAISS, fill with random samples from catalog
    if len(results) < count:
        concepts_lower = [c.lower() for c in concepts]
        diff_candidates = []
        for i, e in enumerate(catalog):
            if str(e.get("difficulty", "")).lower() != difficulty_lower:
                continue
            if e.get("title", e.get("name", "")) in seen_titles or i in seen_indexes:
                continue
            # Concept filter
            if concepts_lower:
                entry_category = e.get("sql_category", "").lower()
                entry_tags = [t.lower() for t in e.get("tags", [])]
                entry_topics = [t.lower() for t in e.get("topics", [])]
                # Abbreviation map for common DSA concepts
                abbrev_map = {
                    "bfs": "breadth", "dfs": "depth", "dp": "dynamic",
                    "bs": "binary search", "ll": "linked list"
                }
                expanded = [abbrev_map.get(c, c) for c in concepts_lower]
                if not any(
                    c == entry_category or
                    any(c in tag or tag in c for tag in entry_tags) or
                    any(c in topic or topic in c for topic in entry_topics) or
                    any(exp in tag for tag in entry_tags for exp in expanded)
                    for c in concepts_lower
                ):
                    continue
            diff_candidates.append((i, e))
        logger.info("Random fallback: %d candidates for difficulty='%s' in %d catalog entries", len(diff_candidates), difficulty_lower, len(catalog))
        random.shuffle(diff_candidates)
        for i, entry in diff_candidates:
            if len(results) >= count:
                break
            title = entry.get("title", entry.get("name", ""))
            if title not in seen_titles and i not in seen_indexes:
                seen_titles.add(title)
                seen_indexes.add(i)
                results.append({
                    "matched": entry,
                    "score": 0.0,
                    "method": "random_sample",
                })

    return results
