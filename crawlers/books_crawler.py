"""books.toscrape.com — the "hybrid" crawler pattern.

Phase 1 (in extract(), off the orchestrator's pre-rendered HTML — no browser
session of this crawler's own yet): parse the listing page's book cards for
each book's detail-page URL, capped by TEST_MODE like every other collection
point in this project.

Phase 2 (in stream_extract()): visit each book's detail page — batched,
browser-restarting, streamed via the same asyncio.Queue bridge as
QuotesAuthorsCrawler — and run each one through Crawl4AI, scoped to just the
"Product Description" paragraph via `css_selector`, since that paragraph is
the one piece of genuinely freeform prose on an otherwise fully structured
page. Structured fields (title, price, availability, rating) are still
parsed directly with BeautifulSoup; Crawl4AI is reserved for the prose it's
actually good at converting.

Contrast with QuotesAuthorsCrawler: there, the crawler owns *all* pagination
and rendering itself (`requires_prerendered_html() -> False`). Here, the
orchestrator hands over page one for free, and only the detail-page fan-out
needs the crawler's own browser session.
"""

import asyncio
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from core.config import settings
from core.exceptions import ExtractionError
from core.logger import get_logger
from crawlers.base_crawler import BaseCrawler, OnRawJobFn
from crawlers.click_through_base import run_pages_with_restart
from models.domain import RawJobData

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"/catalogue/([^/]+)/index\.html")
_DETAIL_READY_SELECTOR = "#product_description"

# Scoped to just the description paragraph that follows the "Product
# Description" heading — keeps page chrome and the product-info table out
# of the Markdown entirely, no PruningContentFilter heuristics needed.
_DESCRIPTION_RUN_CONFIG = CrawlerRunConfig(
    css_selector="#product_description ~ p",
    word_count_threshold=1,
    exclude_all_images=True,
    exclude_external_links=True,
    markdown_generator=DefaultMarkdownGenerator(options={"ignore_links": True, "ignore_images": True}),
)


class BooksCatalogCrawler(BaseCrawler):
    """Collects every book listed on a books.toscrape.com catalog page, plus each book's description."""

    def requires_prerendered_html(self, url: str) -> bool:
        return True

    @staticmethod
    def _collect_book_urls(listing_url: str, html_content: str) -> list[str]:
        """Parse the listing page for book detail-page URLs, capped by TEST_MODE."""
        soup = BeautifulSoup(html_content, "html.parser")
        cards = soup.select("article.product_pod")
        if not cards:
            raise ExtractionError(f"No book cards found on {listing_url} — page layout may have changed")

        urls: list[str] = []
        for card in cards:
            link = card.select_one("h3 a")
            if link is not None and link.get("href"):
                urls.append(urljoin(listing_url, link["href"]))

        if settings.test_mode:
            urls = urls[: settings.test_mode_job_limit]
        return urls

    @staticmethod
    def _parse_detail_fields(detail_url: str, html_content: str) -> dict:
        """Parse title/price/availability/rating directly from a book's detail page."""
        soup = BeautifulSoup(html_content, "html.parser")
        main = soup.select_one("div.product_main") or soup

        title_el = main.select_one("h1")
        title = title_el.text.strip() if title_el else "NA"

        price_el = main.select_one("p.price_color")
        price = price_el.text.strip() if price_el else "NA"

        availability_el = main.select_one("p.instock.availability")
        availability = " ".join(availability_el.text.split()) if availability_el else "NA"

        rating_el = main.select_one("p.star-rating")
        rating = "NA"
        if rating_el is not None:
            classes = rating_el.get("class", [])
            rating = next((c for c in classes if c != "star-rating"), "NA")

        slug_match = _SLUG_RE.search(detail_url)
        source_refid = slug_match.group(1) if slug_match else "NA"

        return {
            "source_refid": source_refid,
            "title": title,
            "price": price,
            "availability": availability,
            "rating": rating,
        }

    async def _extract_book(self, crawler: AsyncWebCrawler, detail_url: str, html_content: str) -> Optional[RawJobData]:
        """Combine BeautifulSoup-parsed fields with a Crawl4AI-converted description into one RawJobData."""
        fields = self._parse_detail_fields(detail_url, html_content)

        description = "NA"
        try:
            result = await crawler.arun(url=f"raw:{html_content}", config=_DESCRIPTION_RUN_CONFIG)
            if result.success:
                description = str(result.markdown).strip() or "NA"
            else:
                logger.warning(f"Crawl4AI conversion unsuccessful for {detail_url}: {result.error_message}")
        except Exception as exc:
            logger.warning(f"Crawl4AI conversion failed for {detail_url}: {exc}")

        extracted_content = (
            f"{fields['title']}\n"
            f"Price: {fields['price']}\n"
            f"Availability: {fields['availability']}\n"
            f"Rating: {fields['rating']} out of Five\n\n"
            f"{description}"
        )
        return RawJobData(
            source_refid=fields["source_refid"],
            source_url=detail_url,
            extracted_content=extracted_content,
        )

    async def extract(self, url: str, html_content: Optional[str] = None) -> list[RawJobData]:
        """Non-streaming entry point — collects every book before returning.

        Kept for BaseCrawler compliance and simple callers (e.g. unit tests);
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
        """Queue-bridge streaming for Phase 2 — see QuotesAuthorsCrawler for the same pattern."""
        if not html_content:
            raise ExtractionError(f"No HTML provided for {url}")

        book_urls = self._collect_book_urls(url, html_content)
        logger.info(f"Phase 1 complete: {len(book_urls)} book(s) found on {url}")

        loop = asyncio.get_running_loop()
        result_queue: asyncio.Queue[Optional[RawJobData]] = asyncio.Queue()
        all_raw_jobs: list[RawJobData] = []
        jobs_delivered = 0

        async def process_chunk(pages: list[tuple[str, str]]) -> list:
            async with AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy()) as crawler:
                for detail_url, detail_html in pages:
                    raw = await self._extract_book(crawler, detail_url, detail_html)
                    if raw:
                        loop.call_soon_threadsafe(result_queue.put_nowait, raw)
            return []  # never accumulate on the thread side — process_chunk streams instead

        async def _crawl() -> None:
            try:
                await asyncio.to_thread(
                    run_pages_with_restart,
                    book_urls,
                    ready_selector=_DETAIL_READY_SELECTOR,
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
            raise ExtractionError(f"No books extracted from {url}")

        logger.info(f"Phase 2 complete: {jobs_delivered} book(s) delivered")
        return all_raw_jobs
