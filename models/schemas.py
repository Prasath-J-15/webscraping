from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator


class _UrlRequest(BaseModel):
    """Base request payload accepting a single target URL."""

    url: HttpUrl

    @field_validator("url", mode="before")
    @classmethod
    def add_default_scheme(cls, value: str) -> str:
        """Prepend "https://" to bare domains/paths (e.g. "books.toscrape.com")."""
        if isinstance(value, str) and not value.startswith(("http://", "https://")):
            return f"https://{value}"
        return value


class ExtractRequest(_UrlRequest):
    """Incoming request payload for the /extract endpoint."""


class ScrapeRequest(_UrlRequest):
    """Incoming request payload for the /scrape endpoint."""


class _ExtractedContentResponse(BaseModel):
    """Base response payload for a single piece of extracted content."""

    internal_refid: int = Field(..., alias="internalRefid")
    source_refid: str = Field(..., alias="sourceRefid")
    source_url: str = Field(..., alias="sourceURL")
    domain: str = Field(..., alias="domain")
    extracted_content: str = Field(..., alias="extractedContent")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")
    indexed: bool = False

    model_config = {"populate_by_name": True}


class JobContentResponse(_ExtractedContentResponse):
    """API response for a single item returned by /extract."""


class ScrapeResponse(_ExtractedContentResponse):
    """API response for the /scrape endpoint."""


class HealthResponse(BaseModel):
    """Response for the /health endpoint."""

    status: str
    elasticsearch: str
    environment: str
