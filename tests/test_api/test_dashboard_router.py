from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import api.dashboard_router as dashboard_router
from main import app


def _mock_es(search_hits=None, counts_by_domain=None):
    """Build a mock AsyncElasticsearch stub for the dashboard endpoints under test."""
    es = AsyncMock()
    es.search.return_value = {
        "hits": {
            "total": {"value": len(search_hits or [])},
            "hits": [{"_source": h} for h in (search_hits or [])],
        }
    }

    async def _count(index, query):
        domain = query.get("term", {}).get("domain") or query.get("bool", {}).get("must", [{}])[0].get("term", {}).get("domain")
        return {"count": (counts_by_domain or {}).get(domain, 0)}

    es.count.side_effect = _count
    return es


@pytest.fixture
def use_es(monkeypatch):
    """Patch the module-level get_elasticsearch_client() the router calls, per test."""

    def _apply(es_or_none):
        monkeypatch.setattr(dashboard_router, "get_elasticsearch_client", lambda: es_or_none)

    return _apply


async def _get(path: str, **params) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(path, params=params)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_list_domains_returns_registered_domains_with_counts(use_es):
    use_es(_mock_es(counts_by_domain={"books.toscrape.com": 20, "quotes.toscrape.com": 0}))
    body = {row["key"]: row for row in await _get("/api/dashboard/domains")}
    assert body["books.toscrape.com"]["totalItems"] == 20
    assert body["quotes.toscrape.com"]["totalItems"] == 0
    assert body["books.toscrape.com"]["label"] == "Books to Scrape"


@pytest.mark.asyncio
async def test_search_without_es_configured_returns_empty_page(use_es):
    use_es(None)
    body = await _get("/api/dashboard/search", q="quote")
    assert body == {"total": 0, "page": 1, "size": 10, "results": []}


@pytest.mark.asyncio
async def test_search_returns_hits_with_domain_label(use_es):
    hits = [{"sourceRefid": "a-light-in-the-attic_1000", "domain": "books.toscrape.com", "extractedContent": "..."}]
    use_es(_mock_es(search_hits=hits))
    body = await _get("/api/dashboard/search")
    assert body["total"] == 1
    assert body["results"][0]["domainLabel"] == "Books to Scrape"


@pytest.mark.asyncio
async def test_report_today_excludes_zero_item_domains(use_es):
    use_es(_mock_es(counts_by_domain={"books.toscrape.com": 20}))
    body = await _get("/api/dashboard/report/today")
    domains_in_report = {row["domain"] for row in body["rows"]}
    assert "books.toscrape.com" in domains_in_report
    assert "quotes.toscrape.com" not in domains_in_report
