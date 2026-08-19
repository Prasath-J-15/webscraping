import pytest

from core.exceptions import UnsupportedDomainError
from crawlers.books_crawler import BooksCatalogCrawler
from crawlers.quotes_authors_crawler import QuotesAuthorsCrawler
from dispatcher.crawler_dispatcher import extract_domain, resolve_crawler


@pytest.mark.parametrize(
    "url, expected_domain",
    [
        ("https://books.toscrape.com/catalogue/page-2.html", "books.toscrape.com"),
        ("https://www.books.toscrape.com/", "books.toscrape.com"),  # "www" is stripped
        ("https://quotes.toscrape.com/page/3/", "quotes.toscrape.com"),
        # Multi-label TLD: must keep the extra label instead of truncating to "co.uk"
        ("https://jobs.example.co.uk/careers", "example.co.uk"),
        ("not a url at all", ""),
    ],
)
def test_extract_domain(url, expected_domain):
    assert extract_domain(url) == expected_domain


def test_resolve_crawler_returns_books_crawler():
    crawler = resolve_crawler("https://books.toscrape.com/")
    assert isinstance(crawler, BooksCatalogCrawler)


def test_resolve_crawler_returns_quotes_crawler():
    crawler = resolve_crawler("https://quotes.toscrape.com/")
    assert isinstance(crawler, QuotesAuthorsCrawler)


def test_resolve_crawler_raises_for_unregistered_domain():
    with pytest.raises(UnsupportedDomainError):
        resolve_crawler("https://not-a-registered-site.example.com/")
