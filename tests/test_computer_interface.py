#!/usr/bin/env python3
"""Deterministic contracts for the browser and visible-desktop surface."""

import unittest
from unittest.mock import patch

from core.action_protocol import classify_tool_result, verify_receipts
from tools import browser, desktop_control
from tools.tool_declarations import BROWSER_TOOLS, DESKTOP_TOOLS


class _Element:
    def __init__(self, label, tag="button"):
        self.label = label
        self.tag = tag
        self.clicked = False

    def is_visible(self):
        return True

    def evaluate(self, script):
        if "tagName" in script:
            return self.tag
        return None

    def get_attribute(self, name):
        return self.label if name == "aria-label" else ""

    def inner_text(self, timeout=None):
        return self.label

    def click(self, timeout=None):
        self.clicked = True


class _Collection:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    @property
    def first(self):
        return self.items[0]


class _Body:
    def count(self):
        return 1

    def inner_text(self):
        return "Video title\nChannel name"


class _Page:
    url = "https://www.youtube.com/watch?v=abc"

    def __init__(self):
        self.play = _Element("Play", "button")

    def title(self):
        return "Video title - YouTube"

    def locator(self, selector):
        if selector == "body":
            return _Body()
        if selector.startswith("a, button"):
            return _Collection([self.play])
        return _Collection([self.play])


class BrowserSurfaceTests(unittest.TestCase):
    def tearDown(self):
        browser._browser_page = None
        browser._browser_refs = {}

    def test_snapshot_exposes_short_stable_element_refs(self):
        page = _Page()
        snapshot = browser._page_snapshot(page)
        self.assertIn('[e1] button "Play"', snapshot)
        self.assertIn("Video title", snapshot)
        self.assertIs(browser._resolve_element(page, "e1"), page.play)
        self.assertIs(browser._resolve_element(page, "[e1]"), page.play)

    def test_interaction_accepts_a_short_ref(self):
        page = _Page()
        browser._browser_page = page
        browser._browser_refs = {"e1": page.play}
        result = browser.browse_interact("e1", "click")
        self.assertEqual(result, "Clicked: e1")
        self.assertTrue(page.play.clicked)

    def test_browser_contract_has_observation_tool(self):
        names = {item["name"] for item in BROWSER_TOOLS}
        self.assertIn("browse_observe", names)
        interaction = next(
            item for item in BROWSER_TOOLS if item["name"] == "browse_interact"
        )
        self.assertIn(
            "short element ref",
            interaction["parameters"]["properties"]["selector"]["description"].lower(),
        )


class VisibleDesktopTests(unittest.TestCase):
    def test_visible_url_tool_is_declared(self):
        names = {item["name"] for item in DESKTOP_TOOLS}
        self.assertIn("desktop_open_url", names)

    def test_open_url_rejects_non_http_without_launching(self):
        with patch("tools.desktop_control.subprocess.Popen") as popen:
            result = desktop_control.desktop_open_url("file:///tmp/private")
        self.assertIn("http or https", result)
        popen.assert_not_called()

    def test_click_does_not_hide_xdotool_failure(self):
        with patch(
            "tools.desktop_control._run_xdotool",
            return_value="xdotool error: display unavailable",
        ) as run:
            result = desktop_control.desktop_click(10, 20)
        self.assertEqual(result, "xdotool error: display unavailable")
        self.assertEqual(run.call_count, 1)

    def test_visible_launch_needs_later_window_observation(self):
        opened = classify_tool_result(
            "desktop_open_url",
            {"url": "https://youtube.com/watch?v=abc"},
            "Opened URL in the default browser: https://youtube.com/watch?v=abc",
        )
        self.assertEqual(verify_receipts([opened]).status.value, "partial")
        window = classify_tool_result(
            "desktop_window", {}, "Active window: Video title - YouTube"
        )
        self.assertEqual(verify_receipts([opened, window]).status.value, "verified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
