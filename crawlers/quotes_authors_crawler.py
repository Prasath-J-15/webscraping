"""quotes.toscrape.com — the "click-through" crawler pattern.

Two phases:
  1. Walk pagination on the quote-listing pages (`/page/N/`) collecting the
     unique set of author bio-page URLs referenced by the "(about)" links.
  2. Visit each author page individually, restarting the browser every
     `settings.browser_restart_after_pages` pages, and stream each parsed
     bio out through an asyncio.Queue as soon as it's ready instead of
     buffering the whole crawl in memory.

This crawler owns its Playwright session end-to-end (both phases), so
`requires_prerendered_html()` returns False — ExtractionService must not
also pre-render the URL before calling in.
"""

import asyncio
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from playwright.async_api import async_playwright

from core.config import settings
from core.exceptions import ExtractionError
from core.logger import get_logger
from crawlers.base_crawler import BaseCrawler, OnRawJobFn
from crawlers.click_through_base import run_pages_with_restart
from crawlers.pagination import collect_paginated_urls
from models.domain import RawJobData

logger = get_logger(__name__)

_AUTHOR_READY_SELECTOR = ".author-details"

# A per-crawler CrawlerRunConfig, deliberately lighter than ScrapeService's —
# this crawler already knows the DOM (it only ever sees author pages), so it
# doesn't need PruningContentFilter's generic noise-detection heuristics.
_BIO_RUN_CONFIG = CrawlerRunConfig(
    excluded_tags=["nav", "header", "footer", "script", "style"],
    word_count_threshold=5,
    exclude_all_images=True,
    exclude_external_links=True,
    markdown_generator=DefaultMarkdownGenerator(options={"ignore_links": True, "ignore_images": True}),
)


class QuotesAuthorsCrawler(BaseCrawler):
    """Collects every unique quote author on quotes.toscrape.com and their bio."""

    def requires_prerendered_html(self, url: str) -> bool:
        return False

    def _collect_author_urls_in_thread(self, listing_url: str) -> list[str]:
        """Phase 1: walk quote-listing pagination, return unique author bio URLs.

        Runs its own lightweight Playwright session — listing pages are small
        and few, so there's no need for the batching/restart machinery Phase 2
        uses for the (potentially much larger) set of detail pages.
        """
        limit = settings.test_mode_job_limit if settings.test_mode else None

        async def _run() -> list[str]:
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.launch(
                        headless=settings.playwright_headless,
                        channel=settings.playwright_channel or None,
                    )
                except Exception as exc:
                    raise ExtractionError(f"Failed to launch browser for {listing_url}: {exc}") from exc

                try:
                    page = await browser.new_page()
                    page.set_default_timeout(settings.playwright_timeout_ms)
                    return await collect_paginated_urls(
                        page,
                        start_url=listing_url,
                        item_link_selector="div.quote span a[href^='/author/']",
                        next_link_selector="li.next a",
                        timeout_ms=settings.playwright_timeout_ms,
                        wait_ms=settings.playwright_render_wait_ms,
                        limit=limit,
                    )
                finally:
                    await browser.close()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Author URL collection failed for {listing_url}: {exc}") from exc
        finally:
            loop.close()

    @staticmethod
    def _parse_author_fields(author_url: str, html_content: str) -> tuple[str, str, str, str]:
        """Return (source_refid, name, born_date, born_location) parsed directly from the DOM."""
        soup = BeautifulSoup(html_content, "html.parser")
        name_el = soup.select_one(".author-title")
        born_date_el = soup.select_one(".author-born-date")
        born_location_el = soup.select_one(".author-born-location")

        name = name_el.text.strip() if name_el else "NA"
        born_date = born_date_el.text.strip() if born_date_el else "NA"
        born_location = born_location_el.text.strip() if born_location_el else "NA"
        source_refid = author_url.rstrip("/").rsplit("/", 1)[-1] or "NA"

        return source_refid, name, born_date, born_location

    async def _extract_author(self, crawler: AsyncWebCrawler, author_url: str, html_content: str) -> Optional[RawJobData]:
        """Convert one author detail page into a RawJobData via Crawl4AI markdown conversion."""
        source_refid, name, born_date, born_location = self._parse_author_fields(author_url, html_content)

        try:
            result = await crawler.arun(url=f"raw:{html_content}", config=_BIO_RUN_CONFIG)
        except Exception as exc:
            logger.warning(f"Crawl4AI conversion failed for {author_url}: {exc}")
            return None

        if not result.success:
            logger.warning(f"Crawl4AI conversion unsuccessful for {author_url}: {result.error_message}")
            return None

        bio_markdown = str(result.markdown).strip()
        if not bio_markdown:
            logger.warning(f"No bio content extracted for {author_url}")
            return None

        extracted_content = f"{name}\nBorn: {born_date} {born_location}\n\n{bio_markdown}"

        return RawJobData(
            source_refid=source_refid,
            source_url=author_url,
            extracted_content=extracted_content,
        )

    async def extract(self, url: str, html_content: Optional[str] = None) -> list[RawJobData]:
        """Non-streaming entry point — collects every job before returning.

        Kept for BaseCrawler compliance and for callers that don't need
        streaming (e.g. a unit test asserting on the full result list).
        stream_extract() below is what ExtractionService actually calls.
        """
        jobs: list[RawJobData] = []

        async def _collect(raw: RawJobData) -> None:
            jobs.append(raw)

        await self.stream_extract(url, html_content, on_raw_job=_collect)
        return jobs

    async def stream_extract(
        self,
        url: str,
        html_content: Optional[str] = None,
        on_raw_job: Optional[OnRawJobFn] = None,
    ) -> list[RawJobData]:
        """Queue-bridge streaming: deliver each author bio as soon as it's parsed.

        See CLAUDE.md's "Streaming pattern (all click-through crawlers)" for
        the shape this follows: a producer coroutine drives the thread-side
        crawl and pushes results onto an asyncio.Queue via
        `loop.call_soon_threadsafe`; a consumer coroutine drains the queue and
        forwards each item to `on_raw_job`. `jobs_delivered` (not
        `len(all_raw_jobs)`) is the authoritative "did we find anything" check,
        since `all_raw_jobs` stays empty in streaming mode.
        """
        loop = asyncio.get_running_loop()
        result_queue: asyncio.Queue[Optional[RawJobData]] = asyncio.Queue()
        all_raw_jobs: list[RawJobData] = []
        jobs_delivered = 0

        async def process_chunk(pages: list[tuple[str, str]]) -> list:
            async with AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy()) as crawler:
                for author_url, author_html in pages:
                    raw = await self._extract_author(crawler, author_url, author_html)
                    if raw:
                        loop.call_soon_threadsafe(result_queue.put_nowait, raw)
            return []  # never accumulate on the thread side — process_chunk streams instead

        async def _crawl() -> None:
            try:
                author_urls = await asyncio.to_thread(self._collect_author_urls_in_thread, url)
                logger.info(f"Phase 1 complete: {len(author_urls)} unique author(s) found")
                await asyncio.to_thread(
                    run_pages_with_restart,
                    author_urls,
                    ready_selector=_AUTHOR_READY_SELECTOR,
                    process_chunk=process_chunk,
                )
            finally:
                loop.call_soon_threadsafe(result_queue.put_nowait, None)  # sentinel

        async def _consume() -> None:
            nonlocal jobs_delivered
            while True:
                raw = await result_queue.get()
                if raw is None:
                    break
                jobs_delivered += 1
                if on_raw_job is not None:
                    await on_raw_job(raw)
                else:
                    all_raw_jobs.append(raw)

        await asyncio.gather(_crawl(), _consume())

        if jobs_delivered == 0:
            raise ExtractionError(f"No authors extracted from {url}")

        logger.info(f"Phase 2 complete: {jobs_delivered} author bio(s) delivered")
        return all_raw_jobs
