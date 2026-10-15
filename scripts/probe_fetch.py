#!/usr/bin/env python3
"""Probe helper: fetch a URL through the CloakBrowser stealth browser.

Usage:
  .venv/bin/python scripts/probe_fetch.py <url> [--save path/to/file.html] [--playwright]

Backends:
  default      - crawl4ai dedicated mode resolving the CloakBrowser binary
                 through the repo-local .pw-browsers tree (the M0-chosen
                 backend; the custom-CDP attach door was rejected in M0).
  --playwright - Playwright launches the CloakBrowser binary directly (the
                 M0-proven fallback).
"""
import argparse
import asyncio
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

CLOAK_BIN = "/home/ubuntu/.cloakbrowser/chromium-146.0.7680.177.5/chrome"


async def fetch_crawl4ai(url: str):
    # CloakBrowser resolution needs the repo-local symlink tree — same default
    # radar.browser pins for the fetch layer.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".pw-browsers"))
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    cfg = BrowserConfig(headless=True)  # dedicated mode (crawl4ai's default)
    async with AsyncWebCrawler(config=cfg) as crawler:
        res = await crawler.arun(
            url,
            config=CrawlerRunConfig(
                wait_until="domcontentloaded",  # M0: networkidle timed out on devfolio
                page_timeout=45000,
                delay_before_return_html=2.5,
            ),
        )
    return res.html or "", res.markdown or ""


def fetch_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CLOAK_BIN,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            return page.content()
        finally:
            browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--save", default=None)
    ap.add_argument("--playwright", action="store_true")
    a = ap.parse_args()

    if a.playwright:
        html, md = fetch_playwright(a.url), ""
    else:
        html, md = asyncio.run(fetch_crawl4ai(a.url))

    print(f"fetched: {len(html)} chars html" + (f" | {len(md)} chars md" if md else ""))
    if a.save:
        p = pathlib.Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        print(f"saved -> {p}")
    else:
        print(html[:300])


if __name__ == "__main__":
    main()
