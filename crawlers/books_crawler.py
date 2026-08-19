"""books.toscrape.com — the "simple" crawler pattern.

The orchestrator (ExtractionService) pre-renders the page with Playwright and
hands the crawler finished HTML; the crawler's only job is to parse it. No
pagination, no click-through, no second browser session — this is the
default `requires_prerendered_html() -> True` path from BaseCrawler.

Because the catalog page already exposes clean, structured fields (title,
price, availability, rating) per book, there's nothing worth running through
Crawl4AI's HTML->Markdown pipeline here — that pipeline earns its keep on
freeform prose pages (see quotes_authors_crawler.py and services/scrape_service.py),
not on a repeating card layout that's easier to just parse directly.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.exceptions import ExtractionError
from core.logger import get_logger
from crawlers.base_crawler import BaseCrawler
from models.domain import RawJobData

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"/catalogue/([^/]+)/index\.html")


class BooksCatalogCrawler(BaseCrawler):
    """Extracts every book listed on a single books.toscrape.com catalog page."""

    def requires_prerendered_html(self, url: str) -> bool:
        return True

    async def extract(self, url: str, html_content: Optional[str] = None) -> list[RawJobData]:
        if not html_content:
            raise ExtractionError(f"No HTML provided for {url}")

        soup = BeautifulSoup(html_content, "html.parser")
        cards = soup.select("article.product_pod")
        if not cards:
            raise ExtractionError(f"No book cards found on {url} — page layout may have changed")

        items: list[RawJobData] = []
        for card in cards:
            link = card.select_one("h3 a")
            if link is None or not link.get("href"):
                continue

            title = link.get("title", link.text).strip()
            href = link["href"]
            source_url = urljoin(url, href)

            slug_match = _SLUG_RE.search(href) or _SLUG_RE.search(source_url)
            source_refid = slug_match.group(1) if slug_match else "NA"

            price_el = card.select_one("p.price_color")
            price = price_el.text.strip() if price_el else "NA"

            availability_el = card.select_one("p.instock.availability")
            availability = " ".join(availability_el.text.split()) if availability_el else "NA"

            rating_el = card.select_one("p.star-rating")
            rating = "NA"
            if rating_el is not None:
                classes = rating_el.get("class", [])
                rating = next((c for c in classes if c != "star-rating"), "NA")

            extracted_content = (
                f"{title}\n"
                f"Price: {price}\n"
                f"Availability: {availability}\n"
                f"Rating: {rating} out of Five"
            )

            items.append(
                RawJobData(
                    source_refid=source_refid,
                    source_url=source_url,
                    extracted_content=extracted_content,
                )
            )

        logger.info(f"Parsed {len(items)} book(s) from {url}")
        return items
