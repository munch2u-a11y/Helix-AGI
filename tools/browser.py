"""
Helix — Browser Automation Tools (Playwright)

Provides full browser automation via action tags:
  [BROWSE:] url                          — navigate to URL with JS rendering
  [BROWSE_INTERACT:selector] action | value — interact with page elements
  [BROWSE_SCREENSHOT:]                    — screenshot current page

Uses Playwright for headless Chromium. Domain-whitelisted for security.
"""

import logging
from pathlib import Path

logger = logging.getLogger("helix.tools.browser")

# Shared browser state (module-level)
_browser = None
_browser_page = None

# Domain whitelist
_DOMAIN_WHITELIST_FILE = Path("/home/nemo/Helix/data/domain_whitelist.txt")


def _load_domain_whitelist() -> set:
    """Load the domain whitelist from the plaintext file."""
    domains = set()
    if _DOMAIN_WHITELIST_FILE.exists():
        try:
            for line in _DOMAIN_WHITELIST_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    domains.add(line.lower())
        except Exception:
            pass
    return domains


def _is_domain_allowed(url: str) -> bool:
    """Check if a URL's domain is on the whitelist."""
    from urllib.parse import urlparse
    allowed = _load_domain_whitelist()
    if not allowed:
        return True  # If whitelist is empty/missing, allow all (fail-open)
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower()
        for domain in allowed:
            if hostname == domain or hostname.endswith(f".{domain}"):
                return True
        return False
    except Exception:
        return False


def _get_browser_page():
    """Get or create a Playwright browser page."""
    global _browser, _browser_page

    if _browser_page is None or _browser is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _browser = pw.chromium.launch(headless=True)
        _browser_page = _browser.new_page()

    return _browser_page


# ── Tool Functions ────────────────────────────────────────────────────


def browse(url: str, wait_for: str = "") -> str:
    """Navigate to a URL with full browser rendering.

    Uses Playwright for JavaScript-heavy pages that READ_URL can't handle.
    """
    if not url:
        return "URL required."

    if not _is_domain_allowed(url):
        return (
            f"Domain not on whitelist. Access denied for: {url}\n"
            f"Approved domains are listed in: data/domain_whitelist.txt"
        )

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        page = _get_browser_page()

        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=10000)
            else:
                page.wait_for_timeout(2000)
        except PlaywrightTimeoutError:
            logger.warning(f"Playwright navigation timeout on {url}. Salvaging partial DOM.")

        title = page.title()
        try:
            body_loc = page.locator("body")
            text = body_loc.inner_text() if body_loc.count() > 0 else ""
        except Exception:
            text = "Failed to extract body text."

        return (
            f"Page loaded: {title}\n"
            f"URL: {page.url}\n\n"
            f"{text[:3000]}"
        )
    except Exception as e:
        return f"Browser navigation failed: {e}"


def browse_interact(selector: str, action: str, value: str = "") -> str:
    """Interact with the current browser page.

    Actions: click, type, scroll, select, submit
    """
    if _browser_page is None:
        return "No page loaded. Use BROWSE first."

    if not action or not selector:
        return "Both action and selector are required."

    action = action.lower()

    try:
        page = _browser_page

        if action == "click":
            page.click(selector, timeout=5000)
            return f"Clicked: {selector}"
        elif action == "type":
            page.fill(selector, value, timeout=5000)
            return f"Typed '{value}' into {selector}"
        elif action == "scroll":
            page.eval_on_selector(selector, "el => el.scrollIntoView()")
            return f"Scrolled to: {selector}"
        elif action == "select":
            page.select_option(selector, value, timeout=5000)
            return f"Selected '{value}' in {selector}"
        elif action == "submit":
            page.click(selector, timeout=5000)
            try:
                from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                page.wait_for_timeout(2000)
            except PlaywrightTimeoutError:
                pass
            return f"Submitted form via {selector}. New page: {page.title()}"
        else:
            return f"Unknown action '{action}'. Use: click, type, scroll, select, submit"
    except Exception as e:
        return f"Browser interaction failed: {e}"


def browse_screenshot(full_page: bool = False) -> str:
    """Take a screenshot of the current browser page.

    Returns the file path for optional vision analysis.
    """
    if _browser_page is None:
        return "No page loaded. Use BROWSE first."

    try:
        page = _browser_page
        screenshot_dir = Path("/home/nemo/Helix/data/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        filename = f"browser_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = screenshot_dir / filename

        page.screenshot(path=str(filepath), full_page=full_page)

        return (
            f"Browser screenshot saved: {filepath}\n"
            f"Page: {page.url}\n"
            f"(Use LOOK to analyze it visually)"
        )
    except Exception as e:
        return f"Screenshot failed: {e}"
