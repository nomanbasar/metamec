"""
Cleans WordPress content that was built with the WPBakery Page Builder
(a.k.a. Visual Composer) plugin.

The WP REST API's `content.rendered` field is expected to contain fully
rendered HTML, but on some setups (this WPBakery install included) it comes
back with the raw shortcode syntax still in place, e.g.:

    [vc_row row_height_percent="0" ...][vc_column][vc_column_text]
    Actual paragraph content here.
    [/vc_column_text][/vc_column][/vc_row]

If left in, these shortcodes pollute the text sent to the embedding model —
adding noise, wasting tokens, and diluting retrieval quality with syntax
that has nothing to do with loan content.

This module strips shortcodes first, then runs the remaining HTML through
BeautifulSoup for a final plain-text extraction.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Matches WPBakery / generic WP shortcodes: [tag attr="val" ...] or [/tag]
# Also handles smart-quote attribute values (”/“) seen in some exports.
_SHORTCODE_PATTERN = re.compile(r"\[/?[a-zA-Z0-9_]+(?:\s+[^\[\]]*)?\]")


def strip_shortcodes(raw: str) -> str:
    """Remove WPBakery/WP shortcode tags, leaving inner text intact."""
    if not raw:
        return ""
    return _SHORTCODE_PATTERN.sub(" ", raw)


def clean_wp_content(raw_html: str) -> str:
    """
    Full cleaning pipeline: strip shortcodes, then strip HTML tags,
    then collapse whitespace/blank lines.
    """
    if not raw_html:
        return ""

    without_shortcodes = strip_shortcodes(raw_html)

    soup = BeautifulSoup(without_shortcodes, "html.parser")
    text = soup.get_text(separator="\n")

    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)

    # Collapse repeated spaces left behind by shortcode removal
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned
