"""Standalone async script — crawls every registered demo domain sequentially.

Not a FastAPI route. Run directly:

    python services/batch_runner.py

Streams results to batch_output/items_<timestamp>.json one item at a time
(rather than building one giant list in memory) and writes a short summary
report to batch_output/report_<timestamp>.txt.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import aiofiles

from core.logger import get_logger
from db.elasticsearch_client import close_elasticsearch, init_elasticsearch
from db.elasticsearch_indexer import ElasticsearchIndexer
from services.extraction_service import ExtractionService
from services.scrape_service import ScrapeService

logger = get_logger(__name__)

OUTPUT_DIR = "batch_output"

# Update this alongside dispatcher/crawler_dispatcher.py's DOMAIN_REGISTRY.
URLS = [
    "https://books.toscrape.com/",
    "https://quotes.toscrape.com/",
]


async def run() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    items_path = os.path.join(OUTPUT_DIR, f"items_{timestamp}.json")
    report_path = os.path.join(OUTPUT_DIR, f"report_{timestamp}.txt")

    es_client = await init_elasticsearch()
    indexer = ElasticsearchIndexer(es_client) if es_client is not None else None
    if indexer is not None:
        await indexer.ensure_index()

    service = ExtractionService(indexer=indexer, scrape_service=ScrapeService(indexer=indexer))

    summary: list[dict] = []
    item_count = 0

    async with aiofiles.open(items_path, "w", encoding="utf-8") as f:
        await f.write("[\n")
        first = True

        for url in URLS:
            logger.info(f"Batch: starting {url}")
            per_url_count = 0
            error: str | None = None

            async def on_job(response, _url=url) -> None:
                nonlocal item_count, first, per_url_count
                per_url_count += 1
                item_count += 1
                if not first:
                    await f.write(",\n")
                first = False
                await f.write(json.dumps(response.model_dump(mode="json", by_alias=True), indent=2))

            try:
                await service.extract(url, on_job=on_job)
            except Exception as exc:
                error = str(exc)
                logger.error(f"Batch: {url} failed: {exc}", exc_info=True)

            summary.append({"url": url, "items": per_url_count, "error": error})
            logger.info(f"Batch: finished {url} — {per_url_count} item(s){f' — ERROR: {error}' if error else ''}")

        await f.write("\n]\n")

    async with aiofiles.open(report_path, "w", encoding="utf-8") as f:
        await f.write(f"Batch run: {timestamp}\n")
        await f.write(f"Total items: {item_count}\n\n")
        for row in summary:
            status = f"ERROR: {row['error']}" if row["error"] else "OK"
            await f.write(f"{row['url']:<45} items={row['items']:<4} {status}\n")

    await close_elasticsearch()
    logger.info(f"Batch run complete: {item_count} item(s) written to {items_path}")


if __name__ == "__main__":
    asyncio.run(run())
