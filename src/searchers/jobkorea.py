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


class JobkoreaSearcher(BaseSearcher):
    """잡코리아(jobkorea.co.kr) 키워드 검색.

    검색 결과가 서버 렌더링되어 봇 차단/JS 이슈가 적다 → 가장 안정적.
    상세 링크는 /Recruit/GI_Read/{id} 형태이며 JobkoreaParser.can_handle과 일치.
    """

    platform_name = "잡코리아"
    BASE = "https://www.jobkorea.co.kr"
    ID_PATTERN = r"/Recruit/GI_Read/(\d+)"
    URL_TEMPLATE = "https://www.jobkorea.co.kr/Recruit/GI_Read/{id}"
    MAX_PAGES = 5

    async def search(self, keyword: str, limit: int) -> list[str]:
        hrefs: list[str | None] = []
        async with async_playwright() as p:
            browser, page = await open_search_page(p)
            try:
                for page_no in range(1, self.MAX_PAGES + 1):
                    url = f"{self.BASE}/Search/?stext={quote(keyword)}&Page_No={page_no}"
                    await page.goto(
                        url, wait_until="domcontentloaded",
                        timeout=config.PAGE_LOAD_TIMEOUT,
                    )
                    await page.wait_for_timeout(2000)

                    before = len(self._matches(hrefs, limit))
                    hrefs.extend(await collect_hrefs(page))
                    after = len(self._matches(hrefs, limit))
                    # 목표 수량 달성 또는 더 이상 새 결과 없음 → 중단
                    if after >= limit or after == before:
                        break
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
