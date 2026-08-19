from fastapi import Request
from fastapi.responses import JSONResponse

from core.logger import get_logger

logger = get_logger(__name__)


class UnsupportedDomainError(Exception):
    """Raised when no crawler is registered for the given URL's domain."""


class ExtractionError(Exception):
    """Raised when content extraction from a URL fails."""


class IndexingError(Exception):
    """Raised when indexing a document into Elasticsearch fails."""


async def unsupported_domain_handler(request: Request, exc: UnsupportedDomainError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "UNSUPPORTED_DOMAIN", "message": str(exc)},
    )


async def extraction_error_handler(request: Request, exc: ExtractionError) -> JSONResponse:
    logger.error(f"Extraction failed for {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "EXTRACTION_FAILED", "message": str(exc)},
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception for {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred."},
    )
