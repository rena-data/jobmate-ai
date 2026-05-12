from __future__ import annotations

import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from parsers.base import BaseParser, JobPost, canonicalize_url, parse_deadline


class SaraminParser(BaseParser):
    """사람인(saramin.co.kr) 전용 파서."""

    def can_handle(self, url: str) -> bool:
        return "saramin.co.kr" in url and ("rec_idx" in url or "jobs/relay" in url)

    async def parse(self, url: str) -> JobPost:
        canonical = canonicalize_url(url)
        main_html, detail_html = await self._fetch_page(canonical)
        return self._extract(main_html, detail_html, canonical)

    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """메인 페이지 + iframe 상세 페이지를 모두 가져옴."""
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
                await page.wait_for_timeout(3000)

                main_html = await page.content()

                # 사람인은 상세 내용이 iframe 안에 있음
                detail_html = ""
                for frame in page.frames:
                    if "view-detail" in frame.url:
                        try:
                            detail_html = await frame.content()
                            break
                        except Exception:
                            pass

                return main_html, detail_html
            finally:
                await browser.close()

    def _extract(self, main_html: str, detail_html: str, url: str) -> JobPost:
        main_soup = BeautifulSoup(main_html, "html.parser")
        detail_soup = BeautifulSoup(detail_html, "html.parser") if detail_html else None

        post = JobPost(url=url)

        # 회사명 (메인 페이지)
        post.company = self._extract_text(main_soup, [
            ".company_name a",
            ".company_name",
        ])

        # 포지션 (메인 페이지)
        post.position = self._extract_text(main_soup, [
            "h1.tit_job",
            ".job_tit .tit",
            "h1",
        ])

        # 상단 요약 정보 (경력, 학력, 근무지역 등)
        summary = self._extract_summary(main_soup)
        post.company_description = summary.get("location", "")

        # 마감일 (메인 페이지)
        deadline_raw = self._extract_deadline(main_soup)
        post.deadline_raw = deadline_raw
        post.deadline_parsed, post.deadline_type = parse_deadline(deadline_raw)

        # 상세 내용 (iframe)
        if detail_soup:
            detail_text = detail_soup.get_text("\n", strip=True)
            sections = self._extract_sections_from_text(detail_text)
            post.responsibilities = sections.get("responsibilities", "")
            post.requirements = sections.get("requirements", "")
            post.preferred = sections.get("preferred", "")

            # 업종 (iframe 상세에서)
            post.company_type = self._extract_industry(detail_soup, detail_text)

            # 직원수
            emp_match = re.search(r"(\d{1,5})\s*명", detail_text)
            if emp_match:
                post.employee_count = emp_match.group(0).strip()

        return post

    def _extract_text(self, soup: BeautifulSoup, selectors: list[str]) -> str:
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text and len(text) < 200:
                    return text
        return ""

    def _extract_summary(self, soup: BeautifulSoup) -> dict[str, str]:
        """상단 요약 영역에서 근무지역 등 추출."""
        info: dict[str, str] = {"location": ""}
        cols = soup.select(".col")
        for col in cols:
            text = col.get_text(" ", strip=True)
            if "근무지역" in text:
                # "근무지역 서울 강남구" 형태
                location = text.replace("근무지역", "").strip()
                # "지도보기" 등 제거
                location = re.sub(r"지도보기.*", "", location).strip()
                info["location"] = location
        return info

    def _extract_deadline(self, soup: BeautifulSoup) -> str:
        """접수기간에서 마감일 추출."""
        period = soup.select_one(".info_period")
        if period:
            text = period.get_text(" ", strip=True)
            # "마감일 2026.05.24 23:59" 패턴
            m = re.search(r"마감일\s*(\d{4}\.\d{2}\.\d{2})", text)
            if m:
                return m.group(1)
            # 상시채용 패턴
            if "상시" in text or "채용시" in text:
                return "상시채용"

        # 전체 텍스트에서 폴백
        text = soup.get_text()
        if re.search(r"상시\s*채용|채용\s*시\s*마감", text):
            return "상시채용"

        return ""

    def _extract_sections_from_text(self, text: str) -> dict[str, str]:
        """상세 텍스트에서 주요업무/자격요건/우대사항 추출."""
        sections: dict[str, str] = {}

        patterns = {
            "responsibilities": [
                r"(?:이런\s*일|주요\s*업무|담당\s*업무|업무\s*내용|하는\s*일)[을를\s]*합니다[.\s]*([\s\S]*?)(?=자격|우대|필수|이런\s*분|경력|학력|근무|혜택|복지|접수|지원|$)",
                r"(?:주요\s*업무|담당\s*업무|업무\s*내용|What you)[\s:：]*([\s\S]*?)(?=자격|우대|필수|이런\s*분|경력|학력|근무|혜택|복지|접수|지원|$)",
            ],
            "requirements": [
                r"(?:자격\s*요건|필수\s*조건|지원\s*자격|이런\s*분을?\s*찾|필요\s*역량|Requirements)[\s:：]*([\s\S]*?)(?=우대|혜택|복지|근무|접수|지원|Preferred|$)",
            ],
            "preferred": [
                r"(?:우대\s*사항|우대\s*조건|이런\s*분이면?\s*더|Preferred)[\s:：]*([\s\S]*?)(?=혜택|복지|근무|접수|지원|전형|채용|Benefits|$)",
            ],
        }

        for key, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    content = m.group(1).strip()[:2000]
                    if len(content) > 10:
                        sections[key] = content
                        break

        return sections

    def _extract_industry(self, soup: BeautifulSoup, text: str) -> str:
        """업종 추출."""
        # "업종" 라벨 다음의 값
        m = re.search(r"업종\s+(.+?)(?:\n|직종|$)", text)
        if m:
            industry = m.group(1).strip()
            # ">" 구분자 정리
            if ">" in industry:
                parts = [p.strip() for p in industry.split(">")]
                return parts[-1] if parts else industry
            return industry[:50]
        return ""
