import asyncio
from datetime import datetime, timezone
from typing import Optional

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from core.browser import PLAYWRIGHT_TIMEOUT_MS, render_page_in_thread
from core.exceptions import ExtractionError
from core.logger import get_logger
from db.elasticsearch_indexer import ElasticsearchIndexer
from dispatcher.crawler_dispatcher import extract_domain
from models.domain import ScrapedItem
from models.schemas import ScrapeResponse
from services.text_cleaner import clean_markdown

logger = get_logger(__name__)

# Tags stripped before conversion — chrome/boilerplate, never page content.
_NOISE_TAGS = ["nav", "footer", "header", "script", "style", "noscript", "svg"]

# Common chrome/boilerplate wrapper names, matched against any element's
# class/id regardless of the target site's markup, and removed before
# Markdown conversion.
_NOISE_CLASS_ID_PATTERNS = [
    "nav", "header", "footer", "sidebar", "breadcrumb",
    "cookie", "consent", "popup", "modal", "overlay", "banner",
    "advert", "sponsor", "promo",
    "social", "share",
    "related", "similar", "recommend", "suggestion", "trending",
    "menu", "toolbar", "language",
]
_NOISE_SELECTOR = ", ".join(f'[class*="{pattern}"], [id*="{pattern}"]' for pattern in _NOISE_CLASS_ID_PATTERNS)

# Because this endpoint accepts *any* URL (no crawler knows its DOM ahead of
# time), it leans on PruningContentFilter to statistically find the "main
# content" block rather than a hand-written selector.
_MARKDOWN_RUN_CONFIG = CrawlerRunConfig(
    excluded_tags=_NOISE_TAGS,
    excluded_selector=_NOISE_SELECTOR,
    word_count_threshold=5,
    exclude_all_images=True,
    exclude_external_links=True,
    exclude_social_media_links=True,
    remove_overlay_elements=True,
    remove_consent_popups=True,
    markdown_generator=DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.5, threshold_type="dynamic"),
        options={"ignore_links": True, "ignore_images": True},
    ),
)


class ScrapeService:
    """Renders any URL with Playwright and converts it to Markdown via Crawl4AI.

    Unlike ExtractionService, this performs no domain dispatch — every URL is
    rendered and converted the same generic way. Also used as
    ExtractionService's fallback when a domain crawler errors out.
    """

    def __init__(self, indexer: Optional[ElasticsearchIndexer] = None) -> None:
        self.indexer = indexer

    async def scrape_html(self, url: str, html_content: str) -> ScrapeResponse:
        """Convert already-rendered HTML to Markdown, skipping a redundant render."""
        logger.info(f"Converting pre-rendered HTML to Markdown for: {url}")
        markdown_content = await self._convert_to_markdown(url, html_content)
        return await self._finish(url, markdown_content)

    async def scrape(self, url: str) -> ScrapeResponse:
        """Render, extract, clean, and optionally index the content at a URL."""
        logger.info(f"Incoming scrape request: {url}")
        html_content = await self._render_page(url)
        markdown_content = await self._convert_to_markdown(url, html_content)
        response = await self._finish(url, markdown_content)
        logger.info(f"Scrape completed: {url}")
        return response

    async def _finish(self, url: str, markdown_content: str) -> ScrapeResponse:
        cleaned_content = clean_markdown(markdown_content)
        now = datetime.now(timezone.utc)
        scraped = ScrapedItem(
            source_refid="NA",
            source_url=url,
            domain=extract_domain(url),
            extracted_content=cleaned_content,
            created_at=now,
            updated_at=now,
        )
        is_indexed = await self._index_content(scraped)

        return ScrapeResponse(
            internalRefid=scraped.internal_refid,
            sourceRefid=scraped.source_refid,
            sourceURL=scraped.source_url,
            domain=scraped.domain,
            extractedContent=scraped.extracted_content,
            createdAt=scraped.created_at,
            updatedAt=scraped.updated_at,
            indexed=is_indexed,
        )

    async def _render_page(self, url: str) -> str:
        try:
            logger.info(f"Rendering page with Playwright: {url}")
            return await asyncio.to_thread(render_page_in_thread, url, PLAYWRIGHT_TIMEOUT_MS)
        except Exception as exc:
            logger.error(f"Playwright navigation failed for {url}: {exc}", exc_info=True)
            raise ExtractionError(f"Failed to render page at {url}: {exc}") from exc

    async def _convert_to_markdown(self, url: str, html_content: str) -> str:
        """Convert rendered HTML to Markdown via Crawl4AI.

        Uses AsyncHTTPCrawlerStrategy with a "raw:" pseudo-URL so Crawl4AI
        converts HTML we already have instead of launching a second browser
        of its own.
        """
        try:
            async with AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy()) as crawler:
                result = await crawler.arun(url=f"raw:{html_content}", config=_MARKDOWN_RUN_CONFIG)
        except Exception as exc:
            logger.error(f"Crawl4AI extraction failed for {url}: {exc}", exc_info=True)
            raise ExtractionError(f"Failed to extract content from {url}: {exc}") from exc

        if not result.success:
            logger.error(f"Crawl4AI extraction failed for {url}: {result.error_message}")
            raise ExtractionError(f"Crawl4AI extraction failed for {url}: {result.error_message}")

        # fit_markdown is the PruningContentFilter output — falls back to raw
        # markdown if pruning happens to strip everything on a sparse page.
        fit_markdown = (result.markdown.fit_markdown or "").strip()
        raw_markdown = str(result.markdown).strip()
        content = fit_markdown or raw_markdown
        if not content:
            logger.error(
                f"No content extracted from {url}: rendered HTML length={len(html_content)}, "
                f"fit_markdown length={len(fit_markdown)}, raw_markdown length={len(raw_markdown)}"
            )
            raise ExtractionError(f"No content extracted from {url}")

        logger.info(f"Extraction completed: {url}")
        return content

    async def _index_content(self, scraped: ScrapedItem) -> bool:
        if self.indexer is None:
            return False
        try:
            scraped.internal_refid = await self.indexer.upsert(scraped)
            logger.info(f"Indexed: {scraped.source_url}")
            return True
        except Exception as exc:
            logger.error(f"Indexing failed for {scraped.source_url}: {exc}", exc_info=True)
            return False
