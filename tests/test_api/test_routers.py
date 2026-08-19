from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from api.dependencies import get_extraction_service, get_scrape_service
from main import app
from models.schemas import JobContentResponse, ScrapeResponse

_NOW = datetime.now(timezone.utc)


def _sample_job_response() -> JobContentResponse:
    return JobContentResponse(
        internalRefid=1,
        sourceRefid="a-light-in-the-attic_1000",
        sourceURL="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        domain="books.toscrape.com",
        extractedContent="A Light in the Attic\nPrice: £51.77",
        createdAt=_NOW,
        updatedAt=_NOW,
        indexed=False,
    )


def _sample_scrape_response() -> ScrapeResponse:
    return ScrapeResponse(
        internalRefid=0,
        sourceRefid="NA",
        sourceURL="https://quotes.toscrape.com/js/",
        domain="quotes.toscrape.com",
        extractedContent="Some rendered content",
        createdAt=_NOW,
        updatedAt=_NOW,
        indexed=False,
    )


@pytest.fixture
def client():
    mock_extraction_service = AsyncMock()
    mock_extraction_service.extract.return_value = [_sample_job_response()]

    mock_scrape_service = AsyncMock()
    mock_scrape_service.scrape.return_value = _sample_scrape_response()

    app.dependency_overrides[get_extraction_service] = lambda: mock_extraction_service
    app.dependency_overrides[get_scrape_service] = lambda: mock_scrape_service
    try:
        yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_extract_endpoint_returns_items(client):
    async with client as ac:
        resp = await ac.post("/extract", json={"url": "https://books.toscrape.com/"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["sourceRefid"] == "a-light-in-the-attic_1000"


@pytest.mark.asyncio
async def test_scrape_endpoint_returns_single_item(client):
    async with client as ac:
        resp = await ac.post("/scrape", json={"url": "https://quotes.toscrape.com/js/"})
    assert resp.status_code == 200
    assert resp.json()["domain"] == "quotes.toscrape.com"


@pytest.mark.asyncio
async def test_extract_endpoint_accepts_bare_domain_without_scheme(client):
    async with client as ac:
        resp = await ac.post("/extract", json={"url": "books.toscrape.com"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_endpoint_reports_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
