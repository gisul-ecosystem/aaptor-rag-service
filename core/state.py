from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Supported competencies — add new ones here as datasets are added
COMPETENCIES = ["aiml", "dsa", "devops", "data_engineering", "design", "prompt_engineering", "cloud", "fullstack", "sql", "mcq"]

# Loaded indexes per competency
indexes: dict[str, Any] = {}        # faiss index objects
metadata: dict[str, list] = {}      # list of metadata dicts
catalogs: dict[str, list] = {}      # raw catalog entries
embed_model = None                   # shared sentence transformer


def load_all_indexes() -> None:
    """Load all available FAISS indexes on startup."""
    from core.settings import get_settings
    from db import mongo
    s = get_settings()

    _load_embed_model()

    for competency in COMPETENCIES:
        faiss_path = s.faiss_path(competency)
        
        if not faiss_path.exists():
            logger.info("No FAISS index for '%s' — skipping", competency)
            continue

        try:
            import faiss
            indexes[competency] = faiss.read_index(str(faiss_path))
            
            # Load metadata from file (maps FAISS vector index → document ID)
            meta_path = s.metadata_path(competency)
            if meta_path.exists():
                with open(meta_path, encoding="utf-8") as f:
                    metadata[competency] = json.load(f)
            else:
                metadata[competency] = []
            
            # Load catalog from MongoDB (source of truth) — sort for stable ordering
            raw_catalog = mongo.load_all(competency)
            catalogs[competency] = sorted(raw_catalog, key=lambda e: str(e.get("_id", e.get("id", e.get("title", "")))))
            
            # Ensure indexes exist
            mongo.ensure_indexes(competency)
            
            logger.info(
                "Loaded '%s' index: %d vectors, %d catalog entries from MongoDB",
                competency,
                indexes[competency].ntotal,
                len(catalogs[competency]),
            )
        except Exception as e:
            logger.error("Failed to load '%s' index: %s", competency, e)


def reload_index(competency: str) -> None:
    """Hot-reload a single competency index after rebuild."""
    from core.settings import get_settings
    from db import mongo
    s = get_settings()

    try:
        import faiss
        indexes[competency] = faiss.read_index(str(s.faiss_path(competency)))
        with open(s.metadata_path(competency), encoding="utf-8") as f:
            metadata[competency] = json.load(f)
        # Always reload catalog from MongoDB — sort for stable ordering
        raw_catalog = mongo.load_all(competency)
        catalogs[competency] = sorted(raw_catalog, key=lambda e: str(e.get("_id", e.get("id", e.get("title", "")))))
        logger.info("Reloaded '%s' index: %d vectors, %d catalog entries", competency, indexes[competency].ntotal, len(catalogs[competency]))
    except Exception as e:
        logger.error("Failed to reload '%s' index: %s", competency, e)


def _load_embed_model() -> None:
    global embed_model
    if embed_model is not None:
        return
    from sentence_transformers import SentenceTransformer
    from core.settings import get_settings
    logger.info("Loading embedding model (CPU)...")
    # Always use CPU — RAG service is designed to run without GPU
    embed_model = SentenceTransformer(get_settings().embed_model_name, device="cpu")
    logger.info("Embedding model loaded.")


def get_stats() -> dict:
    return {
        competency: {
            "vectors": indexes[competency].ntotal if competency in indexes else 0,
            "catalog_entries": len(catalogs.get(competency, [])),
            "loaded": competency in indexes,
        }
        for competency in COMPETENCIES
    }
