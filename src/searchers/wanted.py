from __future__ import annotations

from urllib.parse import quote

from playwright.async_api import async_playwright

import config
from searchers.base import (
    BaseSearcher,
    collect_hrefs,
    extract_detail_urls,
    open_search_page,
)


class WantedSearcher(BaseSearcher):
    """원티드(wanted.co.kr) 키워드 검색.

    검색 결과가 SPA + 무한 스크롤이라 Playwright로 스크롤하며 /wd/{id} 링크를
    수집한다. 상세 링크 형태는 WantedParser.can_handle과 일치.
    """

    platform_name = "원티드"
    BASE = "https://www.wanted.co.kr"
    ID_PATTERN = r"/wd/(\d+)"
    URL_TEMPLATE = "https://www.wanted.co.kr/wd/{id}"
    MAX_SCROLLS = 6

    async def search(self, keyword: str, limit: int) -> list[str]:
        hrefs: list[str | None] = []
        async with async_playwright() as p:
            browser, page = await open_search_page(p)
            try:
                url = f"{self.BASE}/search?query={quote(keyword)}&tab=position"
                await page.goto(
                    url, wait_until="domcontentloaded",
                    timeout=config.PAGE_LOAD_TIMEOUT,
                )
                await page.wait_for_timeout(3000)

                for _ in range(self.MAX_SCROLLS):
                    hrefs = await collect_hrefs(page)
                    if len(self._matches(hrefs, limit)) >= limit:
                        break
                    await page.mouse.wheel(0, 3000)
                    await page.wait_for_timeout(1500)

                hrefs = await collect_hrefs(page)
            finally:
                await browser.close()
        return self._matches(hrefs, limit)

    def _matches(self, hrefs: list[str | None], limit: int) -> list[str]:
        return extract_detail_urls(
            hrefs,
            id_pattern=self.ID_PATTERN,
            url_template=self.URL_TEMPLATE,
            limit=limit,
            base_url=self.BASE,
        )
