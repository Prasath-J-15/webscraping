from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

from core.logger import get_logger
from models.domain import RawJobData

logger = get_logger(__name__)

OnRawJobFn = Callable[[RawJobData], Awaitable[None]]


class BaseCrawler(ABC):
    """Abstract base class defining the crawler interface every site plugs into."""

    def requires_prerendered_html(self, url: str) -> bool:
        """Whether extract() needs HTML pre-rendered by the orchestrator for this URL.

        Crawlers that manage their own Playwright session (click-through flows
        that must visit many detail pages, or navigate through pagination)
        return False here so ExtractionService skips a redundant render.
        """
        return True

    @abstractmethod
    async def extract(self, url: str, html_content: Optional[str] = None) -> list[RawJobData]:
        """Extract items from the given URL.

        Args:
            url: The target URL (listing page or individual item page).
            html_content: Pre-rendered HTML from Playwright, when applicable.

        Returns:
            A list of RawJobData — one entry per item found.
        """
        ...

    async def stream_extract(
        self,
        url: str,
        html_content: Optional[str] = None,
        on_raw_job: Optional[OnRawJobFn] = None,
    ) -> list[RawJobData]:
        """Extract items and deliver each via on_raw_job as soon as it's ready.

        The default implementation just calls extract() and dispatches the
        results sequentially afterwards. Crawlers that can genuinely stream
        (paginated click-through crawlers) override this so downstream
        indexing isn't blocked on the entire crawl finishing first — see
        QuotesAuthorsCrawler and crawlers/click_through_base.py.
        """
        raw_jobs = await self.extract(url, html_content)
        if on_raw_job is not None:
            for raw in raw_jobs:
                try:
                    await on_raw_job(raw)
                except Exception as exc:
                    logger.error(f"Delivery callback failed for {raw.source_url}: {exc}", exc_info=True)
        return raw_jobs
