"""
tests/test_web_search.py
────────────────────────
File test thực tế (integration test) cho WebSearchTool.

Chạy:
    cd ai-service
    python -m pytest tests/test_web_search.py -v -s

Hoặc chạy thẳng bằng Python (không cần pytest):
    python tests/test_web_search.py

Yêu cầu:
    - SERPER_API_KEY    : bắt buộc (có trong .env)
    - FIRECRAWL_API_KEY : tuỳ chọn (nếu thiếu, test scraping sẽ skip)

Cấu trúc test:
    TestSerperOnly          -> chỉ dùng Serper (không Firecrawl)
    TestSerperWithFirecrawl -> full pipeline Serper + Firecrawl
    TestEdgeCases           -> các trường hợp biên (query lạ, num=1, num=10)
"""

import asyncio
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

# ── Đảm bảo import đúng package từ ai-service/ ───────────────────────────────
ROOT = Path(__file__).resolve().parents[1]   # ai-service/
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.tools.web_search import (
    WebSearchTool,
    _FirecrawlScraper,
    _build_site_query,
    _clean_markdown,
    _collect_candidates,
    make_web_search_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERPER_KEY    = settings.SERPER_API_KEY
_FIRECRAWL_KEY = settings.FIRECRAWL_API_KEY

_HAS_SERPER    = bool(_SERPER_KEY)
_HAS_FIRECRAWL = bool(_FIRECRAWL_KEY)

_SKIP_SERPER    = pytest.mark.skipif(not _HAS_SERPER,    reason="SERPER_API_KEY chưa cấu hình")
_SKIP_FIRECRAWL = pytest.mark.skipif(not _HAS_FIRECRAWL, reason="FIRECRAWL_API_KEY chưa cấu hình")

_SEP = "─" * 70


def _print_result(label: str, result: str):
    """In kết quả test đẹp, cắt ngắn nếu quá dài."""
    print(f"\n{_SEP}")
    print(f"  {label}")
    print(_SEP)
    # In tối đa 2000 ký tự
    preview = result[:2000]
    if len(result) > 2000:
        preview += f"\n\n... [CẮT NGẮN - tổng {len(result):,} ký tự]"
    print(textwrap.indent(preview, "  "))
    print(_SEP)


# ---------------------------------------------------------------------------
# Unit tests - không cần API key
# ---------------------------------------------------------------------------

class TestBuildSiteQuery:
    """Kiểm tra hàm xây dựng query lọc site."""

    def test_single_site(self):
        q = _build_site_query("test query", ["example.com"])
        assert q == "test query site:example.com"

    def test_multi_site(self):
        q = _build_site_query("mức phạt", ["vanban.chinhphu.vn", "moj.gov.vn"])
        assert "site:vanban.chinhphu.vn" in q
        assert "site:moj.gov.vn" in q
        assert " OR " in q

    def test_query_preserved(self):
        original = "Nghị định 168/2024/NĐ-CP điều 5"
        q = _build_site_query(original, ["vbpl.vn"])
        assert original in q


class TestCleanMarkdown:
    """Kiểm tra hàm lọc Markdown nhiễu."""

    def test_removes_nav_links(self):
        raw = """## Tiêu đề

Đây là nội dung thực sự.

- [Trang chủ](https://example.com/)
- [Giới thiệu](https://example.com/intro)
- [Sơ đồ cổng](https://example.com/sitemap)

Nội dung pháp lý quan trọng."""
        result = _clean_markdown(raw)
        assert "Trang chủ" not in result
        assert "Giới thiệu" not in result
        assert "Nội dung pháp lý quan trọng" in result
        assert "Tiêu đề" in result

    def test_keeps_inline_links(self):
        """Link inline trong câu văn KHÔNG bị xoá."""
        raw = "Xem thêm [Nghị định 168](https://vbpl.vn/nd168) để biết chi tiết."
        result = _clean_markdown(raw)
        assert "Nghị định 168" in result

    def test_collapses_blank_lines(self):
        raw = "Line 1\n\n\n\n\nLine 2"
        result = _clean_markdown(raw)
        assert "\n\n\n" not in result

    def test_empty_input(self):
        assert _clean_markdown("") == ""


# ---------------------------------------------------------------------------
# Integration tests - Serper only (không Firecrawl)
# ---------------------------------------------------------------------------

class TestSerperOnly:
    """Test WebSearchTool chỉ dùng Serper snippet (không Firecrawl)."""

    def _make_tool(self) -> WebSearchTool:
        return make_web_search_tool(
            serper_api_key=_SERPER_KEY,
            firecrawl_api_key="",   # chủ ý để trống
        )

    @_SKIP_SERPER
    def test_basic_search_sync(self):
        """Test _run (sync) với câu hỏi pháp lý cơ bản."""
        tool = self._make_tool()
        result = tool._run("mức phạt vượt đèn đỏ nghị định 168 2024")

        _print_result("TestSerperOnly::test_basic_search_sync", result)

        assert isinstance(result, str)
        assert len(result) > 50, "Kết quả quá ngắn, có thể không tìm được gì"
        assert "Lỗi" not in result[:30], f"Tool trả lỗi: {result[:200]}"

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_basic_search_async(self):
        """Test _arun (async) với câu hỏi pháp lý cơ bản."""
        tool = self._make_tool()
        result = await tool._arun("nồng độ cồn khi lái xe 2024")

        _print_result("TestSerperOnly::test_basic_search_async", result)

        assert isinstance(result, str)
        assert len(result) > 50
        assert "Lỗi" not in result[:30]

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_tier1_sources_present(self):
        """Kết quả phải chứa ít nhất 1 URL từ nguồn Tier 1."""
        tool = self._make_tool()
        result = await tool._arun("Nghị định 168/2024/NĐ-CP")

        _print_result("TestSerperOnly::test_tier1_sources_present", result)

        tier1_domains = [
            "vanban.chinhphu.vn",
            "moj.gov.vn",
            "quochoi.vn",
            "vbpl.vn",
        ]
        found_tier1 = any(d in result for d in tier1_domains)
        assert found_tier1, (
            f"Không tìm thấy nguồn Tier 1 nào trong kết quả.\n"
            f"Preview: {result[:500]}"
        )

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_tier_label_in_output(self):
        """Output phải có nhãn tier (🏛️ hoặc 📚)."""
        tool = self._make_tool()
        result = await tool._arun("tốc độ tối đa xe ô tô trong khu đô thị")

        _print_result("TestSerperOnly::test_tier_label_in_output", result)

        assert "🏛️" in result or "📚" in result, (
            "Không tìm thấy nhãn tier trong output"
        )

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_num_param(self):
        """Test tham số num - yêu cầu 1 kết quả."""
        tool = self._make_tool()
        result = await tool._arun("luật giao thông", num=1)

        _print_result("TestSerperOnly::test_num_param (num=1)", result)

        # Chỉ có 1 block kết quả -> chỉ có [1]
        assert "[1]" in result
        assert "[2]" not in result

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_no_results_graceful(self):
        """Query quá kỳ lạ -> không crash, trả về thông báo rõ ràng."""
        tool = self._make_tool()
        # Query rác, rất khó có kết quả từ các site luật
        result = await tool._arun("xyzxyzxyz không tồn tại abcdefg", num=2)

        _print_result("TestSerperOnly::test_no_results_graceful", result)

        assert isinstance(result, str)
        # Không được raise exception - bất kể kết quả rỗng hay có


# ---------------------------------------------------------------------------
# Integration tests - Collect candidates (Serper raw)
# ---------------------------------------------------------------------------

class TestCollectCandidates:
    """Test hàm _collect_candidates riêng lẻ."""

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_returns_list(self):
        candidates = await _collect_candidates(
            api_key=_SERPER_KEY,
            query="mức phạt uống rượu lái xe",
            num=3,
            gl="vn",
            hl="vi",
        )

        print(f"\n  Số candidates: {len(candidates)}")
        for c in candidates:
            print(f"  [Tier {c['tier']}] {c['title'][:60]} | {c['url'][:60]}")

        assert isinstance(candidates, list)
        assert all("url" in c and "tier" in c for c in candidates)

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_tier_values(self):
        """Tier phải là 1 hoặc 2."""
        candidates = await _collect_candidates(
            api_key=_SERPER_KEY,
            query="Nghị định 100/2019",
            num=5,
            gl="vn",
            hl="vi",
        )
        for c in candidates:
            assert c["tier"] in (1, 2), f"Tier lạ: {c['tier']} - {c['url']}"

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_no_duplicate_urls(self):
        """Không được có URL trùng nhau."""
        candidates = await _collect_candidates(
            api_key=_SERPER_KEY,
            query="xử phạt xe không chính chủ",
            num=6,
            gl="vn",
            hl="vi",
        )
        urls = [c["url"] for c in candidates]
        assert len(urls) == len(set(urls)), f"URL trùng: {urls}"


# ---------------------------------------------------------------------------
# Integration tests - Firecrawl scraper
# ---------------------------------------------------------------------------

class TestFirecrawlScraper:
    """Test _FirecrawlScraper riêng lẻ với một URL cụ thể."""

    @_SKIP_FIRECRAWL
    @pytest.mark.asyncio
    async def test_scrape_real_url(self):
        """Scrape trang Cổng Chính phủ để lấy Markdown."""
        scraper = _FirecrawlScraper(api_key=_FIRECRAWL_KEY)
        # Trang tương đối ổn định
        url = "https://vbpl.vn/TW/Pages/Home.aspx"
        result = await scraper.scrape(url)

        print(f"\n  URL: {url}")
        if result:
            print(f"  ✅ Scrape thành công - {len(result):,} ký tự")
            print(f"  Preview: {result[:300]}")
        else:
            print("  ⚠️  Scrape trả về None (có thể timeout hoặc block)")

        # Chỉ kiểm tra không crash - None cũng được chấp nhận
        assert result is None or isinstance(result, str)

    @_SKIP_FIRECRAWL
    @pytest.mark.asyncio
    async def test_scrape_invalid_url(self):
        """URL không tồn tại -> trả về None, không raise exception."""
        scraper = _FirecrawlScraper(api_key=_FIRECRAWL_KEY)
        result = await scraper.scrape("https://this-domain-does-not-exist-xyz.vn/abc")
        assert result is None, "URL lỗi phải trả về None"

    @_SKIP_FIRECRAWL
    @pytest.mark.asyncio
    async def test_scrape_many_concurrent(self):
        """Scrape nhiều URL song song."""
        scraper = _FirecrawlScraper(api_key=_FIRECRAWL_KEY)
        urls = [
            "https://moj.gov.vn",
            "https://quochoi.vn",
            "https://thuvienphapluat.vn",
        ]
        start = time.monotonic()
        results = await scraper.scrape_many(urls)
        elapsed = time.monotonic() - start

        print(f"\n  Scraped {len(urls)} URL trong {elapsed:.1f}s")
        for url, res in zip(urls, results):
            status = f"✅ {len(res):,} ký tự" if res else "⚠️  None"
            print(f"  {status} - {url}")

        assert len(results) == len(urls)
        assert all(r is None or isinstance(r, str) for r in results)


# ---------------------------------------------------------------------------
# Integration tests - Full pipeline (Serper + Firecrawl)
# ---------------------------------------------------------------------------

class TestSerperWithFirecrawl:
    """Full pipeline: Serper tìm URL -> Firecrawl cào nội dung."""

    def _make_tool(self) -> WebSearchTool:
        return make_web_search_tool(
            serper_api_key=_SERPER_KEY,
            firecrawl_api_key=_FIRECRAWL_KEY,
        )

    @_SKIP_SERPER
    @_SKIP_FIRECRAWL
    @pytest.mark.asyncio
    async def test_full_pipeline_law_query(self):
        """Pipeline đầy đủ: tìm + cào trang pháp lý."""
        tool = self._make_tool()

        start = time.monotonic()
        result = await tool._arun("mức phạt vượt đèn đỏ Nghị định 168 2024", num=3)
        elapsed = time.monotonic() - start

        _print_result(
            f"TestSerperWithFirecrawl::full_pipeline (elapsed: {elapsed:.1f}s)",
            result,
        )

        assert isinstance(result, str)
        assert len(result) > 100
        # Khi Firecrawl hoạt động, output nên có "Firecrawl (toàn văn)"
        # hoặc "Serper snippet" làm fallback - ít nhất 1 trong 2
        has_firecrawl_content = "Firecrawl (toàn văn)" in result
        has_snippet_fallback  = "Serper snippet" in result
        assert has_firecrawl_content or has_snippet_fallback, (
            "Không tìm thấy nguồn nội dung trong output"
        )

    @_SKIP_SERPER
    @_SKIP_FIRECRAWL
    @pytest.mark.asyncio
    async def test_output_contains_url(self):
        """Mỗi kết quả phải có URL."""
        tool = self._make_tool()
        result = await tool._arun("nồng độ cồn bằng 0 nghị định 168", num=2)

        _print_result("TestSerperWithFirecrawl::test_output_contains_url", result)

        assert "URL:" in result or "https://" in result


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Các trường hợp biên."""

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_empty_query(self):
        """Query rỗng -> không crash."""
        tool = make_web_search_tool(serper_api_key=_SERPER_KEY)
        result = await tool._arun("", num=1)
        assert isinstance(result, str)

    @_SKIP_SERPER
    @pytest.mark.asyncio
    async def test_max_num(self):
        """num = 10 (tối đa) -> không lỗi validation."""
        tool = make_web_search_tool(serper_api_key=_SERPER_KEY)
        result = await tool._arun("luật giao thông đường bộ", num=10)
        assert isinstance(result, str)

    def test_no_serper_key(self):
        """Thiếu SERPER_API_KEY -> trả về thông báo lỗi, không raise."""
        tool = make_web_search_tool(serper_api_key="")
        result = tool._run("test")
        assert "SERPER_API_KEY" in result or "Lỗi" in result

    def test_tool_metadata(self):
        """Kiểm tra metadata của LangChain tool."""
        tool = make_web_search_tool(serper_api_key="dummy")
        assert tool.name == "web_search"
        assert len(tool.description) > 20
        assert tool.args_schema is not None


# ---------------------------------------------------------------------------
# Runner thủ công (không cần pytest)
# ---------------------------------------------------------------------------

async def _manual_run():
    """Chạy thủ công một test nhanh để xem output thực tế."""
    print("\n" + "═" * 70)
    print("  MANUAL TEST - WebSearchTool")
    print("═" * 70)

    if not _HAS_SERPER:
        print("❌ SERPER_API_KEY chưa được đặt trong .env!")
        return

    tool = make_web_search_tool(
        serper_api_key=_SERPER_KEY,
        firecrawl_api_key=_FIRECRAWL_KEY,
    )

    queries = [
        "mức phạt vượt đèn đỏ Nghị định 168/2024/NĐ-CP",
        "nồng độ cồn bằng 0 khi lái xe 2024",
    ]

    for q in queries:
        print(f"\n🔍 Query: {q}")
        print(f"   Firecrawl: {'✅ bật' if _HAS_FIRECRAWL else '⚠️  tắt (chỉ snippet)'}")
        start = time.monotonic()
        result = await tool._arun(q, num=3)
        elapsed = time.monotonic() - start
        print(f"   ⏱  {elapsed:.1f}s - {len(result):,} ký tự")
        _print_result(f"Query: {q}", result)


if __name__ == "__main__":
    asyncio.run(_manual_run())
