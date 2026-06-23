from __future__ import annotations

import re
from abc import ABC, abstractmethod
from urllib.parse import urljoin

import config

# 파서들과 동일한 브라우저 지문 (parsers/*._fetch_page와 일치)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 800}


async def open_search_page(p):
    """공용 Playwright 브라우저/페이지 생성 (파서들과 동일 설정).

    config.PLAYWRIGHT_HEADLESS를 그대로 사용하므로 사람인의 headless=False 요구도
    자동으로 충족된다. (browser, page) 반환 — 호출자가 finally에서 browser.close().
    """
    browser = await p.chromium.launch(headless=config.PLAYWRIGHT_HEADLESS)
    context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
    page = await context.new_page()
    return browser, page


async def collect_hrefs(page) -> list[str]:
    """현재 페이지의 모든 <a> href를 수집 (상대/절대 혼재).

    컨테이너 클래스명이 자주 바뀌는 사이트(사람인 등) 대비, 좁은 셀렉터 대신
    전체 앵커를 긁고 extract_detail_urls의 정규식으로 상세 URL만 거른다.
    """
    return await page.eval_on_selector_all(
        "a", "els => els.map(e => e.getAttribute('href'))"
    )


def extract_detail_urls(
    hrefs: list[str | None],
    *,
    id_pattern: str,
    url_template: str,
    limit: int,
    base_url: str = "",
) -> list[str]:
    """검색 결과 href 목록에서 개별 상세 URL을 추출·정규화·중복제거한다 (순수 함수).

    id_pattern: 캡처그룹 1이 공고 id인 정규식 (예: r"/Recruit/GI_Read/(\\d+)").
    url_template: "...{id}..." 형식의 정규화 템플릿 (검색 결과의 추적 파라미터 제거 효과).
    base_url: 상대 href를 절대 URL로 만들 기준 (urljoin).
    같은 id는 한 번만, 등장 순서를 보존하며 최대 limit개 반환.
    """
    rx = re.compile(id_pattern)
    seen: set[str] = set()
    out: list[str] = []
    for h in hrefs:
        if not h:
            continue
        absolute = urljoin(base_url, h) if base_url else h
        m = rx.search(absolute)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)
        out.append(url_template.format(id=job_id))
        if len(out) >= limit:
            break
    return out


class BaseSearcher(ABC):
    """검색기 인터페이스. 키워드 → 개별 상세 URL 리스트."""

    platform_name: str = ""

    def can_search(self, platform: str) -> bool:
        """이 검색기가 해당 플랫폼명을 담당하는지 (service._PLATFORMS의 한글명)."""
        return platform == self.platform_name

    @abstractmethod
    async def search(self, keyword: str, limit: int) -> list[str]:
        """keyword로 플랫폼을 검색해 최대 limit개의 정규화된 상세 URL을 반환."""
        ...
