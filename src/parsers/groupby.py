from __future__ import annotations

import json

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from parsers.base import BaseParser, JobPost, canonicalize_url, parse_deadline


class GroupbyParser(BaseParser):
    """그룹바이(groupby.kr) 전용 파서.

    그룹바이는 Next.js 앱이라 공고 데이터가 `__NEXT_DATA__` 스크립트의
    props.pageProps.fallbackDataRaw 에 JSON으로 그대로 들어있다.
    DOM 스크래핑 없이 그 JSON을 읽어 매핑한다 (Gemini 불필요).
    """

    def can_handle(self, url: str) -> bool:
        return "groupby.kr/positions/" in url

    async def parse(self, url: str) -> JobPost:
        canonical = canonicalize_url(url)
        html = await self._fetch_page(canonical)
        return self._extract(html, canonical)

    async def _fetch_page(self, url: str) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.PLAYWRIGHT_HEADLESS)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT)
                await page.wait_for_timeout(2000)
                return await page.content()
            finally:
                await browser.close()

    def _extract(self, html: str, url: str) -> JobPost:
        soup = BeautifulSoup(html, "html.parser")
        post = JobPost(url=url)

        data = self._load_next_data(soup)
        if not data:
            # __NEXT_DATA__ 구조가 바뀌었거나 없으면 빈 post 반환
            # → service.collect()가 Gemini 폴백으로 재시도한다.
            return post

        post.position = (data.get("name") or "").strip()

        startup = data.get("startup") or {}
        post.company = (startup.get("name") or "").strip()
        post.company_description = (startup.get("briefIntro") or "").strip()
        areas = startup.get("serviceAreas") or []
        post.company_type = ", ".join(a for a in areas if a)
        member = startup.get("memberCount")
        if member:
            post.employee_count = f"{member}명"

        post.responsibilities = self._html_to_text(data.get("task", ""))
        post.requirements = self._html_to_text(data.get("qualification", ""))
        post.preferred = self._html_to_text(data.get("preferred", ""))

        # dueDate가 null이면 마감일 미정(상시) → 빈 값으로 둔다.
        due = data.get("dueDate")
        deadline_raw = str(due)[:10] if due else ""
        post.deadline_raw = deadline_raw
        post.deadline_parsed, post.deadline_type = parse_deadline(deadline_raw)

        return post

    def _load_next_data(self, soup: BeautifulSoup) -> dict:
        """__NEXT_DATA__ → props.pageProps.fallbackDataRaw 추출."""
        nd = soup.find("script", id="__NEXT_DATA__")
        if not nd or not nd.string:
            return {}
        try:
            data = json.loads(nd.string)
        except (json.JSONDecodeError, TypeError):
            return {}
        page_props = data.get("props", {}).get("pageProps", {})
        return page_props.get("fallbackDataRaw") or {}

    def _html_to_text(self, html: str) -> str:
        """task/qualification/preferred의 리치텍스트(HTML)를 평문으로 변환."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        return "\n".join(lines)
