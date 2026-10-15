"""Fetch layer: one rendered-page fetch for every `browser`-kind adapter.

Backend per M0 spike (docs/spike-m0.md, binding):

- default: crawl4ai in dedicated mode (its default `browser_mode`); Playwright
  (under crawl4ai) resolves the CloakBrowser binary through the repo-local
  ``.pw-browsers`` symlink tree that `radar.browser` points
  PLAYWRIGHT_BROWSERS_PATH at. The custom-CDP door was rejected in M0.
- ``RADAR_FETCH_BACKEND=playwright``: direct Playwright launch with
  ``executable_path=CLOAK_BIN`` (the M0-proven fallback).

One crawl per call via ``asyncio.run``; sequential fetch is the pacing —
retries/backoff are deferred by ruling (design spec §9).
crawl4ai/playwright are imported lazily inside the fetch functions so
importing `radar.fetch` stays cheap.
"""

import asyncio
import os

from radar.browser import CLOAK_BIN, ensure_pw_browsers

# M0-proven crawl4ai parameters (docs/spike-m0.md): DOM ready + a short settle
# delay is enough for the client-rendered listings, and survives pages whose
# connections never go idle (networkidle is NOT used — it timed out on devfolio
# in M0).
CRAWL4AI_WAIT_UNTIL = "domcontentloaded"
CRAWL4AI_PAGE_TIMEOUT_MS = 45_000
CRAWL4AI_DELAY_BEFORE_HTML_S = 2.5

# M0-proven fallback parameters.
PLAYWRIGHT_TIMEOUT_MS = 45_000
PLAYWRIGHT_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


def _backend() -> str:
    """Selected backend: ``crawl4ai`` (default) or ``playwright``.

    Env-driven so tests can pin it without touching the network.
    """
    return os.environ.get("RADAR_FETCH_BACKEND", "crawl4ai")


def fetch_page(url: str) -> str:
    """Fetch a JS-rendered page and return its HTML.

    Backend from ``RADAR_FETCH_BACKEND``: unset/``crawl4ai`` -> crawl4ai
    dedicated mode; ``playwright`` -> direct CloakBrowser launch.
    """
    if _backend() == "playwright":
        return _fetch_playwright(url)
    return asyncio.run(_fetch_crawl4ai(url))


async def _fetch_crawl4ai(url: str) -> str:
    """crawl4ai dedicated-mode crawl (browser lifecycle owned by crawl4ai)."""
    # Fail fast with the provisioning hint instead of letting Playwright try
    # to download a stock browser.
    ensure_pw_browsers()
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(headless=True)  # browser_mode=dedicated is the default
    run_config = CrawlerRunConfig(
        wait_until=CRAWL4AI_WAIT_UNTIL,
        page_timeout=CRAWL4AI_PAGE_TIMEOUT_MS,
        delay_before_return_html=CRAWL4AI_DELAY_BEFORE_HTML_S,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url, config=run_config)
    if not result.success:
        raise RuntimeError(
            f"crawl4ai fetch failed for {url}: {result.error_message or 'unknown error'}"
        )
    return result.html or ""


def _fetch_playwright(url: str) -> str:
    """M0 fallback: Playwright drives the CloakBrowser binary directly."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CLOAK_BIN,
            headless=True,
            args=PLAYWRIGHT_LAUNCH_ARGS,
        )
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
            return page.content()
        finally:
            browser.close()
