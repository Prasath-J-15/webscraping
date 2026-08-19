import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from core.browser import PLAYWRIGHT_TIMEOUT_MS, render_page_in_thread
from core.exceptions import ExtractionError
from core.logger import get_logger
from db.elasticsearch_indexer import ElasticsearchIndexer
from dispatcher.crawler_dispatcher import extract_domain, resolve_crawler
from models.domain import RawJobData, ScrapedItem
from models.schemas import JobContentResponse
from services.scrape_service import ScrapeService
from services.text_cleaner import clean_markdown

logger = get_logger(__name__)

OnJobFn = Callable[[JobContentResponse], Awaitable[None]]


class ExtractionService:
    """Orchestrates domain-dispatched crawling, content cleaning, and optional indexing.

    This is the piece that answers "which crawler, does it need HTML handed
    to it, and what happens per item once we have one" — everything else
    (rendering, extraction, indexing) is delegated to a specialised module.
    """

    def __init__(
        self,
        indexer: Optional[ElasticsearchIndexer] = None,
        scrape_service: Optional[ScrapeService] = None,
    ) -> None:
        self.indexer = indexer
        self.scrape_service = scrape_service

    async def extract(self, url: str, on_job: Optional[OnJobFn] = None) -> list[JobContentResponse]:
        """Run the full extraction pipeline for the given URL.

        When `on_job` is provided, each JobContentResponse is delivered to it
        immediately after indexing instead of being accumulated — lets a
        caller (e.g. the batch runner) stream results to disk without holding
        the whole crawl in memory. Returns an empty list in that mode.

        Raises:
            ExtractionError: If navigation, extraction, and any configured
                fallback all fail.
        """
        logger.info(f"Incoming URL request: {url}")

        crawler = resolve_crawler(url)
        logger.info(f"Crawler selected: {type(crawler).__name__}")

        html_content: Optional[str] = None
        if crawler.requires_prerendered_html(url):
            try:
                logger.info(f"Extraction started: {url}")
                html_content = await asyncio.to_thread(render_page_in_thread, url, PLAYWRIGHT_TIMEOUT_MS)
            except Exception as exc:
                logger.error(f"Playwright navigation failed for {url}: {exc}", exc_info=True)
                return await self._fallback_scrape(url, None, on_job)
        else:
            logger.info(f"Extraction started: {url} (crawler performs its own rendering)")

        domain = extract_domain(url)
        results: list[JobContentResponse] = []
        jobs_delivered = 0

        async def on_raw_job(raw: RawJobData) -> None:
            """Index and deliver one item; called per-item by stream_extract."""
            nonlocal jobs_delivered
            jobs_delivered += 1
            item = ScrapedItem(
                source_refid=raw.source_refid,
                source_url=raw.source_url,
                domain=domain,
                extracted_content=clean_markdown(raw.extracted_content),
                internal_refid=str(uuid.uuid1()),
                created_at=raw.extracted_at,
                updated_at=raw.extracted_at,
            )
            indexed = False
            if self.indexer is not None:
                try:
                    # upsert() returns a fresh id only for a brand-new document;
                    # for a re-crawled (already-indexed) URL it returns None and
                    # this response keeps the placeholder id assigned above.
                    new_refid = await self.indexer.upsert(item)
                    if new_refid:
                        item.internal_refid = new_refid
                    indexed = True
                except Exception as exc:
                    logger.error(f"Indexing failed for {item.source_url}: {exc}", exc_info=True)

            response = JobContentResponse(
                internalRefid=item.internal_refid,
                sourceRefid=item.source_refid,
                sourceURL=item.source_url,
                domain=item.domain,
                extractedContent=item.extracted_content,
                createdAt=item.created_at,
                updatedAt=item.updated_at,
                indexed=indexed,
            )
            if on_job is not None:
                try:
                    await on_job(response)
                except Exception as exc:
                    logger.error(f"Job delivery callback failed for {item.source_url}: {exc}", exc_info=True)
            else:
                results.append(response)

        try:
            await crawler.stream_extract(url, html_content, on_raw_job=on_raw_job)
            html_content = None
            logger.info(f"Extraction completed: {jobs_delivered} item(s) found at {url}")
        except Exception as exc:
            logger.error(f"Crawler error for {url}: {exc}", exc_info=True)
            if jobs_delivered > 0:
                # Partial success — items already indexed; skip fallback so we
                # don't re-scrape the listing page as one generic document.
                logger.warning(f"Crawler failed after {jobs_delivered} item(s) — partial results retained, skipping fallback for {url}")
            else:
                return await self._fallback_scrape(url, html_content, on_job)

        return results

    async def _fallback_scrape(
        self,
        url: str,
        html_content: Optional[str],
        on_job: Optional[OnJobFn],
    ) -> list[JobContentResponse]:
        """Fall back to generic scraping when the domain crawler fails entirely.

        Reuses already-rendered HTML when available to avoid a second
        Playwright round-trip.

        Raises:
            ExtractionError: If no ScrapeService is configured, or the
                fallback scrape itself fails.
        """
        if self.scrape_service is None:
            raise ExtractionError(f"Crawler failed for {url} and no scrape_service fallback is configured")

        logger.warning(f"Crawler failed — falling back to generic scrape for {url}")
        try:
            if html_content is not None:
                scrape_resp = await self.scrape_service.scrape_html(url, html_content)
            else:
                scrape_resp = await self.scrape_service.scrape(url)
        except Exception as exc:
            raise ExtractionError(f"Fallback scrape also failed for {url}: {exc}") from exc

        response = JobContentResponse.model_validate(scrape_resp.model_dump())
        logger.info(f"Fallback scrape indexed and returned result for {url}")

        if on_job is not None:
            try:
                await on_job(response)
            except Exception as exc:
                logger.error(f"Job delivery callback failed for fallback scrape of {url}: {exc}", exc_info=True)
            return []
        return [response]
