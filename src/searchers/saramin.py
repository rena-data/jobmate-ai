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


class SaraminSearcher(BaseSearcher):
    """사람인(saramin.co.kr) 키워드 검색.

    봇 감지로 headless=False가 필수(config.PLAYWRIGHT_HEADLESS=False로 충족).
    결과가 JS로 채워지므로 렌더 대기 후 앵커를 긁는다. 상세 링크는 rec_idx=
    파라미터를 가지며 SaraminParser.can_handle과 일치.
    """

    platform_name = "사람인"
    BASE = "https://www.saramin.co.kr"
    ID_PATTERN = r"rec_idx=(\d+)"
    URL_TEMPLATE = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={id}"
    MAX_PAGES = 5

    async def search(self, keyword: str, limit: int) -> list[str]:
        hrefs: list[str | None] = []
        async with async_playwright() as p:
            browser, page = await open_search_page(p)
            try:
                for page_no in range(1, self.MAX_PAGES + 1):
                    url = (
                        f"{self.BASE}/zf_user/search/recruit"
                        f"?searchType=search&searchword={quote(keyword)}"
                        f"&recruitPage={page_no}"
                    )
                    await page.goto(
                        url, wait_until="domcontentloaded",
                        timeout=config.PAGE_LOAD_TIMEOUT,
                    )
                    await page.wait_for_timeout(3000)

                    before = len(self._matches(hrefs, limit))
                    hrefs.extend(await collect_hrefs(page))
                    after = len(self._matches(hrefs, limit))
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
