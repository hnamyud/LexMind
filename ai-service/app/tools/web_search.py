# -*- coding: utf-8 -*-
"""
app/tools/web_search.py
───────────────────────
LangChain Tool tìm kiếm + cào nội dung văn bản pháp luật.

Pipeline 2 bước:
  Bước 1 - Serper.dev (tìm URL, song song)
    Tier 1 và Tier 2 được gọi ĐỒNG THỜI qua asyncio.gather.
    Kết quả được merge và ưu tiên theo tier.
    Tier 1 (chính thức): vanban.chinhphu.vn | moj.gov.vn | quochoi.vn | vbpl.vn
    Tier 2 (uy tín):     thuvienphapluat.vn | luatvietnam.vn

  Bước 2 - Firecrawl (cào nội dung, song song)
    - onlyMainContent=True: Firecrawl tự bỏ nav/header/footer
    - excludeTags: loại thêm sidebar, breadcrumb, cookie banner
    - _clean_markdown(): lọc Python để loại link rác còn sót
    - Tối đa MAX_CONCURRENT_SCRAPES trang chạy song song

Fallback:
    Firecrawl thất bại -> dùng snippet Serper thay thế.
"""

import asyncio
import logging
import re
from typing import Optional, Type
from urllib.parse import urlparse

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

_SERPER_URL = "https://google.serper.dev/search"

_DEFAULT_TOP_K = 5
_MAX_TOP_K = 10

# Giới hạn ký tự mỗi trang sau khi làm sạch
_MAX_CHARS_PER_PAGE = 3_000

# Timeout
_SERPER_TIMEOUT  = 8.0
_FIRECRAWL_TIMEOUT = 15.0

# Số trang cào đồng thời
_MAX_CONCURRENT_SCRAPES = 3

_TIER1_SITES: list[str] = [
    "xaydungchinhsach.chinhphu.vn",
    "moj.gov.vn",
    "quochoi.vn",
    "vbpl.vn",
]

_TIER2_SITES: list[str] = [
    "thuvienphapluat.vn",
    "luatvietnam.vn",
]

_TIER_LABEL = {1: "🏛️ Chính thức", 2: "📚 Pháp lý uy tín"}

# Cấu hình thẻ CSS cần lấy cho từng domain (dùng cho Firecrawl include_tags)
_DOMAIN_SELECTORS = {
    "moj.gov.vn": [".news-details"],
    "xaydungchinhsach.chinhphu.vn": [".detail-main"],
    "vbpl.vn": [".content"],
    "thuvienphapluat.vn": [".content1", ".news-content"],
    "luatvietnam.vn": [".the-document-body"],
}

# Tags Firecrawl sẽ loại bỏ khi extract main content
_EXCLUDE_TAGS = [
    "nav", "header", "footer", "aside",
    "script", "style", "noscript",
    ".breadcrumb", ".cookie", ".sidebar",
    ".menu", ".navigation", ".navbar",
    "#header", "#footer", "#nav",
]


# ---------------------------------------------------------------------------
# Markdown cleaner
# ---------------------------------------------------------------------------

# Regex khớp dòng CHỈ là link navigation dạng: "- [text](url)" hoặc "[text](url)"
# Không xoá inline link trong câu văn thực sự
_RE_NAV_LINK    = re.compile(r"^\s*[-*]?\s*\[([^\]]{1,80})\]\(https?://[^)]+\)\s*$")
# Dòng toàn dấu phân cách
_RE_SEPARATOR   = re.compile(r"^\s*[-=_*]{3,}\s*$")
# Dòng trắng liên tiếp (giữ tối đa 1 dòng trắng)
_RE_MULTI_BLANK = re.compile(r"\n{3,}")

_NOISE_KEYWORDS = [
    "trang chủ", "giới thiệu", "sơ đồ cổng", "thư điện tử", "thông tin điều hành",
    "thủ tục hành chính", "văn bản điều hành", "hướng dẫn nghiệp vụ",
    "hỏi đáp pháp luật", "thông cáo báo chí", "dịch vụ công trực tuyến",
    "phản ánh kiến nghị", "sự kiện", "danh bạ", "phiên bản thử nghiệm",
    "chỉ đạo điều hành", "chuyên mục", "video", "hình ảnh", "tải về",
    "đăng nhập", "đăng ký", "quên mật khẩu", "tìm kiếm"
]

def _clean_markdown(text: str) -> str:
    """
    Làm sạch Markdown từ Firecrawl - loại bỏ mạnh tay:
      - Menu, breadcrumb, sitemap chứa từ khóa nhiễu
      - Dòng chỉ chứa link navigation
      - Link hình ảnh vô nghĩa
      - Dòng trống thừa
    """
    lines = text.splitlines()
    cleaned = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
            
        # 1. Bỏ dòng chỉ là link độc lập (navigation/menu con)
        if _RE_NAV_LINK.match(line):
            continue
            
        # 2. Bỏ dòng toàn dấu phân cách
        if _RE_SEPARATOR.match(line):
            continue
            
        # 3. Bỏ dòng hiển thị ảnh (thường chứa base64 rất dài hoặc link ảnh)
        if stripped.startswith("![") or "[![" in stripped:
            continue
            
        # 4. Kiểm tra dòng có chứa các link thường xuất hiện ở navigation header/footer
        # Chỉ check nếu dòng đó chủ yếu là link (dấu hiệu của menu)
        if "[" in line and "]" in line and "(" in line and ")" in line:
            line_lower = line.lower()
            is_noise = any(kw in line_lower for kw in _NOISE_KEYWORDS)
            if is_noise and len(stripped) < 150:  # Chắc chắn đó không phải 1 đoạn văn dài
                continue

        cleaned.append(line)

    result = "\n".join(cleaned)
    # Gộp nhiều dòng trắng liên tiếp thành tối ra 2 newline (1 dòng trống)
    result = _RE_MULTI_BLANK.sub("\n\n", result)
    return result.strip()


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class WebSearchInput(BaseModel):
    """Schema đầu vào cho WebSearchTool."""

    query: str = Field(
        description=(
            "Câu truy vấn tìm kiếm văn bản pháp luật Việt Nam. "
            "Nên dùng thuật ngữ chính xác, kèm số hiệu nếu biết. "
            "Ví dụ: 'mức phạt vượt đèn đỏ Nghị định 168/2024/NĐ-CP'."
        )
    )
    num: int = Field(
        default=_DEFAULT_TOP_K,
        ge=1,
        le=_MAX_TOP_K,
        description=f"Số trang cần lấy (1–{_MAX_TOP_K}, mặc định {_DEFAULT_TOP_K}).",
    )


# ---------------------------------------------------------------------------
# Firecrawl scraper
# ---------------------------------------------------------------------------


class _FirecrawlScraper:
    """Wrapper async quanh AsyncV1FirecrawlApp - scrape URL -> Markdown sạch."""

    def __init__(self, api_key: str, timeout: float = _FIRECRAWL_TIMEOUT):
        self._api_key = api_key
        self._timeout = timeout
        self._app = None

    def _ensure_app(self):
        if self._app is None:
            from firecrawl.v1 import AsyncV1FirecrawlApp
            self._app = AsyncV1FirecrawlApp(api_key=self._api_key)

    async def scrape(self, url: str) -> str | None:
        try:
            self._ensure_app()
            
            # Lấy domain để tìm CSS selectors tương ứng
            domain = _domain_of(url)
            include_tags = []
            
            for key, selectors in _DOMAIN_SELECTORS.items():
                if key in domain:
                    include_tags = selectors
                    break

            scrape_args = {
                "url": url,
                "formats": ["markdown"]
            }
            if include_tags:
                scrape_args["include_tags"] = include_tags

            result = await asyncio.wait_for(
                self._app.scrape_url(**scrape_args),
                timeout=self._timeout,
            )

            md = getattr(result, "markdown", None) or ""
            if not md and isinstance(result, dict):
                md = result.get("markdown", "")

            if not md:
                return None

            # Làm sạch Python
            md_clean = _clean_markdown(md)
            return md_clean[:_MAX_CHARS_PER_PAGE] if md_clean else None

        except asyncio.TimeoutError:
            logger.warning(f"[Firecrawl] Timeout ({self._timeout}s): {url}")
            return None
        except Exception as e:
            logger.warning(f"[Firecrawl] Lỗi scraping {url}: {e}")
            return None

    async def scrape_many(self, urls: list[str]) -> list[str | None]:
        """Scrape nhiều URL đồng thời, giới hạn concurrency."""
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SCRAPES)

        async def _bounded(url: str) -> str | None:
            async with semaphore:
                return await self.scrape(url)

        return await asyncio.gather(*[_bounded(u) for u in urls])


# ---------------------------------------------------------------------------
# Serper helpers
# ---------------------------------------------------------------------------


def _build_site_query(query: str, sites: list[str]) -> str:
    """Tạo query với `site:` operator để giới hạn domain."""
    return f"{query} {' OR '.join(f'site:{s}' for s in sites)}"


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


async def _serper_fetch(
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    num: int,
    gl: str,
    hl: str,
) -> list[dict]:
    """Gọi 1 request Serper, trả về danh sách organic results."""
    try:
        response = await client.post(
            _SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": num, "gl": gl, "hl": hl},
            timeout=_SERPER_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("organic", [])
    except Exception as e:
        logger.warning(f"[Serper] Lỗi fetch '{query[:50]}': {e}")
        return []


async def _collect_candidates(
    api_key: str,
    query: str,
    num: int,
    gl: str,
    hl: str,
) -> list[dict]:
    """
    Thu thập URL ứng viên theo chiến lược 2-tier SONG SONG.

    Tier 1 và Tier 2 được gọi ĐỒNG THỜI qua asyncio.gather.
    Sau đó merge: Tier 1 ưu tiên trước, Tier 2 bổ sung nếu thiếu.
    Loại trùng URL giữa 2 tier.

    Mỗi phần tử dict:
        { url, title, snippet, date, tier }
    """
    async with httpx.AsyncClient(timeout=_SERPER_TIMEOUT) as client:
        # ── 2 Tier gọi ĐỒNG THỜI ─────────────────────────────────────
        t1_results, t2_results = await asyncio.gather(
            _serper_fetch(client, api_key, _build_site_query(query, _TIER1_SITES), num, gl, hl),
            _serper_fetch(client, api_key, _build_site_query(query, _TIER2_SITES), num, gl, hl),
        )

    logger.info(
        f"[Serper] Tier1={len(t1_results)} | Tier2={len(t2_results)} | query='{query[:50]}'"
    )

    # ── Merge theo ưu tiên ────────────────────────────────────────────
    seen: set[str] = set()
    candidates: list[dict] = []

    def _add(items: list[dict], tier: int):
        for item in items:
            url = item.get("link", "")
            if not url or url in seen:
                continue
            seen.add(url)
            candidates.append({
                "url":     url,
                "title":   item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "date":    item.get("date", ""),
                "tier":    tier,
            })

    _add(t1_results, 1)  # Tier 1 trước
    _add(t2_results, 2)  # Tier 2 bổ sung

    return candidates[:num]


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def _format_results(candidates: list[dict], scraped: list[str | None]) -> str:
    """
    Ghép URL + Markdown (hoặc snippet fallback) thành chuỗi cho LLM.
    """
    blocks: list[str] = []

    for i, (cand, content) in enumerate(zip(candidates, scraped), start=1):
        tier_label = _TIER_LABEL.get(cand["tier"], "")
        title = cand["title"] or "(Không có tiêu đề)"

        lines = [
            f"{'━' * 3} [{i}] [{tier_label}] {title}",
            f"URL : {cand['url']}",
        ]
        if cand["date"]:
            lines.append(f"Ngày: {cand['date']}")

        if content:
            lines.append(f"Nội dung ({len(content):,} ký tự - Firecrawl):\n")
            lines.append(content)
        else:
            lines.append("Nội dung (Serper snippet):\n")
            lines.append(cand["snippet"] or "(Không có trích đoạn)")

        blocks.append("\n".join(lines))

    sep = "\n\n" + "─" * 60 + "\n\n"
    return sep.join(blocks) if blocks else "Không tìm thấy kết quả phù hợp."


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------


class WebSearchTool(BaseTool):
    """
    LangChain Tool tìm kiếm và cào toàn văn trang pháp luật Việt Nam.

    Pipeline:
      Serper (Tier 1 + Tier 2 song song) -> Firecrawl (song song) -> LLM

    Firecrawl trả về nội dung sạch qua:
      - onlyMainContent=True
      - excludeTags (nav, header, footer, sidebar...)
      - Python post-filter (_clean_markdown)
    """

    name: str = "web_search"
    description: str = (
        "CÔNG CỤ DỰ PHÒNG. CHỈ DÙNG KHI `search_legal_graph` không trả về kết quả hoặc bạn "
        "cần lấy tin tức, chính sách mới nhất, hoặc các Nghị định/Thông tư nằm ngoài "
        "CSDL nội bộ (như Luật khác ngoài giao thông). "
        "Tìm kiếm và cào toàn văn trên các trang: vanban.chinhphu.vn, moj.gov.vn, "
        "quochoi.vn, vbpl.vn, thuvienphapluat.vn, luatvietnam.vn. "
        "Input: câu truy vấn ngắn gọn. Output: trích đoạn hoặc toàn văn từ các bài viết pháp luật."
    )
    args_schema: Type[BaseModel] = WebSearchInput
    return_direct: bool = False

    model_config = {"arbitrary_types_allowed": True}

    serper_api_key: str = Field(description="Serper.dev API key.")
    firecrawl_api_key: str = Field(
        default="",
        description="Firecrawl API key (tuỳ chọn).",
    )
    gl: str = Field(default="vn")
    hl: str = Field(default="vi")

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _scraper(self) -> _FirecrawlScraper | None:
        return _FirecrawlScraper(self.firecrawl_api_key) if self.firecrawl_api_key else None

    async def _execute(self, query: str, num: int) -> str:
        if not self.serper_api_key:
            return "Lỗi: Chưa cấu hình SERPER_API_KEY."

        # Bước 1: Serper tìm URL (2 tier song song)
        candidates = await _collect_candidates(
            api_key=self.serper_api_key,
            query=query,
            num=num,
            gl=self.gl,
            hl=self.hl,
        )

        if not candidates:
            return "Không tìm thấy kết quả từ các nguồn pháp lý."

        # Bước 2: Firecrawl cào nội dung (song song)
        scraper = self._scraper()
        if scraper:
            urls = [c["url"] for c in candidates]
            scraped = await scraper.scrape_many(urls)
            success = sum(1 for s in scraped if s)
            logger.info(
                f"[WebSearch] Firecrawl: {success}/{len(urls)} trang OK | "
                f"query='{query[:50]}'"
            )
        else:
            scraped = [None] * len(candidates)
            logger.info("[WebSearch] Firecrawl chưa cấu hình -> dùng Serper snippet.")

        return _format_results(candidates, scraped)

    # ------------------------------------------------------------------
    # LangChain interface
    # ------------------------------------------------------------------

    def _run(
        self,
        query: str,
        num: int = _DEFAULT_TOP_K,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._execute(query, num))
                return future.result()
        except Exception as e:
            logger.error(f"[WebSearchTool] Lỗi sync: {e}")
            return f"Lỗi khi tìm kiếm: {e}"

    async def _arun(
        self,
        query: str,
        num: int = _DEFAULT_TOP_K,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        try:
            return await self._execute(query, num)
        except httpx.HTTPStatusError as e:
            logger.error(f"[WebSearchTool] HTTP {e.response.status_code}: {e}")
            return f"Lỗi HTTP {e.response.status_code} khi gọi Serper API."
        except httpx.TimeoutException:
            logger.error("[WebSearchTool] Timeout.")
            return "Lỗi: Timeout khi tìm kiếm."
        except Exception as e:
            logger.error(f"[WebSearchTool] Lỗi: {e}")
            return f"Lỗi khi tìm kiếm: {e}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_web_search_tool(
    serper_api_key: str,
    firecrawl_api_key: str = "",
    gl: str = "vn",
    hl: str = "vi",
) -> WebSearchTool:
    """
    Tạo WebSearchTool với pipeline Serper (song song) -> Firecrawl (song song).

    Parameters
    ----------
    serper_api_key    : API key từ https://serper.dev (bắt buộc).
    firecrawl_api_key : API key từ https://firecrawl.dev (tuỳ chọn).
                        Bỏ trống -> chỉ dùng Serper snippet.
    gl : Mã quốc gia (mặc định "vn").
    hl : Ngôn ngữ  (mặc định "vi").
    """
    return WebSearchTool(
        serper_api_key=serper_api_key,
        firecrawl_api_key=firecrawl_api_key,
        gl=gl,
        hl=hl,
    )
