"""Generic "walk Next-page links, collect item URLs, stop at a cap" helper.

Any click-through crawler whose listing page paginates via a simple "next"
link can reuse this instead of hand-rolling its own pagination loop. Keeps
the TEST_MODE capping logic (which needs to sit in exactly one place so every
crawler behaves consistently) out of individual crawler files.
"""

from urllib.parse import urljoin
from typing import Optional

from playwright.async_api import Page

from core.logger import get_logger

logger = get_logger(__name__)


async def collect_paginated_urls(
    page: Page,
    start_url: str,
    item_link_selector: str,
    next_link_selector: str,
    timeout_ms: int,
    wait_ms: int,
    limit: Optional[int] = None,
) -> list[str]:
    """Follow "next page" links from `start_url`, collecting item URLs as we go.

    Pagination is always followed to completion even when `limit` is set —
    only *collection* stops once the cap is hit, matching the project-wide
    TEST_MODE contract ("pagination is still followed; collection stops once
    the limit is reached").

    Args:
        page: An already-open Playwright page.
        start_url: The first listing page to visit.
        item_link_selector: CSS selector matching each item's anchor tag.
        next_link_selector: CSS selector matching the "next page" anchor;
            absent/disabled on the last page.
        limit: Max number of URLs to collect (TEST_MODE cap). None = no cap.

    Returns:
        Ordered, de-duplicated list of absolute item URLs.
    """
    collected: list[str] = []
    seen: set[str] = set()
    current_url = start_url
    page_num = 1

    while current_url:
        try:
            await page.goto(current_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(wait_ms)
        except Exception as exc:
            logger.warning(f"Failed to load listing page {page_num} ({current_url}): {exc}")
            break

        hrefs = await page.eval_on_selector_all(item_link_selector, "els => els.map(e => e.getAttribute('href'))")
        new_on_page = 0
        for href in hrefs:
            if not href:
                continue
            absolute = urljoin(current_url, href)
            if absolute not in seen:
                seen.add(absolute)
                collected.append(absolute)
                new_on_page += 1

        logger.info(f"Listing page {page_num}: found {new_on_page} new item(s), {len(collected)} total")

        if limit is not None and len(collected) >= limit:
            logger.info(f"Collection cap ({limit}) reached — stopping pagination early")
            break

        next_el = await page.query_selector(next_link_selector)
        next_href = await next_el.get_attribute("href") if next_el else None

        current_url = urljoin(current_url, next_href) if next_href else None
        page_num += 1

    if limit is not None:
        collected = collected[:limit]

    return collected
