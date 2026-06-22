from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from core import state
from core.settings import get_settings

logger = logging.getLogger(__name__)


async def rebuild_index(
    competency: str,
    use_gpu_model: bool = False,
    model_service_url: str = "",
) -> dict:
    """Rebuild FAISS index from catalog.json for a competency."""
    import faiss

    s = get_settings()
    catalog_path = s.catalog_path(competency)
    faiss_path = s.faiss_path(competency)
    meta_path = s.metadata_path(competency)
    faiss_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # Load from MongoDB (source of truth), fallback to JSON file
    from db import mongo
    catalog = mongo.load_all(competency)
    if not catalog:
        if not catalog_path.exists():
            logger.warning("No MongoDB or JSON catalog found for '%s'", competency)
            return {
                "competency": competency,
                "vectors": 0,
                "catalog_entries": 0,
                "time_seconds": round(time.time() - t0, 2),
            }
        logger.info("MongoDB empty for '%s' — loading from JSON file", competency)
        with open(catalog_path, encoding="utf-8") as f:
            catalog = json.load(f)
        # Sync JSON → MongoDB
        synced = mongo.sync_from_json(competency, catalog)
        logger.info("Synced %d entries from JSON to MongoDB for '%s'", synced, competency)

    logger.info("Rebuilding '%s' index from %d entries...", competency, len(catalog))

    # Sort catalog for stable ordering — ensures FAISS index positions are deterministic
    catalog = sorted(catalog, key=lambda e: str(e.get("_id", e.get("id", e.get("title", "")))))

    # Build text for each entry
    texts = []
    meta_entries = []
    for i, entry in enumerate(catalog):
        text = " ".join([
            entry.get("name", ""),
            entry.get("title", ""),
            entry.get("question", ""),         # MCQ
            entry.get("description", ""),
            entry.get("explanation", ""),      # MCQ
            entry.get("problem_description", ""),
            entry.get("context", ""),          # DevOps
            entry.get("use_case", ""),
            entry.get("concept", ""),          # Cloud
            entry.get("core_idea", ""),        # Cloud
            entry.get("service", ""),          # Cloud
            entry.get("action", ""),           # Cloud
            entry.get("sql_category", ""),     # SQL
            entry.get("source_complexity", ""), # SQL
            " ".join(entry.get("tags", [])),
            " ".join(entry.get("topics", [])),
            entry.get("domain", ""),
            entry.get("category", ""),         # MCQ
        ])
        texts.append(text)
        diff = entry.get("difficulty", "Medium")
        if isinstance(diff, list):
            diff = diff[0] if diff else "Medium"
        meta_entries.append({
            "id": entry.get("id", ""),   # empty for DSA — use index-based lookup
            "index": i,
            "difficulty": str(diff),
        })

    # Generate embeddings
    state._load_embed_model()
    embeddings = state.embed_model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype(np.float32)

    # Build FAISS index
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    # Write to temp files then swap atomically
    tmp_faiss = Path(str(faiss_path) + ".tmp")
    tmp_meta = Path(str(meta_path) + ".tmp")

    faiss.write_index(index, str(tmp_faiss))
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump(meta_entries, f, indent=2)

    tmp_faiss.replace(faiss_path)
    tmp_meta.replace(meta_path)

    # Hot-reload
    state.reload_index(competency)

    elapsed = round(time.time() - t0, 2)
    logger.info("Rebuilt '%s' index: %d vectors in %ss", competency, index.ntotal, elapsed)

    return {
        "competency": competency,
        "vectors": index.ntotal,
        "catalog_entries": len(catalog),
        "time_seconds": elapsed,
    }
