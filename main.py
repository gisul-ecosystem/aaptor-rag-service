from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings import get_settings
from core import state
from api.routes import retrieve, retrieve_bulk, rebuild, ingest, health, catalog, schema_import

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if not s.admin_api_key:
        logger.warning(
            "SECURITY WARNING: ADMIN_API_KEY is not set. "
            "Rebuild, ingest, and delete endpoints are UNPROTECTED."
        )
    logger.info("Loading RAG indexes...")
    state.load_all_indexes()
    logger.info("RAG service ready.")
    yield
    logger.info("RAG service shutting down.")


app = FastAPI(
    title="Aaptor RAG Service",
    description="FAISS-based semantic retrieval for DSA, AIML, and other competency datasets.",
    version="1.0.0",
    lifespan=lifespan,
)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(retrieve.router)
app.include_router(retrieve_bulk.router)
app.include_router(rebuild.router)
app.include_router(ingest.router)
app.include_router(catalog.router)
app.include_router(schema_import.router)
