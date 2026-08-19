import html
import re

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"\*{2,3}([\s\S]+?)\*{2,3}")  # spans multiple lines
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_UNDERSCORE_RE = re.compile(r"_{1,2}([^_\n]+)_{1,2}")
_BULLET_RE = re.compile(r"^\s*[-•*+]\s+", re.MULTILINE)
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)


def clean_markdown(text: str) -> str:
    """Convert extracted Markdown to clean plain text.

    Strips markdown syntax (headings, bold, bullets, links) so the output
    reads as natural paragraphs — easier to read and better for full-text search.
    """
    if not text:
        return "NA"

    text = html.unescape(text)  # &nbsp;/&amp; etc. -> literal characters
    text = text.replace("\xa0", " ")  # non-breaking space -> regular space
    text = _IMAGE_RE.sub("", text)  # ![alt](url) -> '' (drop images entirely)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)  # [label](url) -> label
    text = _HEADING_RE.sub("", text)  # ## Heading -> Heading
    text = _BOLD_ITALIC_RE.sub(r"\1", text)  # **bold** / ***bold*** -> text
    text = _ITALIC_RE.sub(r"\1", text)  # *italic* -> text
    text = _UNDERSCORE_RE.sub(r"\1", text)  # __bold__ / _italic_ -> text
    text = _BULLET_RE.sub("", text)  # - item -> item
    text = _NUMBERED_LIST_RE.sub("", text)  # 1. item -> item
    text = re.sub(r"\*+", "", text)  # leftover/dangling asterisks
    text = re.sub(r"\[\]", "", text)  # empty template brackets []
    text = re.sub(r"\n{3,}", "\n\n", text)  # 3+ blank lines -> 1 blank line
    text = re.sub(r"[ \t]+", " ", text)  # collapse spaces/tabs
    text = re.sub(r" \n", "\n", text)  # trailing space before newline
    text = text.strip()

    return text if text else "NA"
