from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RawJobData:
    """Raw content for a single scraped item, as returned by a crawler.

    Named after the field it plays in the pipeline (mirrors a job-board
    "job") rather than renamed per demo site — extraction_service.py builds
    an ScrapedItem from this regardless of what's actually being scraped
    (a book, a quote, an author bio, ...).
    """

    source_refid: str  # Source system's item ID; "NA" if unavailable
    source_url: str
    extracted_content: str
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ScrapedItem:
    """Fully-processed item, ready for the API response and Elasticsearch."""

    source_refid: str
    source_url: str
    domain: str
    extracted_content: str
    internal_refid: str = ""  # time-ordered UUID (uuid1); assigned by the caller before indexing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
