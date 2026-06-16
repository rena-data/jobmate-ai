from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from parsers.base import BaseParser, JobPost, canonicalize_url, parse_deadline


class JobkoreaParser(BaseParser):
    """잡코리아(jobkorea.co.kr) 전용 파서.

    GI_Read 공고 페이지는 봇 차단 없이 서버 렌더링된다.
    - 회사/포지션/마감일: <script type="application/ld+json">의 JobPosting 스키마
    - 상세 JD 본문: GI_Read_Comt_Ifrm iframe (사람인의 iframe 추출 패턴과 동일)
    Gemini 불필요.
    """

    def can_handle(self, url: str) -> bool:
        return "jobkorea.co.kr" in url and "GI_Read" in url

    async def parse(self, url: str) -> JobPost:
        canonical = canonicalize_url(url)
        main_html, detail_text = await self._fetch_page(canonical)
        return self._extract(main_html, detail_text, canonical)

    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """메인 HTML + 상세 iframe 본문 텍스트를 가져옴."""
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

                # 상세 JD 본문 iframe (GI_Read_Comt_Ifrm)
                detail_text = ""
                for frame in page.frames:
                    if "GI_Read_Comt_Ifrm" in frame.url:
                        try:
                            fhtml = await frame.content()
                            fsoup = BeautifulSoup(fhtml, "html.parser")
                            for tag in fsoup.find_all(["script", "style"]):
                                tag.decompose()
                            detail_text = fsoup.get_text("\n", strip=True)
                        except Exception:
                            pass
                        break

                return main_html, detail_text
            finally:
                await browser.close()

    def _extract(self, main_html: str, detail_text: str, url: str) -> JobPost:
        soup = BeautifulSoup(main_html, "html.parser")
        post = JobPost(url=url)

        ld = self._load_jobposting(soup)
        post.position = (ld.get("title") or "").strip()
        org = ld.get("hiringOrganization") or {}
        if isinstance(org, dict):
            post.company = (org.get("name") or "").strip()
        post.company_description = (ld.get("description") or "").strip()

        # 마감일: validThrough "2026-07-15T23:59" → 날짜 부분만
        valid = ld.get("validThrough") or ""
        deadline_raw = str(valid)[:10] if valid else ""
        post.deadline_raw = deadline_raw
        post.deadline_parsed, post.deadline_type = parse_deadline(deadline_raw)

        # JD 본문 → 섹션 분리 시도, 실패 시 통째로 주요업무에 담음
        if detail_text:
            sections = self._split_sections(detail_text)
            post.responsibilities = sections.get("responsibilities", "") or detail_text[:3000]
            post.requirements = sections.get("requirements", "")
            post.preferred = sections.get("preferred", "")

        # 업종/직원수 best-effort (메인 페이지 평문)
        main_text = soup.get_text("\n", strip=True)
        m = re.search(r"업종[\s:：]+(.+?)(?:\n|$)", main_text)
        if m and 0 < len(m.group(1).strip()) < 50:
            post.company_type = m.group(1).strip()
        emp = re.search(r"(?:사원수|임직원|직원수)[\s:：]*(\d[\d,]*)\s*명", main_text)
        if emp:
            post.employee_count = f"{emp.group(1)}명"

        return post

    def _load_jobposting(self, soup: BeautifulSoup) -> dict:
        """ld+json 블록 중 @type == JobPosting 추출."""
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                obj = json.loads(s.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
                return obj
        return {}

    def _split_sections(self, text: str) -> dict[str, str]:
        """자유형식 JD에서 주요업무/자격요건/우대사항 라벨 기반 분리(베스트에포트)."""
        patterns = {
            "responsibilities": r"(?:주요\s*업무|담당\s*업무|업무\s*내용|모집\s*분야|하는\s*일)[\s:：]*([\s\S]*?)(?=자격\s*요건|지원\s*자격|지원\s*요건|우대|근무\s*조건|복지|혜택|접수|전형|$)",
            "requirements": r"(?:자격\s*요건|지원\s*자격|지원\s*요건|필수\s*요건)[\s:：]*([\s\S]*?)(?=우대|근무\s*조건|복지|혜택|접수|전형|주요\s*업무|$)",
            "preferred": r"(?:우대\s*사항|우대\s*조건)[\s:：]*([\s\S]*?)(?=근무\s*조건|복지|혜택|접수|전형|$)",
        }
        out: dict[str, str] = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                content = m.group(1).strip()[:2000]
                if len(content) > 10:
                    out[key] = content
        return out
