"""Tests for the JavaScript Renderer service.

Following TDD - these tests are written FIRST before implementation.
"""

import pytest

from app.services.audit.renderer import Renderer, RenderResult


class TestRenderResult:
    """Test the RenderResult dataclass."""

    def test_render_result_creation_success(self) -> None:
        """Test creating a successful RenderResult."""
        result = RenderResult(
            url="https://example.com",
            html="<html><body>Test content</body></html>",
            title="Example Domain",
            meta_description="This is an example",
            h1_count=2,
            word_count=150,
            render_time_ms=250,
            error=None,
        )

        assert result.url == "https://example.com"
        assert result.html == "<html><body>Test content</body></html>"
        assert result.title == "Example Domain"
        assert result.meta_description == "This is an example"
        assert result.h1_count == 2
        assert result.word_count == 150
        assert result.render_time_ms == 250
        assert result.error is None

    def test_render_result_creation_with_error(self) -> None:
        """Test creating a RenderResult with an error."""
        result = RenderResult(
            url="https://example.com",
            html="",
            title="",
            meta_description="",
            h1_count=0,
            word_count=0,
            render_time_ms=100,
            error="Timeout exceeded",
        )

        assert result.url == "https://example.com"
        assert result.html == ""
        assert result.error == "Timeout exceeded"
        assert result.word_count == 0


class TestRendererShouldRender:
    """Test the should_render logic (hybrid mode detection)."""

    def test_should_render_low_word_count(self) -> None:
        """Test that pages with low word count need rendering."""
        renderer = Renderer()

        # Less than threshold (default 50)
        assert renderer.should_render(
            html_word_count=30, has_title=True, has_h1=True
        ) is True

    def test_should_render_missing_title(self) -> None:
        """Test that pages missing title need rendering."""
        renderer = Renderer()

        assert renderer.should_render(
            html_word_count=100, has_title=False, has_h1=True
        ) is True

    def test_should_render_missing_h1(self) -> None:
        """Test that pages missing h1 need rendering."""
        renderer = Renderer()

        assert renderer.should_render(
            html_word_count=100, has_title=True, has_h1=False
        ) is True

    def test_should_not_render_sufficient_content(self) -> None:
        """Test that pages with sufficient content don't need rendering."""
        renderer = Renderer()

        assert renderer.should_render(
            html_word_count=100, has_title=True, has_h1=True
        ) is False

    def test_should_render_custom_threshold(self) -> None:
        """Test should_render with custom word count threshold."""
        renderer = Renderer()

        # Just above custom threshold
        assert renderer.should_render(
            html_word_count=85,
            has_title=True,
            has_h1=True,
            min_word_threshold=80,
        ) is False

        # Below custom threshold
        assert renderer.should_render(
            html_word_count=75,
            has_title=True,
            has_h1=True,
            min_word_threshold=80,
        ) is True

    def test_should_render_edge_case_at_threshold(self) -> None:
        """Test should_render at exact threshold boundary."""
        renderer = Renderer()

        # Exactly at threshold should not render
        assert renderer.should_render(
            html_word_count=50, has_title=True, has_h1=True
        ) is False


class TestRendererInitialization:
    """Test Renderer initialization."""

    def test_renderer_default_initialization(self) -> None:
        """Test Renderer with default parameters."""
        renderer = Renderer()

        assert renderer.timeout_ms == 30000
        assert renderer.user_agent == "SEOPlatformBot/1.0"

    def test_renderer_custom_initialization(self) -> None:
        """Test Renderer with custom parameters."""
        renderer = Renderer(timeout_ms=15000, user_agent="CustomBot/2.0")

        assert renderer.timeout_ms == 15000
        assert renderer.user_agent == "CustomBot/2.0"


@pytest.mark.skip(reason="Playwright integration test - requires browser setup")
class TestRendererIntegration:
    """Integration tests for actual rendering (requires Playwright)."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        """Test starting and stopping the renderer."""
        renderer = Renderer()

        await renderer.start()
        assert renderer.browser is not None

        await renderer.stop()
        # Browser should be closed

    @pytest.mark.asyncio
    async def test_render_simple_page(self) -> None:
        """Test rendering a simple static page."""
        renderer = Renderer()
        await renderer.start()

        try:
            result = await renderer.render("https://example.com")

            assert result.url == "https://example.com"
            assert result.error is None
            assert "Example Domain" in result.title
            assert result.word_count > 0
            assert result.render_time_ms > 0
        finally:
            await renderer.stop()

    @pytest.mark.asyncio
    async def test_render_with_timeout(self) -> None:
        """Test rendering with timeout error."""
        renderer = Renderer(timeout_ms=1)  # Very short timeout
        await renderer.start()

        try:
            result = await renderer.render("https://example.com")

            # Should have an error due to timeout
            assert result.error is not None
        finally:
            await renderer.stop()
