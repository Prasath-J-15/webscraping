import pytest

from core.config import settings
from core.exceptions import ExtractionError
from crawlers.books_crawler import BooksCatalogCrawler

_LISTING_HTML = """
<html><body>
<article class="product_pod">
  <h3><a href="catalogue/a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light ...</a></h3>
</article>
<article class="product_pod">
  <h3><a href="catalogue/soumission_998/index.html" title="Soumission">Soumission</a></h3>
</article>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
<div class="product_main">
  <h1>A Light in the Attic</h1>
  <p class="price_color">£51.77</p>
  <p class="instock availability">
    <i class="icon-ok"></i>
    In stock (22 available)
  </p>
  <p class="star-rating Three"></p>
</div>
<div id="product_description" class="sub-header"><h2>Product Description</h2></div>
<p>A classic collection of poetry and drawings.</p>
</body></html>
"""


def test_collect_book_urls_parses_every_card_and_resolves_absolute_urls():
    urls = BooksCatalogCrawler._collect_book_urls("https://books.toscrape.com/", _LISTING_HTML)
    assert urls == [
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "https://books.toscrape.com/catalogue/soumission_998/index.html",
    ]


def test_collect_book_urls_respects_test_mode_cap():
    settings.test_mode_job_limit = 1
    urls = BooksCatalogCrawler._collect_book_urls("https://books.toscrape.com/", _LISTING_HTML)
    assert len(urls) == 1


def test_collect_book_urls_raises_when_layout_unrecognised():
    with pytest.raises(ExtractionError):
        BooksCatalogCrawler._collect_book_urls("https://books.toscrape.com/", "<html><body>no books here</body></html>")


def test_parse_detail_fields_extracts_structured_metadata():
    fields = BooksCatalogCrawler._parse_detail_fields(
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", _DETAIL_HTML
    )
    assert fields == {
        "source_refid": "a-light-in-the-attic_1000",
        "title": "A Light in the Attic",
        "price": "£51.77",
        "availability": "In stock (22 available)",
        "rating": "Three",
    }


@pytest.mark.asyncio
async def test_extract_book_combines_parsed_fields_with_crawl4ai_description(mocker):
    crawler = BooksCatalogCrawler()

    fake_result = mocker.Mock(success=True, markdown="A classic collection of poetry and drawings.")
    mock_crawl4ai = mocker.AsyncMock()
    mock_crawl4ai.arun = mocker.AsyncMock(return_value=fake_result)

    raw = await crawler._extract_book(
        mock_crawl4ai, "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", _DETAIL_HTML
    )

    assert raw.source_refid == "a-light-in-the-attic_1000"
    assert "A Light in the Attic" in raw.extracted_content
    assert "£51.77" in raw.extracted_content
    assert "A classic collection of poetry and drawings." in raw.extracted_content
    mock_crawl4ai.arun.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_book_falls_back_to_na_when_crawl4ai_fails(mocker):
    crawler = BooksCatalogCrawler()
    mock_crawl4ai = mocker.AsyncMock()
    mock_crawl4ai.arun = mocker.AsyncMock(side_effect=RuntimeError("boom"))

    raw = await crawler._extract_book(mock_crawl4ai, "https://books.toscrape.com/catalogue/x/index.html", _DETAIL_HTML)

    assert raw is not None
    assert raw.extracted_content.endswith("NA")


def test_books_crawler_requires_prerendered_html():
    assert BooksCatalogCrawler().requires_prerendered_html("https://books.toscrape.com/") is True
