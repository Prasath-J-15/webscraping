from fastapi import APIRouter, Depends

from api.dependencies import get_extraction_service, get_scrape_service
from core.config import settings
from core.logger import get_logger
from db.elasticsearch_client import get_elasticsearch_client
from models.schemas import ExtractRequest, HealthResponse, JobContentResponse, ScrapeRequest, ScrapeResponse
from services.extraction_service import ExtractionService
from services.scrape_service import ScrapeService

logger = get_logger(__name__)
router = APIRouter()


@router.post("/extract", response_model=list[JobContentResponse])
async def extract_job(
    request: ExtractRequest,
    service: ExtractionService = Depends(get_extraction_service),
) -> list[JobContentResponse]:
    """Dispatch to the registered crawler for the URL's domain and return one record per item found.

    Only books.toscrape.com and quotes.toscrape.com are registered in this
    demo — see dispatcher/crawler_dispatcher.py:DOMAIN_REGISTRY.
    """
    return await service.extract(str(request.url))


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_url(
    request: ScrapeRequest,
    service: ScrapeService = Depends(get_scrape_service),
) -> ScrapeResponse:
    """Render any URL and return its content as cleaned Markdown — no domain dispatch."""
    return await service.scrape(str(request.url))


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Report application health and Elasticsearch connectivity."""
    es_status = "disconnected"
    try:
        es = get_elasticsearch_client()
        if es is not None and await es.ping():
            es_status = "connected"
    except Exception:
        pass

    return HealthResponse(status="ok", elasticsearch=es_status, environment=settings.environment)
