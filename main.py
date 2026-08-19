from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.dashboard_router import router as dashboard_router
from api.routers import router
from core.exceptions import (
    ExtractionError,
    UnsupportedDomainError,
    extraction_error_handler,
    generic_error_handler,
    unsupported_domain_handler,
)
from core.logger import get_logger
from db.elasticsearch_client import close_elasticsearch, init_elasticsearch
from db.elasticsearch_indexer import ElasticsearchIndexer

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Application startup")
    try:
        es = await init_elasticsearch()
        if es is not None:
            # Ensures the explicit INDEX_MAPPING (e.g. internalRefid as a
            # keyword UUID) is in place before any request can trigger an
            # auto-created index with ES's default dynamic mapping instead.
            await ElasticsearchIndexer(es).ensure_index()
    except Exception as exc:
        logger.error(f"Elasticsearch initialization failed: {exc}", exc_info=True)
    yield
    await close_elasticsearch()
    logger.info("Application shutdown")


app = FastAPI(
    title="ScrapeFlow",
    description=(
        "A content extraction and search platform built on FastAPI, Playwright, "
        "Crawl4AI, and Elasticsearch — crawling public scrape-practice sites."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_exception_handler(UnsupportedDomainError, unsupported_domain_handler)
app.add_exception_handler(ExtractionError, extraction_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

app.include_router(router)
app.include_router(dashboard_router)

# Mounted last: API routes registered above are matched first, this catches
# everything else and serves the static dashboard (index.html at "/").
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
