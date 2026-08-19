from typing import Optional

from elasticsearch import AsyncElasticsearch

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

_client: Optional[AsyncElasticsearch] = None


def _make_client() -> AsyncElasticsearch:
    return AsyncElasticsearch(
        hosts=[settings.elasticsearch_host],
        basic_auth=(settings.elasticsearch_username, settings.elasticsearch_password),
        verify_certs=False,
        ssl_show_warn=False,
        retry_on_timeout=True,
        max_retries=3,
        connections_per_node=5,
        http_compress=False,
    )


async def init_elasticsearch() -> Optional[AsyncElasticsearch]:
    """Initialize the shared Elasticsearch client and verify connectivity.

    Returns None (rather than raising) when ELASTICSEARCH_HOST isn't
    configured — this demo is fully usable without a running ES cluster;
    ExtractionService/ScrapeService just run with indexer=None.
    """
    global _client
    if not settings.elasticsearch_host:
        logger.info("ELASTICSEARCH_HOST not set — running without an indexer")
        return None

    _client = _make_client()
    try:
        if await _client.ping():
            logger.info("Elasticsearch client initialized and connected")
        else:
            logger.warning("Elasticsearch client initialized but ping returned False — check host/credentials")
    except Exception as exc:
        logger.warning(f"Elasticsearch ping failed at startup: {exc} — indexing will be skipped until ES is reachable")
    return _client


async def close_elasticsearch() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        logger.info("Elasticsearch client closed")


async def reconnect_elasticsearch() -> AsyncElasticsearch:
    """Replace the current client with a fresh connection (used after a dropped connection)."""
    global _client
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            pass
    _client = _make_client()
    logger.info("Elasticsearch client reconnected")
    return _client


def get_elasticsearch_client() -> Optional[AsyncElasticsearch]:
    """Return the active client, or None if ES was never configured."""
    return _client
