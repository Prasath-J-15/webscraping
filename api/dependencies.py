from typing import Optional

from elasticsearch import AsyncElasticsearch
from fastapi import Depends

from db.elasticsearch_client import get_elasticsearch_client
from db.elasticsearch_indexer import ElasticsearchIndexer
from services.extraction_service import ExtractionService
from services.scrape_service import ScrapeService


def get_indexer(
    es: Optional[AsyncElasticsearch] = Depends(get_elasticsearch_client),
) -> Optional[ElasticsearchIndexer]:
    """FastAPI dependency providing an ElasticsearchIndexer, or None when ES isn't configured."""
    return ElasticsearchIndexer(es) if es is not None else None


def get_extraction_service(
    indexer: Optional[ElasticsearchIndexer] = Depends(get_indexer),
) -> ExtractionService:
    """FastAPI dependency providing an ExtractionService, indexer optional."""
    return ExtractionService(indexer=indexer, scrape_service=ScrapeService(indexer=indexer))


def get_scrape_service(
    indexer: Optional[ElasticsearchIndexer] = Depends(get_indexer),
) -> ScrapeService:
    """FastAPI dependency providing a ScrapeService, indexer optional."""
    return ScrapeService(indexer=indexer)
