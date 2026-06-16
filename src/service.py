"""UI-비종속 공통 로직 레이어.

CLI(main.py)와 웹(app.py)이 동일한 로직을 공유한다.
인쇄/확인/스피너는 호출자(UI)가 담당하고, 이 모듈은 결과를 데이터로만 반환한다.
파싱 로직은 기존 parsers/*, sheets.py, slack.py를 그대로 사용한다 (변경 없음).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date

import config
from parsers.base import (
    JobPost,
    DeadlineType,
    canonicalize_url,
    check_robots_txt,
    parse_deadline,
)
from parsers.wanted import WantedParser
from parsers.saramin import SaraminParser
from parsers.jobkorea import JobkoreaParser
from parsers.groupby import GroupbyParser
from parsers.fallback import FallbackParser
import sheets
import slack


# 파서 등록 (우선순위 순) — 두 UI가 공유 (기존 main.py:39-43)
PARSERS = [
    WantedParser(),
    SaraminParser(),
    JobkoreaParser(),
    GroupbyParser(),
    FallbackParser(),  # 항상 마지막 (폴백)
]

# 상태 값 재노출 (sheets.VALID_STATUSES와 동일)
VALID_STATUSES = sheets.VALID_STATUSES


@dataclass
class CollectResult:
    """collect()의 결과. 인쇄/예외 없이 상황을 필드로 표현한다."""

    post: JobPost | None = None
    canonical_url: str = ""
    already_cached: bool = False
    robots_ok: bool = True
    robots_msg: str = ""
    parser_name: str = ""
    used_fallback: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# async 브리지: 매 호출 격리된 스레드에서 새 이벤트 루프로 실행.
# Streamlit ScriptRunner 스레드의 실행 중 루프와 충돌(RuntimeError)을 원천 차단.
# get_event_loop() 사용 금지, 루프를 전역/세션에 캐시 금지.
# ---------------------------------------------------------------------------
def _run_async(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# 캐시 (cache.json) — 기존 main.py:191-217에서 이동
# ---------------------------------------------------------------------------
def load_cache() -> list[dict]:
    try:
        with open(config.CACHE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_cache(cache: list[dict]) -> None:
    with open(config.CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def is_cached(url: str) -> bool:
    cache = load_cache()
    return any(item["url"] == url for item in cache)


def add_to_cache(post: JobPost) -> None:
    cache = load_cache()
    cache.append({
        "url": post.url,
        "company": post.company,
        "position": post.position,
        "last_seen": post.created_at,
    })
    save_cache(cache)


# ---------------------------------------------------------------------------
# 수집 (collect) — 기존 main.py:110-167(_add_url)/248-313(add) 흐름을 1:1 이전.
# 인쇄/확인/저장 없이 수집만 수행하고 CollectResult로 반환.
# ---------------------------------------------------------------------------
def collect(url: str) -> CollectResult:
    canonical = canonicalize_url(url)
    warnings: list[str] = []

    # 중복 체크
    if is_cached(canonical):
        return CollectResult(canonical_url=canonical, already_cached=True)

    # robots.txt 확인
    robots_ok = True
    robots_msg = ""
    if config.CHECK_ROBOTS_TXT:
        robots_ok, robots_msg = check_robots_txt(canonical)
        if not robots_ok:
            return CollectResult(
                canonical_url=canonical,
                robots_ok=False,
                robots_msg=robots_msg,
            )

    # 요청 딜레이 (연속 요청 방지)
    if config.REQUEST_DELAY_SECONDS > 0:
        time.sleep(config.REQUEST_DELAY_SECONDS)

    # 적절한 파서 선택
    parser = None
    parser_name = ""
    for p in PARSERS:
        if p.can_handle(canonical):
            parser = p
            parser_name = type(p).__name__
            break

    if parser is None:
        return CollectResult(
            canonical_url=canonical,
            robots_ok=robots_ok,
            robots_msg=robots_msg,
            error="지원하지 않는 URL입니다.",
        )

    used_fallback = False
    try:
        post = _run_async(parser.parse(canonical))
    except TimeoutError:
        return CollectResult(
            canonical_url=canonical,
            robots_ok=robots_ok,
            robots_msg=robots_msg,
            parser_name=parser_name,
            error="페이지 로딩 시간 초과. 네트워크 연결을 확인하거나 잠시 후 다시 시도해주세요.",
        )
    except Exception as e:
        error_msg = str(e)
        if "net::ERR" in error_msg or "Timeout" in error_msg:
            primary_err = "네트워크 오류. 인터넷 연결을 확인해주세요."
        else:
            primary_err = f"크롤링 실패: {error_msg}"

        # 전용 파서 실패 시 폴백 시도 (기존 main.py:158-167과 동일)
        if parser_name != "FallbackParser":
            warnings.append(primary_err)
            warnings.append("Gemini 폴백으로 재시도합니다...")
            try:
                post = _run_async(FallbackParser().parse(canonical))
                used_fallback = True
            except Exception as e2:
                return CollectResult(
                    canonical_url=canonical,
                    robots_ok=robots_ok,
                    robots_msg=robots_msg,
                    parser_name=parser_name,
                    warnings=warnings,
                    error=f"폴백도 실패: {e2}",
                )
        else:
            return CollectResult(
                canonical_url=canonical,
                robots_ok=robots_ok,
                robots_msg=robots_msg,
                parser_name=parser_name,
                error=primary_err,
            )

    return CollectResult(
        post=post,
        canonical_url=canonical,
        robots_ok=robots_ok,
        robots_msg=robots_msg,
        parser_name=parser_name,
        used_fallback=used_fallback,
        warnings=warnings,
    )


def build_post(data: dict) -> JobPost:
    """미리보기 dict(편집 가능)를 JobPost로 재구성.

    deadline_parsed/deadline_type는 UI에서 전달된 값을 신뢰한다 (파서가 계산한 값
    보존). deadline_type 문자열은 DeadlineType enum으로 복원한다.
    """
    dtype_raw = data.get("deadline_type") or "unknown"
    try:
        deadline_type = DeadlineType(dtype_raw)
    except ValueError:
        deadline_type = DeadlineType.UNKNOWN

    return JobPost(
        url=data.get("url", ""),
        company=data.get("company", ""),
        company_type=data.get("company_type", ""),
        employee_count=data.get("employee_count", ""),
        company_description=data.get("company_description", ""),
        position=data.get("position", ""),
        responsibilities=data.get("responsibilities", ""),
        requirements=data.get("requirements", ""),
        preferred=data.get("preferred", ""),
        deadline_raw=data.get("deadline_raw", ""),
        deadline_parsed=(data.get("deadline_parsed") or None),
        deadline_type=deadline_type,
        created_at=(data.get("created_at") or date.today().isoformat()),
        status=data.get("status", "interest"),
        memo=data.get("memo", ""),
    )


def save(post: JobPost) -> None:
    """Google Sheets 저장 + 로컬 캐시 추가 (기존 main.py:177-178)."""
    sheets.save_job_post(post)
    add_to_cache(post)


# ---------------------------------------------------------------------------
# 목록 / 마감 알림 / 상태 — sheets.py, slack.py 얇은 래퍼
# ---------------------------------------------------------------------------
def list_jobs(online: bool) -> list[dict]:
    """online=True면 Google Sheets, 아니면 로컬 캐시."""
    if online:
        return sheets.get_all_posts()
    return load_cache()


def find_upcoming(days: int | None = None) -> list[dict]:
    if days is None:
        days = config.NOTIFY_DAYS_BEFORE
    return sheets.get_upcoming_deadlines(days=days)


def send_notifications(jobs: list[dict]) -> bool:
    return slack.send_deadline_alert(jobs)


def mark_all_notified(jobs: list[dict]) -> None:
    """발송 완료 표시 (기존 main.py:381-385 — 개별 실패는 무시)."""
    for job in jobs:
        try:
            sheets.mark_notified(job["url"])
        except Exception:
            pass


def change_status(url: str, status: str) -> bool:
    canonical = canonicalize_url(url)
    return sheets.update_status(canonical, status)


def health() -> dict:
    """사이드바 환경 점검용 (읽기 전용). config 값 존재 여부만 반환."""
    return {
        "gemini": bool(config.GEMINI_API_KEY),
        "slack": bool(config.SLACK_WEBHOOK_URL),
        "sheets_id": bool(config.GOOGLE_SHEETS_ID),
        "credentials_file": os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE),
    }
