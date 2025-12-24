"""JavaScript Renderer service for SEO Platform.

Renders JavaScript-heavy pages using Playwright to extract fully-rendered content.
Implements hybrid mode to determine when JS rendering is needed.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright


@dataclass
class RenderResult:
    """Result of rendering a page with JavaScript execution."""

    url: str
    html: str
    title: str
    meta_description: str
    h1_count: int
    word_count: int
    render_time_ms: int
    error: str | None = None


class Renderer:
    """JavaScript renderer using Playwright for dynamic page rendering."""

    def __init__(
        self, timeout_ms: int = 30000, user_agent: str = "SEOPlatformBot/1.0"
    ) -> None:
        """Initialize the Renderer.

        Args:
            timeout_ms: Maximum time to wait for page load in milliseconds
            user_agent: User agent string to use for requests
        """
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent
        self.browser: Browser | None = None
        self._playwright: Playwright | None = None

    async def start(self) -> None:
        """Start the Playwright browser instance."""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )

    async def stop(self) -> None:
        """Stop the browser and cleanup resources."""
        if self.browser:
            await self.browser.close()
            self.browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def render(self, url: str) -> RenderResult:
        """Render a page with JavaScript execution.

        Args:
            url: The URL to render

        Returns:
            RenderResult with extracted content or error information
        """
        start_time = time.time()

        try:
            if not self.browser:
                raise RuntimeError("Browser not started. Call start() first.")

            # Create new context with user agent
            context = await self.browser.new_context(user_agent=self.user_agent)

            try:
                # Create new page
                page = await context.new_page()

                # Set timeout for navigation
                page.set_default_timeout(float(self.timeout_ms))

                # Navigate to URL with networkidle wait
                await page.goto(url, wait_until="networkidle")

                # Wait additional 1 second for JS to settle
                await asyncio.sleep(1)

                # Extract content using JavaScript execution
                content: Any = await page.evaluate(
                    """() => {
                    // Get title
                    const title = document.title || '';

                    // Get meta description
                    const metaDesc = document.querySelector('meta[name="description"]');
                    const metaDescription = metaDesc ? metaDesc.getAttribute('content') || '' : '';

                    // Count h1 elements
                    const h1Count = document.querySelectorAll('h1').length;

                    // Get body text and count words
                    const bodyText = document.body.innerText || '';
                    const wordCount = bodyText.trim().split(/\\s+/).filter(word => word.length > 0).length;

                    // Get full HTML
                    const html = document.documentElement.outerHTML;

                    return {
                        title: title,
                        metaDescription: metaDescription,
                        h1Count: h1Count,
                        wordCount: wordCount,
                        html: html
                    };
                }"""
                )

                # Calculate render time
                render_time_ms = int((time.time() - start_time) * 1000)

                return RenderResult(
                    url=url,
                    html=content["html"],
                    title=content["title"],
                    meta_description=content["metaDescription"],
                    h1_count=content["h1Count"],
                    word_count=content["wordCount"],
                    render_time_ms=render_time_ms,
                    error=None,
                )

            finally:
                # Always close the context
                await context.close()

        except Exception as e:
            # Calculate render time even on error
            render_time_ms = int((time.time() - start_time) * 1000)

            return RenderResult(
                url=url,
                html="",
                title="",
                meta_description="",
                h1_count=0,
                word_count=0,
                render_time_ms=render_time_ms,
                error=str(e),
            )

    def should_render(
        self,
        html_word_count: int,
        has_title: bool,
        has_h1: bool,
        min_word_threshold: int = 50,
    ) -> bool:
        """Determine if a page needs JavaScript rendering (hybrid mode).

        Args:
            html_word_count: Word count from static HTML
            has_title: Whether the page has a title
            has_h1: Whether the page has an h1 element
            min_word_threshold: Minimum word count to consider sufficient

        Returns:
            True if the page needs JS rendering, False otherwise
        """
        # Need rendering if word count is below threshold
        if html_word_count < min_word_threshold:
            return True

        # Need rendering if missing critical elements
        if not has_title or not has_h1:
            return True

        # Otherwise, static HTML is sufficient
        return False
