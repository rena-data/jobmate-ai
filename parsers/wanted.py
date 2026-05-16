from __future__ import annotations

import asyncio
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from parsers.base import BaseParser, JobPost, canonicalize_url, parse_deadline


class WantedParser(BaseParser):
    """원티드(wanted.co.kr) 전용 파서."""

    def can_handle(self, url: str) -> bool:
        return "wanted.co.kr/wd/" in url or "wanted.co.kr/jobpost/" in url

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
                await page.wait_for_timeout(3000)

                # 상세 정보가 접혀있을 수 있으므로 "더 보기" 버튼 클릭 시도
                try:
                    more_btn = page.locator("button:has-text('상세 정보 더 보기'), button:has-text('더 보기')")
                    if await more_btn.count() > 0:
                        await more_btn.first.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                return await page.content()
            finally:
                await browser.close()

    def _extract(self, html: str, url: str) -> JobPost:
        soup = BeautifulSoup(html, "html.parser")
        post = JobPost(url=url)

        # 회사명
        post.company = self._extract_company(soup)

        # 포지션 (제목)
        post.position = self._extract_position(soup)

        # 섹션별 추출 (주요업무, 자격요건, 우대사항 등)
        sections = self._extract_sections(soup)
        post.responsibilities = sections.get("주요업무", "")
        post.requirements = sections.get("자격요건", "")
        post.preferred = sections.get("우대사항", "")

        # 회사 정보
        company_info = self._extract_company_info(soup)
        post.company_type = company_info.get("industry", "")
        post.employee_count = company_info.get("employee_count", "")
        post.company_description = company_info.get("description", "")

        # 마감일
        deadline_raw = self._extract_deadline(soup)
        post.deadline_raw = deadline_raw
        post.deadline_parsed, post.deadline_type = parse_deadline(deadline_raw)

        return post

    def _extract_company(self, soup: BeautifulSoup) -> str:
        # 원티드의 회사명은 보통 헤더 영역에 있음
        # 여러 선택자 시도
        selectors = [
            "a[data-attribute='company-name']",
            "header a[href*='/company/']",
            ".JobHeader_className__HttDA a",
            "[class*='CompanyName'] a",
            "[class*='company-name']",
            "[class*='companyName']",
        ]
        for sel in selectors:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                return tag.get_text(strip=True)

        # 폴백: 링크 중 /company/ 경로를 가진 것
        for a in soup.find_all("a", href=True):
            if "/company/" in a["href"]:
                text = a.get_text(strip=True)
                if text and len(text) < 50:
                    return text

        return ""

    def _extract_position(self, soup: BeautifulSoup) -> str:
        selectors = [
            "h1",
            "h2[class*='JobHeader']",
            "[class*='position']",
            "[class*='title'] h1",
            "[class*='Title'] h1",
        ]
        for sel in selectors:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                text = tag.get_text(strip=True)
                if len(text) < 200:
                    return text
        return ""

    def _extract_sections(self, soup: BeautifulSoup) -> dict[str, str]:
        """원티드 공고의 섹션별 콘텐츠 추출."""
        sections: dict[str, str] = {}

        section_keywords = {
            "주요업무": ["주요업무", "주요 업무", "담당업무", "담당 업무", "업무 내용", "업무내용", "What you'll do"],
            "자격요건": ["자격요건", "자격 요건", "필수 조건", "필수조건", "지원자격", "Requirements"],
            "우대사항": ["우대사항", "우대 사항", "우대조건", "우대 조건", "Preferred"],
            "혜택및복지": ["혜택 및 복지", "혜택및복지", "복리후생", "Benefits"],
        }

        # h6, h3, strong 등 섹션 헤더 탐색
        header_tags = soup.find_all(["h6", "h5", "h4", "h3", "strong", "b"])

        for header in header_tags:
            header_text = header.get_text(strip=True)
            matched_key = None

            for key, keywords in section_keywords.items():
                for kw in keywords:
                    if kw in header_text:
                        matched_key = key
                        break
                if matched_key:
                    break

            if not matched_key:
                continue

            # 다음 형제 요소에서 콘텐츠 수집
            content_parts = []
            sibling = header.find_next_sibling()
            while sibling:
                # 다음 섹션 헤더를 만나면 중단
                if sibling.name in ["h6", "h5", "h4", "h3"] or (
                    sibling.name in ["strong", "b"] and any(
                        kw in sibling.get_text(strip=True)
                        for keywords in section_keywords.values()
                        for kw in keywords
                    )
                ):
                    break
                text = sibling.get_text(strip=True)
                if text:
                    content_parts.append(text)
                sibling = sibling.find_next_sibling()

            if not content_parts:
                # 부모 요소의 다음 형제에서 시도
                parent = header.parent
                if parent:
                    sibling = parent.find_next_sibling()
                    while sibling:
                        if sibling.name in ["h6", "h5", "h4", "h3"]:
                            break
                        text = sibling.get_text("\n", strip=True)
                        if text:
                            content_parts.append(text)
                            break
                        sibling = sibling.find_next_sibling()

            if content_parts:
                sections[matched_key] = "\n".join(content_parts)

        # 섹션 헤더를 못 찾은 경우 전체 본문에서 패턴 매칭 시도
        if not sections:
            body_text = soup.get_text()
            for key, keywords in section_keywords.items():
                for kw in keywords:
                    pattern = rf"{kw}\s*\n([\s\S]*?)(?=(?:{'|'.join(k for kws in section_keywords.values() for k in kws)})|$)"
                    match = re.search(pattern, body_text)
                    if match:
                        sections[key] = match.group(1).strip()[:2000]
                        break

        return sections

    def _extract_company_info(self, soup: BeautifulSoup) -> dict[str, str]:
        """회사 정보 (업종, 직원수, 설명) 추출."""
        info: dict[str, str] = {
            "industry": "",
            "employee_count": "",
            "description": "",
        }

        text = soup.get_text()

        # 업종 추출 - 원티드 태그/카테고리 영역
        # 원티드는 회사 정보 영역에 "IT, 컨텐츠" 같은 업종 태그를 표시
        industry_patterns = [
            r"산업\s*[:：]?\s*(.+?)(?:\n|$)",
            r"업종\s*[:：]?\s*(.+?)(?:\n|$)",
        ]
        for pat in industry_patterns:
            m = re.search(pat, text)
            if m:
                candidate = m.group(1).strip()
                if 0 < len(candidate) < 50:
                    info["industry"] = candidate
                    break

        # 태그 영역에서 업종 추출 시도
        if not info["industry"]:
            tag_selectors = [
                "[class*='Tag']", "[class*='tag']",
                "[class*='category']", "[class*='Category']",
                "[class*='industry']", "[class*='Industry']",
            ]
            for sel in tag_selectors:
                tags = soup.select(sel)
                for tag in tags:
                    tag_text = tag.get_text(strip=True)
                    # 짧은 태그 중 업종 키워드 포함
                    if 2 < len(tag_text) < 30 and any(kw in tag_text for kw in [
                        "IT", "금융", "커머스", "교육", "헬스", "미디어", "게임",
                        "핀테크", "SaaS", "플랫폼", "콘텐츠", "광고", "엔터",
                        "물류", "제조", "유통", "바이오", "소프트웨어",
                    ]):
                        info["industry"] = tag_text
                        break
                if info["industry"]:
                    break

        # 회사 링크 근처의 메타 정보에서 업종 추출 (예: "회사명∙IT, 컨텐츠∙서울")
        if not info["industry"]:
            for a in soup.find_all("a", href=True):
                if "/company/" in a["href"]:
                    parent = a.parent
                    if parent:
                        meta_text = parent.get_text("∙", strip=True)
                        parts = [p.strip() for p in meta_text.split("∙")]
                        for part in parts:
                            if 2 < len(part) < 30 and part != info.get("_company", ""):
                                # 회사명/위치가 아닌 중간 파트가 업종일 가능성
                                if any(kw in part for kw in [
                                    "IT", "금융", "서비스", "테크", "소프트", "미디어",
                                    "커머스", "플랫폼", "콘텐츠", "게임", "엔터",
                                ]):
                                    info["industry"] = part
                                    break
                    break

        # 직원수 패턴 - "300명" 같은 패턴 찾되 전화번호 등 제외
        emp_patterns = [
            r"(\d{1,5})\s*명",
        ]
        for pat in emp_patterns:
            m = re.search(pat, text)
            if m:
                info["employee_count"] = m.group(0).strip()
                break

        # 회사 설명 - company 링크 근처의 설명 텍스트 추출
        for a in soup.find_all("a", href=True):
            if "/company/" in a["href"]:
                # 회사 링크의 상위 섹션에서 설명 찾기
                parent = a
                for _ in range(5):
                    parent = parent.parent
                    if parent is None:
                        break
                if parent:
                    section_text = parent.get_text("\n", strip=True)
                    lines = [l.strip() for l in section_text.split("\n") if l.strip()]
                    for line in lines[1:]:
                        if len(line) > 30 and "주요업무" not in line:
                            info["description"] = line[:300]
                            break
                break

        return info

    def _extract_deadline(self, soup: BeautifulSoup) -> str:
        """마감일 추출."""
        text = soup.get_text()

        # 1. "D-12" 형태 (원티드 제목 옆에 표시)
        d_match = re.search(r"\(D-(\d+)\)", text)
        if d_match:
            from datetime import date, timedelta
            days_left = int(d_match.group(1))
            deadline = date.today() + timedelta(days=days_left)
            return deadline.strftime("%Y-%m-%d")

        # 2. 날짜 형태 마감일
        patterns = [
            r"마감일?\s*[:：]?\s*(.+?)(?:\n|$)",
            r"접수\s*기간?\s*[:：]?\s*(.+?)(?:\n|$)",
            r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:까지|마감)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                result = m.group(1).strip()
                if len(result) < 50 and result not in ("없음", ""):
                    return result

        # 3. "상시채용" 패턴
        if re.search(r"상시\s*채용|수시\s*채용|채용\s*시\s*마감", text):
            return "상시채용"

        # 4. "해당 포지션은 마감되었습니다" 패턴
        if re.search(r"마감되었습니다|지원마감", text):
            return "마감됨"

        return ""
