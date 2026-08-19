from crawlers.quotes_authors_crawler import QuotesAuthorsCrawler

_AUTHOR_HTML = """
<html><body>
<div class="author-details">
  <h3 class="author-title">Albert Einstein</h3>
  <p class="author-born-date">March 14, 1879</p>
  <p class="author-born-location">in Ulm, Germany</p>
  <div class="author-description">Theoretical physicist.</div>
</div>
</body></html>
"""


def test_parse_author_fields_extracts_name_and_birth_details():
    source_refid, name, born_date, born_location = QuotesAuthorsCrawler._parse_author_fields(
        "https://quotes.toscrape.com/author/Albert-Einstein/", _AUTHOR_HTML
    )
    assert source_refid == "Albert-Einstein"
    assert name == "Albert Einstein"
    assert born_date == "March 14, 1879"
    assert born_location == "in Ulm, Germany"


def test_parse_author_fields_falls_back_to_na_on_missing_elements():
    source_refid, name, born_date, born_location = QuotesAuthorsCrawler._parse_author_fields(
        "https://quotes.toscrape.com/author/Unknown/", "<html><body>nothing here</body></html>"
    )
    assert source_refid == "Unknown"
    assert name == "NA"
    assert born_date == "NA"
    assert born_location == "NA"


def test_quotes_crawler_owns_its_own_playwright_session():
    # Click-through crawlers manage their own browser across both phases, so
    # ExtractionService must not pre-render the listing URL for them.
    assert QuotesAuthorsCrawler().requires_prerendered_html("https://quotes.toscrape.com/") is False
