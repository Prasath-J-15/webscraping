import pytest

from services.text_cleaner import clean_markdown


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", "NA"),
        (None, "NA"),
        ("# Heading\nBody text", "Heading\nBody text"),
        ("**bold** and *italic*", "bold and italic"),
        ("- item one\n- item two", "item one\nitem two"),
        ("1. first\n2. second", "first\nsecond"),
        ("[label](https://example.com)", "label"),
        ("![alt text](https://example.com/img.png)", "NA"),  # image-only content collapses to empty -> "NA"
        ("line one\n\n\n\nline two", "line one\n\nline two"),
        ("a &amp; b", "a & b"),
    ],
)
def test_clean_markdown(raw, expected):
    assert clean_markdown(raw) == expected
