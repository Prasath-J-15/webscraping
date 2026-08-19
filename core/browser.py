import asyncio

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from core.config import settings
from core.exceptions import ExtractionError
from core.logger import get_logger

logger = get_logger(__name__)

PLAYWRIGHT_TIMEOUT_MS: int = settings.playwright_timeout_ms
PLAYWRIGHT_RENDER_WAIT_MS: int = settings.playwright_render_wait_ms


def render_page_in_thread(
    url: str,
    timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS,
    wait_ms: int = PLAYWRIGHT_RENDER_WAIT_MS,
) -> str:
    """Render a URL with Playwright and return the fully-rendered HTML.

    Meant to be called via ``asyncio.to_thread(render_page_in_thread, ...)``.
    Uvicorn's default event loop on Windows is a SelectorEventLoop, which
    cannot spawn the subprocess Playwright needs to launch Chromium. Running
    this function in a worker thread with its own fresh ProactorEventLoop
    sidesteps that without touching the loop FastAPI itself runs on.

    Raises:
        ExtractionError: If the browser fails to launch, navigation times out,
                          or content can't be captured.
    """

    async def _run() -> str:
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(
                    headless=settings.playwright_headless,
                    channel=settings.playwright_channel or None,
                )
            except Exception as exc:
                raise ExtractionError(f"Failed to launch browser for {url}: {exc}") from exc

            try:
                page = await browser.new_page()
                page.set_default_timeout(timeout_ms)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise ExtractionError(f"Page load timed out after {timeout_ms}ms for {url}") from exc
                except Exception as exc:
                    raise ExtractionError(f"Navigation failed for {url}: {exc}") from exc

                # Proceed as soon as the network goes idle instead of always
                # sleeping the full wait_ms; falls back to wait_ms as a ceiling
                # for pages with continuous background polling that never idle.
                try:
                    await page.wait_for_load_state("networkidle", timeout=wait_ms)
                except PlaywrightTimeoutError:
                    pass

                try:
                    return await page.content()
                except Exception as exc:
                    raise ExtractionError(f"Failed to capture page content for {url}: {exc}") from exc
            finally:
                await browser.close()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Playwright session failed for {url}: {exc}") from exc
    finally:
        loop.close()
