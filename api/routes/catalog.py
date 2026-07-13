from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

from core.settings import get_settings
from core import state
from db import mongo

router = APIRouter(tags=["catalog"])


@router.get("/api/v1/catalog/{competency}")
async def list_catalog(
    competency: str,
    search: str = Query(default="", description="Search by name/title/description"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    """List all catalog entries for a competency."""
    catalog = state.catalogs.get(competency, [])
    if not catalog:
        # Try loading from MongoDB
        catalog = mongo.load_all(competency)

    if search:
        s = search.lower()
        catalog = [
            e for e in catalog
            if s in str(e.get("name", "")).lower()
            or s in str(e.get("title", "")).lower()
            or s in str(e.get("question", "")).lower()
            or s in str(e.get("description", "")).lower()
            or s in str(e.get("problem_description", "")).lower()
            or s in str(e.get("category", "")).lower()
            or s in str(e.get("quiz_title", "")).lower()
            or any(s in str(t).lower() for t in e.get("tags", []))
        ]

    total = len(catalog)
    page = catalog[offset: offset + limit]

    return {
        "competency": competency,
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": page,
    }


@router.get("/api/v1/catalog/{competency}/{entry_id}")
async def get_catalog_entry(competency: str, entry_id: str):
    """Get a single catalog entry by ID."""
    entry = mongo.get_by_id(competency, entry_id)
    if not entry:
        # Try in-memory catalog
        catalog = state.catalogs.get(competency, [])
        entry = next(
            (e for e in catalog if e.get("id") == entry_id or e.get("title", "").lower().replace(" ", "-") == entry_id),
            None
        )
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found in '{competency}'")
    return entry


@router.delete("/api/v1/catalog/{competency}/{entry_id}")
async def delete_catalog_entry(
    competency: str,
    entry_id: str,
    x_api_key: str | None = Header(default=None),
):
    """Delete a catalog entry by ID."""
    s = get_settings()
    if s.admin_api_key and x_api_key != s.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin API key")

    col = mongo._collection(competency)
    result = col.delete_one({"_id": entry_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found")

    # Reload in-memory catalog
    state.catalogs[competency] = mongo.load_all(competency)
    return {"deleted": entry_id, "competency": competency}
