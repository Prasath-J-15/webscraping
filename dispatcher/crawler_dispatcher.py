from urllib.parse import urlparse

from core.exceptions import UnsupportedDomainError
from core.logger import get_logger
from crawlers.base_crawler import BaseCrawler
from crawlers.books_crawler import BooksCatalogCrawler
from crawlers.quotes_authors_crawler import QuotesAuthorsCrawler

logger = get_logger(__name__)

# Domain -> crawler class. Adding a new site is a one-line addition here plus
# a new crawlers/<site>_crawler.py — no changes to routing or services.
DOMAIN_REGISTRY: dict[str, type[BaseCrawler]] = {
    "books.toscrape.com": BooksCatalogCrawler,
    "quotes.toscrape.com": QuotesAuthorsCrawler,
}

# Multi-label public-suffix TLDs (e.g. "example.co.uk") need one extra label
# kept so they aren't truncated down to just "co.uk".
_MULTI_LABEL_TLDS = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "co.in"}

# Apex domains where distinct subdomains are genuinely distinct *sites* for
# dispatch purposes, not a "www."/CDN prefix — e.g. toscrape.com hosts two
# unrelated practice sites at books.toscrape.com and quotes.toscrape.com, so
# collapsing both to "toscrape.com" would make them indistinguishable to
# resolve_crawler(). Mirrors the real-world case of a multi-tenant platform
# that hosts each client under its own subdomain of one shared apex domain.
_SUBDOMAIN_AWARE_APEX_DOMAINS = {"toscrape.com"}


def extract_domain(url: str) -> str:
    """Extract the registrable domain (e.g. "books.toscrape.com") from a full URL."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception as exc:
        logger.warning(f"Could not parse URL {url!r}: {exc}")
        return ""
    parts = hostname.split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]

    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_LABEL_TLDS:
        apex = ".".join(parts[-3:])
        remaining = parts[:-3]
    else:
        apex = ".".join(parts[-2:]) if len(parts) >= 2 else hostname
        remaining = parts[:-2] if len(parts) >= 2 else []

    if apex in _SUBDOMAIN_AWARE_APEX_DOMAINS and remaining:
        return f"{remaining[-1]}.{apex}"
    return apex


def resolve_crawler(url: str) -> BaseCrawler:
    """Return the appropriate crawler instance for the given URL.

    Raises:
        UnsupportedDomainError: If no crawler is registered for the URL's domain.
    """
    domain = extract_domain(url)
    crawler_cls = DOMAIN_REGISTRY.get(domain)
    if crawler_cls is None:
        logger.warning(f"Unsupported domain: {domain}")
        raise UnsupportedDomainError(f"No crawler registered for domain: {domain}")
    try:
        crawler = crawler_cls()
    except Exception as exc:
        logger.error(f"Failed to instantiate {crawler_cls.__name__} for domain {domain!r}: {exc}", exc_info=True)
        raise
    logger.info(f"Resolved crawler {crawler_cls.__name__} for domain: {domain}")
    return crawler
