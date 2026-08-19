from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

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

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Application startup")
    try:
        await init_elasticsearch()
    except Exception as exc:
        logger.error(f"Elasticsearch initialization failed: {exc}", exc_info=True)
    yield
    await close_elasticsearch()
    logger.info("Application shutdown")


app = FastAPI(
    title="Web Scraping Learning Project",
    description=(
        "Portfolio demo of a FastAPI + Playwright + Crawl4AI + Elasticsearch "
        "scraping pipeline, crawling public scrape-practice sites."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_exception_handler(UnsupportedDomainError, unsupported_domain_handler)
app.add_exception_handler(ExtractionError, extraction_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

app.include_router(router)
