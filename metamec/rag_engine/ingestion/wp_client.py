"""
WordPress REST API client.

Uses HTTP Basic Auth with a WordPress Application Password
(username + application password, NOT the admin login password).

Docs: https://developer.wordpress.org/rest-api/reference/pages/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from .wp_cleaner import clean_wp_content

logger = logging.getLogger(__name__)


@dataclass
class WPDocument:
    """A single normalized WordPress document (page/post) ready for chunking."""

    source_id: str          # e.g. "wp-page-123"
    post_type: str           # "page" | "post" | ...
    title: str
    url: str
    content_html: str
    modified_at: str

    @property
    def content_text(self) -> str:
        # Strips WPBakery shortcodes ([vc_row ...]) as well as HTML tags.
        # See wp_cleaner.py for why this is needed on this site.
        return clean_wp_content(self.content_html)


class WordPressClient:
    """Thin wrapper around the WP REST API for read-only content sync."""

    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: str,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (username, app_password)
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        url = f"{self.base_url}/wp-json/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def check_connection(self) -> bool:
        """Sanity check that the REST API + credentials work."""
        try:
            resp = self._get("wp/v2/pages", params={"per_page": 1})
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error("WordPress connection check failed: %s", e)
            return False

    def fetch_all(self, post_type: str, per_page: int = 50) -> Iterator[dict[str, Any]]:
        """
        Paginate through all items of a given post type
        (e.g. 'pages', 'posts', or a custom post type slug).
        """
        page = 1
        while True:
            resp = self._get(
                f"wp/v2/{post_type}",
                params={
                    "per_page": per_page,
                    "page": page,
                    "status": "publish",
                    "_fields": "id,title,link,content,modified_gmt",
                },
            )
            items = resp.json()
            if not items:
                return
            yield from items

            total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
            if page >= total_pages:
                return
            page += 1

    def fetch_documents(self, post_types: list[str]) -> list[WPDocument]:
        """Fetch and normalize all documents across the given post types."""
        docs: list[WPDocument] = []
        for post_type in post_types:
            singular = post_type.rstrip("s")  # "pages" -> "page" (fine for id prefixing)
            for item in self.fetch_all(post_type):
                docs.append(
                    WPDocument(
                        source_id=f"wp-{singular}-{item['id']}",
                        post_type=singular,
                        title=item.get("title", {}).get("rendered", "").strip(),
                        url=item.get("link", ""),
                        content_html=item.get("content", {}).get("rendered", ""),
                        modified_at=item.get("modified_gmt", ""),
                    )
                )
        logger.info("Fetched %d documents from WordPress", len(docs))
        return docs
