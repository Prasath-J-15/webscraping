"""Shared browser-restart, retry, and streaming utilities for click-through crawlers.

A "click-through" crawler is one that has to (1) collect a list of detail-page
URLs — usually by walking pagination on a listing page — and then (2) visit
every one of those URLs individually to pull the real content. Two problems
show up as soon as the URL count gets non-trivial:

- A single Chromium instance kept open across hundreds of page visits leaks
  memory and gets flaky. `run_pages_with_restart` visits URLs in batches and
  restarts the browser between batches.
- Buffering every (url, html) pair in memory until the whole crawl finishes
  doesn't scale and delays indexing. Passing a `process_chunk` callback lets
  the caller convert + push each batch to a consumer immediately, and the
  raw HTML is freed (`gc.collect()`) before the next batch starts.
"""

import asyncio
import gc
from typing import Awaitable, Callable, Optional

from playwright.async_api import Page, async_playwright

from core.browser import PLAYWRIGHT_RENDER_WAIT_MS, PLAYWRIGHT_TIMEOUT_MS
from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

_MAX_BROWSER_RETRIES = 3

ProcessChunkFn = Callable[[list[tuple[str, str]]], Awaitable[list]]


async def visit_with_retry(
    page: Page,
    detail_url: str,
    timeout_ms: int,
    wait_ms: int,
    ready_selector: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """Navigate to `detail_url` and return `(final_url, html)`, retrying on failure.

    Retries up to `settings.empty_page_max_retries` times when navigation
    throws, a `ready_selector` never appears, or the captured HTML looks
    suspiciously small. Returns None after exhausting all attempts so the
    caller can just skip the URL rather than aborting the whole batch.
    """
    max_retries = settings.empty_page_max_retries

    for attempt in range(1, max_retries + 1):
        try:
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(wait_ms)

            if ready_selector:
                try:
                    await page.wait_for_selector(ready_selector, timeout=timeout_ms)
                except Exception:
                    if attempt < max_retries:
                        logger.warning(
                            f"Ready selector '{ready_selector}' not found on {detail_url} "
                            f"(attempt {attempt}/{max_retries}) — reloading"
                        )
                        await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                        await page.wait_for_timeout(wait_ms)
                        continue
                    logger.warning(f"'{ready_selector}' never appeared on {detail_url} after {max_retries} attempts — skipping")

            html = await page.content()
            if len(html.strip()) < 500 and attempt < max_retries:
                logger.warning(f"Suspiciously little content on {detail_url} (attempt {attempt}/{max_retries}) — reloading")
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(wait_ms)
                continue

            return page.url, html

        except Exception as exc:
            if attempt < max_retries:
                logger.warning(f"Load failed for {detail_url} (attempt {attempt}/{max_retries}): {exc}")
                await asyncio.sleep(2)
            else:
                logger.warning(f"Skipped {detail_url} after {max_retries} attempt(s): {exc}")

    return None


def run_pages_with_restart(
    detail_urls: list[str],
    timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS,
    wait_ms: int = PLAYWRIGHT_RENDER_WAIT_MS,
    ready_selector: Optional[str] = None,
    process_chunk: Optional[ProcessChunkFn] = None,
    restart_every: Optional[int] = None,
) -> list:
    """Visit every URL in `detail_urls` in batches, restarting the browser between batches.

    Meant to be called via `asyncio.to_thread(run_pages_with_restart, ...)` —
    creates its own `asyncio.ProactorEventLoop`, same rationale as
    `core/browser.py:render_page_in_thread`.

    Args:
        detail_urls: Ordered list of detail-page URLs to visit.
        ready_selector: CSS selector that must appear before HTML is captured;
            the page is reloaded and retried when it doesn't show up.
        process_chunk: Async callback invoked with each batch's (url, html)
            pairs right after that batch's browser session closes. When
            provided, the raw HTML is discarded and `gc.collect()` runs
            before the next session starts, so memory never accumulates
            across a long crawl. Must return the processed items for that
            batch (e.g. list[RawJobData]).
        restart_every: Restart the browser after this many pages. Defaults to
            `settings.browser_restart_after_pages`.

    Returns:
        list[RawJobData] when `process_chunk` is given, else list[tuple[str, str]].
    """
    if restart_every is None:
        restart_every = settings.browser_restart_after_pages

    async def _run() -> list:
        total = len(detail_urls)
        all_results: list = []

        launch_kwargs: dict = dict(
            headless=settings.playwright_headless,
            channel=settings.playwright_channel or None,
        )

        for batch_start in range(0, max(total, 1), restart_every):
            batch_urls = detail_urls[batch_start : batch_start + restart_every]
            if not batch_urls:
                break

            batch_num = batch_start // restart_every + 1
            total_batches = max(1, (total + restart_every - 1) // restart_every)
            logger.info(
                f"Browser session {batch_num}/{total_batches}: visiting items "
                f"{batch_start + 1}-{min(batch_start + len(batch_urls), total)}/{total}"
            )

            chunk: list[tuple[str, str]] = []
            succeeded = False

            for attempt in range(1, _MAX_BROWSER_RETRIES + 1):
                chunk = []
                try:
                    async with async_playwright() as pw:
                        try:
                            browser = await pw.chromium.launch(**launch_kwargs)
                        except Exception as exc:
                            raise RuntimeError(f"Failed to launch browser: {exc}") from exc

                        try:
                            page = await browser.new_page()
                            page.set_default_timeout(timeout_ms)

                            for i, detail_url in enumerate(batch_urls):
                                result = await visit_with_retry(page, detail_url, timeout_ms, wait_ms, ready_selector)
                                if result is not None:
                                    chunk.append(result)
                                    logger.info(f"Captured item {batch_start + i + 1}/{total}: {result[0]}")
                        finally:
                            await browser.close()
                    succeeded = True
                    break
                except Exception as exc:
                    logger.warning(f"Browser session attempt {attempt}/{_MAX_BROWSER_RETRIES} failed: {exc}", exc_info=True)
                    if attempt < _MAX_BROWSER_RETRIES:
                        logger.info("Retrying browser session in 5s...")
                        await asyncio.sleep(5)

            if not succeeded:
                logger.error(f"All {_MAX_BROWSER_RETRIES} browser attempts failed for batch {batch_num} — skipping {len(batch_urls)} item(s)")

            if process_chunk is not None and chunk:
                chunk_size = len(chunk)
                try:
                    processed = await process_chunk(chunk)
                except Exception as exc:
                    logger.error(f"Batch {batch_num}/{total_batches}: process_chunk failed — skipping {chunk_size} item(s): {exc}", exc_info=True)
                    processed = []
                all_results.extend(processed)
                del chunk
                gc.collect()
                # processed stays empty in streaming mode (callers push results onto
                # their own queue and return [] by design) — log the batch size, not
                # len(processed), or every streamed batch would misleadingly read "0".
                logger.info(f"Batch {batch_num}/{total_batches}: ran {chunk_size} item(s) through process_chunk, HTML freed from memory")
            else:
                all_results.extend(chunk)

            remaining = total - (batch_start + len(batch_urls))
            if remaining > 0:
                logger.info(f"Restarting browser to free memory — {batch_start + len(batch_urls)}/{total} done, {remaining} remaining")
                gc.collect()
                await asyncio.sleep(1)

        return all_results

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
