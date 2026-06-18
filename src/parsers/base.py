from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional
from urllib.parse import urlparse, urlencode, parse_qs
from urllib.robotparser import RobotFileParser

import requests


class DeadlineType(str, Enum):
    FIXED = "fixed"       # 확정 마감일
    ROLLING = "rolling"   # 상시채용 / 채용시 마감
    UNKNOWN = "unknown"   # 파싱 실패


@dataclass
class JobPost:
    url: str
    company: str = ""
    company_type: str = ""       # 업종 (광고대행사, SaaS 등)
    employee_count: str = ""
    company_description: str = ""
    position: str = ""
    responsibilities: str = ""   # 주요 업무
    requirements: str = ""       # 자격 요건
    preferred: str = ""          # 우대 사항
    deadline_raw: str = ""       # 원본 마감일 텍스트
    deadline_parsed: Optional[str] = None  # YYYY-MM-DD
    deadline_type: DeadlineType = DeadlineType.UNKNOWN
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    status: str = "interest"     # interest / applied / interview / closed
    memo: str = ""

    def to_sheet_row(self) -> list[str]:
        """Google Sheets 행 데이터로 변환."""
        return [
            self.url,
            self.company,
            self.company_type,
            self.employee_count,
            self.company_description,
            self.position,
            self.responsibilities,
            self.requirements,
            self.preferred,
            self.deadline_raw,
            self.deadline_parsed or "",
            self.deadline_type.value,
            self.created_at,
            self.status,
            self.memo,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "URL", "회사명", "업종", "직원수", "회사설명",
            "포지션", "주요업무", "자격요건", "우대사항",
            "마감일(원본)", "마감일(파싱)", "마감유형",
            "등록일", "상태", "비고",
        ]


def canonicalize_url(url: str) -> str:
    """URL에서 추적 파라미터 제거하여 정규화."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # 추적/불필요 파라미터 제거
    remove_keys = {
        "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
        "fbclid", "gclid", "ref", "referer",
    }
    cleaned = {k: v for k, v in params.items() if k not in remove_keys}

    clean_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return parsed._replace(query=clean_query, fragment="").geturl()


def parse_deadline(raw: str) -> tuple[Optional[str], DeadlineType]:
    """마감일 원본 텍스트를 파싱하여 (YYYY-MM-DD, 유형) 반환."""
    if not raw:
        return None, DeadlineType.UNKNOWN

    raw_stripped = raw.strip()

    # 상시채용 패턴
    rolling_keywords = ["상시", "채용시", "채용 시", "수시", "영입"]
    for kw in rolling_keywords:
        if kw in raw_stripped:
            return None, DeadlineType.ROLLING

    # 날짜 파싱 시도 (다양한 포맷)
    formats = [
        "%Y-%m-%d",
        "%Y.%m.%d",
        "%Y/%m/%d",
        "%Y년 %m월 %d일",
        "%m/%d",
        "%m.%d",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(raw_stripped, fmt)
            # 연도 없는 포맷이면 현재 연도 적용
            if parsed.year == 1900:
                parsed = parsed.replace(year=date.today().year)
            return parsed.strftime("%Y-%m-%d"), DeadlineType.FIXED
        except ValueError:
            continue

    # 괄호 안 요일 제거 후 재시도 (예: "2026.05.31(금)")
    import re
    cleaned = re.sub(r"\([^)]*\)", "", raw_stripped).strip()
    if cleaned != raw_stripped:
        return parse_deadline(cleaned)

    return None, DeadlineType.UNKNOWN


def check_robots_txt(url: str) -> tuple[bool, str]:
    """robots.txt를 확인하여 해당 URL 접근이 허용되는지 체크.

    Returns:
        (허용 여부, 상태 메시지)
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        resp = requests.get(robots_url, timeout=5, headers={
            "User-Agent": "Mozilla/5.0"
        })

        # robots.txt가 없거나 접근 불가능하면 허용으로 간주
        if resp.status_code != 200:
            return True, f"robots.txt 없음/접근불가 (HTTP {resp.status_code})"

        # 실제 robots.txt 내용인지 확인 (HTML 에러 페이지 제외)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            return True, "robots.txt가 HTML 에러 페이지 (무시)"

        rp = RobotFileParser()
        rp.parse(resp.text.splitlines())
        allowed = rp.can_fetch("*", url)
        return allowed, "허용" if allowed else "차단됨"
    except Exception as e:
        return True, f"robots.txt 확인 실패: {e} (허용으로 간주)"


class BaseParser(ABC):
    """파서 인터페이스. 모든 사이트별 파서는 이것을 상속."""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """이 파서가 해당 URL을 처리할 수 있는지 판단."""
        ...

    @abstractmethod
    async def parse(self, url: str) -> JobPost:
        """URL에서 채용 공고 데이터를 추출하여 JobPost 반환."""
        ...
