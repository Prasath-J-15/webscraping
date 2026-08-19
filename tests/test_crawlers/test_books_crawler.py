import pytest

from core.exceptions import ExtractionError
from crawlers.books_crawler import BooksCatalogCrawler

_SAMPLE_HTML = """
<html><body>
<article class="product_pod">
  <div class="image_container">
    <a href="catalogue/a-light-in-the-attic_1000/index.html">
      <img src="media/thumb.jpg" alt="A Light in the Attic">
    </a>
  </div>
  <p class="star-rating Three"></p>
  <h3><a href="catalogue/a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light ...</a></h3>
  <div class="product_price">
    <p class="price_color">£51.77</p>
    <p class="instock availability">
      <i class="icon-ok"></i>
      In stock
    </p>
  </div>
</article>
<article class="product_pod">
  <div class="image_container">
    <a href="catalogue/soumission_998/index.html">
      <img src="media/thumb2.jpg" alt="Soumission">
    </a>
  </div>
  <p class="star-rating One"></p>
  <h3><a href="catalogue/soumission_998/index.html" title="Soumission">Soumission</a></h3>
  <div class="product_price">
    <p class="price_color">£50.10</p>
    <p class="instock availability">
      <i class="icon-ok"></i>
      In stock
    </p>
  </div>
</article>
</body></html>
"""


@pytest.mark.asyncio
async def test_extract_parses_every_book_card():
    crawler = BooksCatalogCrawler()
    items = await crawler.extract("https://books.toscrape.com/", _SAMPLE_HTML)

    assert len(items) == 2
    first = items[0]
    assert first.source_refid == "a-light-in-the-attic_1000"
    assert first.source_url == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert "A Light in the Attic" in first.extracted_content
    assert "£51.77" in first.extracted_content
    assert "Three" in first.extracted_content


@pytest.mark.asyncio
async def test_extract_raises_when_no_html_given():
    crawler = BooksCatalogCrawler()
    with pytest.raises(ExtractionError):
        await crawler.extract("https://books.toscrape.com/", None)


@pytest.mark.asyncio
async def test_extract_raises_when_layout_unrecognised():
    crawler = BooksCatalogCrawler()
    with pytest.raises(ExtractionError):
        await crawler.extract("https://books.toscrape.com/", "<html><body>no books here</body></html>")


def test_books_crawler_requires_prerendered_html():
    assert BooksCatalogCrawler().requires_prerendered_html("https://books.toscrape.com/") is True
