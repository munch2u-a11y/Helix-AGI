"""
Helix — Web Search

Web search and URL reading for the Action Agent. Provides:
    search_web(query, max_results) → list of {title, snippet, url}
    read_url(url) → extracted text content

Uses DuckDuckGo for search (free, no API key needed).
Uses requests + BeautifulSoup for URL reading.
Falls back gracefully if dependencies are missing.
"""

import logging
from typing import Optional

logger = logging.getLogger("helix.tools.web_search")


class WebSearch:
    """Web search and URL reading backend.

    Primary: DuckDuckGo search via duckduckgo_search package.
    Fallback: Raw requests + HTML parsing.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._ddg_available = False
        self._bs4_available = False

        # Check for ddgs (renamed from duckduckgo_search)
        try:
            from ddgs import DDGS
            self._ddg_available = True
            logger.info("Web search: DuckDuckGo backend available (ddgs)")
        except ImportError:
            try:
                from duckduckgo_search import DDGS
                self._ddg_available = True
                logger.info("Web search: DuckDuckGo backend available")
            except ImportError:
                logger.warning(
                    "ddgs not installed. "
                    "Install with: pip install ddgs"
                )

        # Check for beautifulsoup4
        try:
            from bs4 import BeautifulSoup
            self._bs4_available = True
        except ImportError:
            logger.warning(
                "beautifulsoup4 not installed for rich text extraction. "
                "Falling back to basic HTML parsing."
            )

        logger.info("WebSearch initialized")

    def search_web(self, query: str, max_results: int = 5) -> list[dict]:
        """Search the web and return structured results.

        Args:
            query: The search query.
            max_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: title, snippet, url
        """
        if not query or not query.strip():
            return []

        # Try DuckDuckGo first
        if self._ddg_available:
            try:
                return self._search_ddg(query, max_results)
            except Exception as e:
                logger.warning(f"DuckDuckGo search failed: {e}")

        # Fallback: use requests to scrape DuckDuckGo HTML
        try:
            return self._search_ddg_html(query, max_results)
        except Exception as e:
            logger.error(f"All search backends failed: {e}")
            return []

    def read_url(self, url: str) -> Optional[str]:
        """Fetch and extract readable text from a URL.

        Args:
            url: The URL to read.

        Returns:
            Extracted text content (capped at 5000 chars), or None on failure.
        """
        if not url or not url.strip():
            return None

        try:
            import requests

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            resp = requests.get(url, timeout=15, headers=headers)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")

            # Handle non-HTML content
            if "json" in content_type:
                return resp.text[:5000]
            if "text/plain" in content_type:
                return resp.text[:5000]

            # Extract text from HTML
            return self._extract_text(resp.text)

        except Exception as e:
            logger.error(f"URL read failed for {url}: {e}")
            return None

    # ── DuckDuckGo search via package ────────────────────────────────

    def _search_ddg(self, query: str, max_results: int) -> list[dict]:
        """Search via ddgs package."""
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", "Untitled"),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })

        logger.info(f"DuckDuckGo search: '{query}' → {len(results)} results")
        return results

    # ── DuckDuckGo HTML fallback ─────────────────────────────────────

    def _search_ddg_html(self, query: str, max_results: int) -> list[dict]:
        """Fallback: scrape DuckDuckGo HTML lite."""
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0"
            ),
        }

        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()

        results = []

        if self._bs4_available:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            for result_div in soup.select(".result")[:max_results]:
                title_el = result_div.select_one(".result__a")
                snippet_el = result_div.select_one(".result__snippet")
                url_el = result_div.select_one(".result__url")

                title = title_el.get_text(strip=True) if title_el else "Untitled"
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                url = ""
                if title_el and title_el.get("href"):
                    url = title_el["href"]
                elif url_el:
                    url = url_el.get_text(strip=True)

                if title and title != "Untitled":
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                    })
        else:
            # Very basic parsing without BS4
            import re
            links = re.findall(
                r'class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)<',
                resp.text,
            )
            for url, title in links[:max_results]:
                if title.strip():
                    results.append({
                        "title": title.strip(),
                        "snippet": "",
                        "url": url,
                    })

        logger.info(f"DuckDuckGo HTML search: '{query}' → {len(results)} results")
        return results

    # ── Text extraction ──────────────────────────────────────────────

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML content."""
        if self._bs4_available:
            return self._extract_text_bs4(html)
        return self._extract_text_basic(html)

    def _extract_text_bs4(self, html: str) -> str:
        """Extract text using BeautifulSoup."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "noscript", "iframe", "meta", "link"]):
            tag.decompose()

        # Try to find main content area
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"role": "main"})
            or soup.find("div", {"id": "content"})
            or soup.find("div", {"class": "content"})
        )

        target = main if main else soup.body if soup.body else soup

        # Extract text with paragraph awareness
        text_parts = []
        for element in target.find_all(["p", "h1", "h2", "h3", "h4", "li", "td", "th", "pre", "blockquote"]):
            text = element.get_text(strip=True)
            if text and len(text) > 10:  # Skip tiny fragments
                text_parts.append(text)

        # If structured extraction got too little, fall back to all text
        if len(text_parts) < 3:
            text = target.get_text(separator="\n", strip=True)
            # Clean up excessive whitespace
            import re
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r' {2,}', ' ', text)
            return text[:5000]

        return "\n\n".join(text_parts)[:5000]

    def _extract_text_basic(self, html: str) -> str:
        """Basic text extraction without BeautifulSoup."""
        from html.parser import HTMLParser
        import re

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
                self._skip_tags = {"script", "style", "nav", "footer", "noscript"}
                self._skip_depth = 0

            def handle_starttag(self, tag, attrs):
                if tag in self._skip_tags:
                    self._skip_depth += 1

            def handle_endtag(self, tag):
                if tag in self._skip_tags and self._skip_depth > 0:
                    self._skip_depth -= 1

            def handle_data(self, data):
                if self._skip_depth == 0:
                    cleaned = data.strip()
                    if cleaned:
                        self.text.append(cleaned)

        parser = TextExtractor()
        parser.feed(html)
        text = " ".join(parser.text)
        text = re.sub(r' {2,}', ' ', text)
        return text[:5000]
