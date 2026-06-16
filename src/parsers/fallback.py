from __future__ import annotations

import json
import re
import time

from google import genai
from google.genai import errors as genai_errors
import trafilatura
from playwright.async_api import async_playwright
from rich.console import Console

import config
from parsers.base import BaseParser, JobPost, canonicalize_url, parse_deadline

console = Console()


class FallbackParser(BaseParser):
    """Gemini API를 사용한 범용 폴백 파서."""

    def can_handle(self, url: str) -> bool:
        # 모든 URL 처리 가능 (폴백이므로)
        return True

    async def parse(self, url: str) -> JobPost:
        canonical = canonicalize_url(url)
        html = await self._fetch_page(canonical)
        main_text = self._extract_main_content(html)
        data = self._extract_with_gemini(main_text)
        return self._build_job_post(data, canonical)

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
                return await page.content()
            finally:
                await browser.close()

    def _extract_main_content(self, html: str) -> str:
        """trafilatura + BeautifulSoup 병행으로 본문 추출."""
        from bs4 import BeautifulSoup

        # HTTP 에러 페이지 감지
        if len(html) < 2000:
            lower = html.lower()
            if any(kw in lower for kw in ["403", "404", "forbidden", "not found", "request blocked", "access denied"]):
                raise RuntimeError("페이지 접근이 차단되었습니다 (403/봇 감지). 해당 사이트는 자동 수집을 지원하지 않습니다.")

        # 1) trafilatura 시도
        traf_text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""

        # 2) BeautifulSoup 타겟 추출 (채용 공고 본문 영역)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        # 채용 상세 영역 우선 탐색
        content_selectors = [
            "[class*='job-detail']", "[class*='jobDetail']", "[class*='JobDetail']",
            "[class*='recruit']", "[class*='Recruit']",
            "[class*='posting']", "[class*='Posting']",
            "[class*='description']", "[class*='Description']",
            "article", "main", "[role='main']",
        ]
        bs4_text = ""
        for sel in content_selectors:
            el = soup.select_one(sel)
            if el:
                candidate = el.get_text("\n", strip=True)
                if len(candidate) > len(bs4_text):
                    bs4_text = candidate

        # 타겟 선택자 실패 시 전체 본문
        if len(bs4_text) < 200:
            bs4_text = soup.get_text("\n", strip=True)

        # 더 긴 결과 채택
        text = traf_text if len(traf_text) >= len(bs4_text) else bs4_text
        return text[:8000]

    def _extract_with_gemini(self, text: str) -> dict:
        """Gemini API로 구조화된 데이터 추출."""
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        prompt = f"""아래는 채용 공고 페이지의 본문 텍스트입니다.
다음 정보를 JSON 형식으로 추출해주세요. 없는 정보는 빈 문자열로 채워주세요.
설명이나 부가 텍스트 없이 JSON만 출력하세요.

필수 JSON 구조:
{{
  "company": "회사명",
  "company_type": "업종 (예: IT, 광고대행사, 도소매, SaaS 등)",
  "employee_count": "직원 수",
  "company_description": "회사 한 줄 설명",
  "position": "채용 포지션명",
  "responsibilities": "주요 업무 내용",
  "requirements": "자격 요건",
  "preferred": "우대 사항",
  "deadline": "마감일 (원본 텍스트 그대로)"
}}

채용 공고 본문:
{text}"""

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                )
                return self._parse_json_response(response.text)
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    if attempt < max_retries:
                        wait = 30 * (attempt + 1)
                        console.print(f"[yellow]Gemini API 한도 초과. {wait}초 후 재시도... ({attempt + 1}/{max_retries})[/yellow]")
                        time.sleep(wait)
                    else:
                        raise RuntimeError(
                            "Gemini API 일일 무료 한도를 초과했습니다. "
                            "잠시 후 다시 시도하거나, Google AI Studio에서 새 API 키를 발급해주세요."
                        )
                else:
                    raise

    def _parse_json_response(self, text: str) -> dict:
        """Gemini 응답에서 JSON 추출."""
        # markdown 코드 블록 제거
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # JSON 부분만 추출 시도
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    def _build_job_post(self, data: dict, url: str) -> JobPost:
        deadline_raw = data.get("deadline", "")
        deadline_parsed, deadline_type = parse_deadline(deadline_raw)

        return JobPost(
            url=url,
            company=data.get("company", ""),
            company_type=data.get("company_type", ""),
            employee_count=data.get("employee_count", ""),
            company_description=data.get("company_description", ""),
            position=data.get("position", ""),
            responsibilities=data.get("responsibilities", ""),
            requirements=data.get("requirements", ""),
            preferred=data.get("preferred", ""),
            deadline_raw=deadline_raw,
            deadline_parsed=deadline_parsed,
            deadline_type=deadline_type,
        )
