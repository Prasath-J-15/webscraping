"""Read-only search/browse API backing the static dashboard in frontend/.

Mirrors the real "webscraper writes, a separate dashboard reads" split from
a shared Elasticsearch index — just folded into one app for this demo. Never
writes to the index; every route here is a plain query.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

from core.config import settings
from core.logger import get_logger
from db.elasticsearch_client import get_elasticsearch_client
from dispatcher.crawler_dispatcher import DOMAIN_REGISTRY

logger = get_logger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

DOMAIN_DISPLAY_NAMES: dict[str, str] = {
    "books.toscrape.com": "Books to Scrape",
    "quotes.toscrape.com": "Quotes to Scrape",
}

_EMPTY_PAGE = {"total": 0, "results": []}


@router.get("/domains")
async def list_domains() -> list[dict]:
    """Every registered domain with its display label and total item count.

    Used for both the search dropdown (key/label only) and the Browse
    Domains card grid, which also needs the count to grey out empty domains
    — unlike /report/today, this never omits a domain for having zero items.
    """
    es = get_elasticsearch_client()
    domains = []
    for key in DOMAIN_REGISTRY:
        total_items = 0
        if es is not None:
            try:
                total_items = (await es.count(index=settings.index_name, query={"term": {"domain": key}}))["count"]
            except Exception as exc:
                logger.warning(f"Domain count failed for {key}: {exc}")
        domains.append({"key": key, "label": DOMAIN_DISPLAY_NAMES.get(key, key), "totalItems": total_items})
    logger.info(f"Listed {len(domains)} registered domain(s)")
    return domains


@router.get("/search")
async def search_items(
    q: Optional[str] = Query(None, description="Keyword — matches extractedContent (full-text) and sourceRefid (wildcard)"),
    domain: Optional[str] = Query(None, description="Domain key to filter, e.g. books.toscrape.com"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
) -> dict:
    """Full-text search over indexed items, with optional domain filter and pagination.

    With `q`: bool/should match on extractedContent + wildcard on sourceRefid,
    sorted by relevance then recency. Without `q`: everything, most recent first.
    """
    es = get_elasticsearch_client()
    if es is None:
        logger.info(f"Dashboard search: q={q!r} domain={domain!r} — Elasticsearch not configured, returning empty page")
        return {**_EMPTY_PAGE, "page": page, "size": size}

    must: list[dict] = [{"term": {"domain": domain}}] if domain else []

    if q:
        query = {
            "bool": {
                "must": must,
                "should": [
                    {"match": {"extractedContent": q}},
                    {"wildcard": {"sourceRefid": f"*{q}*"}},
                ],
                "minimum_should_match": 1,
            }
        }
        sort = ["_score", {"updatedAt": {"order": "desc"}}]
    else:
        query = {"bool": {"must": must}} if must else {"match_all": {}}
        sort = [{"updatedAt": {"order": "desc"}}]

    try:
        resp = await es.search(
            index=settings.index_name,
            query=query,
            sort=sort,
            from_=(page - 1) * size,
            size=size,
        )
    except Exception as exc:
        logger.error(f"Dashboard search failed for q={q!r} domain={domain!r}: {exc}", exc_info=True)
        return {**_EMPTY_PAGE, "page": page, "size": size}

    total = resp["hits"]["total"]["value"]
    results = [
        {**hit["_source"], "domainLabel": DOMAIN_DISPLAY_NAMES.get(hit["_source"].get("domain", ""), hit["_source"].get("domain", "NA"))}
        for hit in resp["hits"]["hits"]
    ]
    logger.info(f"Dashboard search: q={q!r} domain={domain!r} page={page} -> {total} total result(s), {len(results)} returned")
    return {"total": total, "page": page, "size": size, "results": results}


@router.get("/report/today")
async def report_today() -> dict:
    """Domain-wise item counts for today. Domains with zero total items are excluded."""
    es = get_elasticsearch_client()
    rows: list[dict] = []
    total_items = total_new_today = total_ingested_today = 0
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    if es is not None:
        for domain_key in DOMAIN_REGISTRY:
            try:
                total = (await es.count(index=settings.index_name, query={"term": {"domain": domain_key}}))["count"]
                if total == 0:
                    continue
                new_today = (
                    await es.count(
                        index=settings.index_name,
                        query={"bool": {"must": [{"term": {"domain": domain_key}}, {"range": {"createdAt": {"gte": today_start}}}]}},
                    )
                )["count"]
                ingested_today = (
                    await es.count(
                        index=settings.index_name,
                        query={"bool": {"must": [{"term": {"domain": domain_key}}, {"range": {"updatedAt": {"gte": today_start}}}]}},
                    )
                )["count"]
            except Exception as exc:
                logger.warning(f"Report count failed for domain {domain_key}: {exc}")
                continue

            rows.append(
                {
                    "domain": domain_key,
                    "displayName": DOMAIN_DISPLAY_NAMES.get(domain_key, domain_key),
                    "totalItems": total,
                    "newToday": new_today,
                    "ingestedToday": ingested_today,
                }
            )
            total_items += total
            total_new_today += new_today
            total_ingested_today += ingested_today

    logger.info(
        f"Today's report: {len(rows)} domain(s) with items, "
        f"{total_items} total item(s), {total_new_today} new today, {total_ingested_today} ingested today"
    )
    return {
        "rows": rows,
        "totalItems": total_items,
        "totalNewToday": total_new_today,
        "totalIngestedToday": total_ingested_today,
        "reportDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
