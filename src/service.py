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
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import config
from classify import classify_role
from parsers.base import (
    JobPost,
    DeadlineType,
    canonicalize_url,
    check_robots_txt,
)
from parsers.wanted import WantedParser
from parsers.saramin import SaraminParser
from parsers.jobkorea import JobkoreaParser
from parsers.groupby import GroupbyParser
from parsers.fallback import FallbackParser
from searchers.wanted import WantedSearcher
from searchers.saramin import SaraminSearcher
from searchers.jobkorea import JobkoreaSearcher
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

# 검색기 등록 (자동 수집 — 전용 파서 보유 플랫폼만). PARSERS와 동일한 레지스트리 패턴.
# 점핏은 전용 상세 파서 부재로 다음 라운드, 로켓펀치는 CloudFront 봇차단으로 제외.
SEARCHERS = [
    WantedSearcher(),
    SaraminSearcher(),
    JobkoreaSearcher(),
]

# 상태 값 재노출 (sheets.VALID_STATUSES와 동일)
VALID_STATUSES = sheets.VALID_STATUSES

# 상태 → 한글 라벨 (UI 공용). "closed"는 레거시 시트값 표시용.
STATUS_LABELS = {
    "interest": "관심공고",
    "applied": "지원완료",
    "document_fail": "서류탈락",
    "document_pass": "서류합격",
    "interview": "면접예정",
    "interview_fail": "면접탈락",
    "final_pass": "최종합격",
    "rejected": "불합격",
    "hold": "보류",
    "closed": "마감",
}

# URL 도메인 → 플랫폼명 (대시보드 플랫폼별 집계용)
_PLATFORMS = [
    ("원티드", "wanted.co.kr"),
    ("사람인", "saramin.co.kr"),
    ("잡코리아", "jobkorea.co.kr"),
    ("그룹바이", "groupby.kr"),
]


def platform_of(url: str) -> str:
    """공고 URL에서 출처 플랫폼명을 추정. 매칭 없으면 '기타'."""
    u = (url or "").lower()
    for name, domain in _PLATFORMS:
        if domain in u:
            return name
    return "기타"


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


def clear_cache() -> None:
    """로컬 캐시(cache.json)를 비운다. 시트는 보존(중복검사는 시트로도 동작)."""
    save_cache([])


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
# 자동 수집 (auto-collect) — 신규 기능.
# 키워드로 플랫폼을 검색해 신규 공고 URL을 발견하고, 기존 collect()/save()
# 파이프라인으로 수집한다. 기존 수동 수집 경로는 한 줄도 바꾸지 않는다.
# ---------------------------------------------------------------------------
@dataclass
class AutoCollectItem:
    """자동 수집 후보 1건의 처리 결과."""

    keyword: str
    platform: str
    url: str
    outcome: str  # "new" | "duplicate" | "failed"
    company: str = ""
    position: str = ""
    error: str | None = None


@dataclass
class AutoCollectStats:
    """키워드 × 플랫폼 단위 집계."""

    keyword: str
    platform: str
    discovered: int = 0
    new: int = 0
    duplicate: int = 0
    failed: int = 0


@dataclass
class AutoCollectResult:
    """auto_collect() 전체 결과 (UI/CLI가 인쇄)."""

    items: list[AutoCollectItem] = field(default_factory=list)
    stats: list[AutoCollectStats] = field(default_factory=list)
    discovered: int = 0
    new: int = 0
    duplicate: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)  # 검색기 레벨 실패


def resolve_keywords() -> list[str]:
    """검색 키워드 결정: Google Sheets '키워드 관리' 탭 우선, 없으면 config 기본값."""
    try:
        kws = sheets.get_keywords()
    except Exception:
        kws = []
    return kws or list(config.AUTOCOLLECT_KEYWORDS)


def save_keywords(keywords: list[str]) -> None:
    """검색 키워드 목록을 '키워드 관리' 시트에 저장 (resolve_keywords가 읽음)."""
    sheets.save_keywords(keywords)


def discover(keyword: str, platform: str, limit: int) -> list[str]:
    """keyword × platform → 후보 상세 URL 리스트. 매칭 검색기 없으면 빈 리스트.

    검색기는 async이므로 collect()와 동일하게 _run_async로 격리 실행한다.
    """
    for s in SEARCHERS:
        if s.can_search(platform):
            return _run_async(s.search(keyword, limit))
    return []


def save_auto(post: JobPost, *, keyword: str, platform: str) -> None:
    """자동 수집 저장: 기존 save()로 행 추가 후 자동 메타데이터를 태깅."""
    save(post)
    sheets.annotate_collection(
        post.url, search_keyword=keyword, platform=platform,
        is_new="Y", method="자동",
    )


def _job_key(company: str, position: str) -> str | None:
    """회사+직무 정규화 키(공백 축약 + 소문자). 둘 다 비면 None(중복판정 제외)."""
    c = re.sub(r"\s+", " ", (company or "").strip()).lower()
    p = re.sub(r"\s+", " ", (position or "").strip()).lower()
    if not c and not p:
        return None
    return f"{c}|{p}"


def auto_collect(
    keywords: list[str],
    platforms: list[str] | None = None,
    limit_per: int | None = None,
) -> AutoCollectResult:
    """키워드로 플랫폼을 검색해 신규 공고만 자동 수집한다.

    중복 제거 2단계:
      1) URL 기준 — 캐시(is_cached) + 시트 URL 스냅샷. collect 비용 전에 차단.
      2) 회사+직무 기준 — 수집 후 (회사,직무)가 시트/이번 실행에 이미 있으면 저장 스킵.
         URL이 달라도 동일 회사·동일 직무면 중복으로 본다.
    검색기 실패는 result.errors에 담고 다음 키워드/플랫폼으로 계속 진행한다.
    """
    platforms = platforms or [s.platform_name for s in SEARCHERS]
    limit_per = limit_per or config.AUTOCOLLECT_LIMIT_PER
    result = AutoCollectResult()

    # 시작 시 시트를 1회만 읽어 URL/(회사,직무) 스냅샷 구축 (URL당 반복 조회 방지)
    seen_urls: set[str] = set()
    seen_jobs: set[str] = set()
    try:
        for r in sheets.get_all_posts():
            u = str(r.get("URL", "") or "")
            if u:
                seen_urls.add(u)
            jk = _job_key(str(r.get("회사명", "")), str(r.get("포지션", "")))
            if jk:
                seen_jobs.add(jk)
    except Exception as e:
        result.errors.append(f"기존 시트 조회 실패(중복검사 일부 제한): {e}")

    for kw in keywords:
        for plat in platforms:
            stat = AutoCollectStats(keyword=kw, platform=plat)
            try:
                candidates = discover(kw, plat, limit_per)
            except Exception as e:
                result.errors.append(f"{plat} / '{kw}' 검색 실패: {e}")
                result.stats.append(stat)
                continue

            for url in candidates:
                stat.discovered += 1
                canonical = canonicalize_url(url)

                # 1단계: URL 중복 — collect 비용(robots/딜레이/Playwright) 전에 차단
                if is_cached(canonical) or canonical in seen_urls:
                    stat.duplicate += 1
                    result.items.append(AutoCollectItem(kw, plat, canonical, "duplicate"))
                    continue

                cr = collect(canonical)
                if cr.post is None:
                    if cr.already_cached:  # 검사~수집 사이 레이스 방어
                        stat.duplicate += 1
                        result.items.append(AutoCollectItem(kw, plat, canonical, "duplicate"))
                    else:
                        stat.failed += 1
                        result.items.append(
                            AutoCollectItem(kw, plat, canonical, "failed", error=cr.error)
                        )
                    continue

                # 2단계: 회사+직무 중복 — URL이 달라도 동일 공고면 저장 스킵
                jkey = _job_key(cr.post.company, cr.post.position)
                if jkey is not None and jkey in seen_jobs:
                    stat.duplicate += 1
                    result.items.append(
                        AutoCollectItem(
                            kw, plat, canonical, "duplicate",
                            company=cr.post.company, position=cr.post.position,
                        )
                    )
                    continue

                save_auto(cr.post, keyword=kw, platform=plat)
                seen_urls.add(canonical)
                if jkey is not None:
                    seen_jobs.add(jkey)
                stat.new += 1
                result.items.append(
                    AutoCollectItem(
                        kw, plat, canonical, "new",
                        company=cr.post.company, position=cr.post.position,
                    )
                )

            result.stats.append(stat)
            result.discovered += stat.discovered
            result.new += stat.new
            result.duplicate += stat.duplicate
            result.failed += stat.failed

    return result


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


def find_stale_applications(days: int | None = None) -> list[dict]:
    if days is None:
        days = config.STALE_APPLY_DAYS
    return sheets.get_stale_applications(days=days)


def dashboard_summary(rows: list[dict], upcoming_days: int = 7) -> dict:
    """저장된 공고 행(get_all_posts 형식)을 집계해 대시보드용 통계 반환.

    순수 함수(네트워크 없음) — rows만 받아 계산하므로 단독 테스트 가능.
    직군은 classify_role로 온더플라이 분류(시트 컬럼 불필요).
    """
    today = date.today()
    status_counts = {s: 0 for s in VALID_STATUSES}
    role_counts: dict[str, int] = {}
    new_role_counts: dict[str, int] = {}
    upcoming: list[dict] = []
    rolling = 0
    new_this_week = 0
    platforms: dict[str, dict] = {}
    recent_all: list[dict] = []

    for r in rows:
        st = str(r.get("상태", "") or "interest")
        if st in status_counts:
            status_counts[st] += 1

        role = classify_role(str(r.get("포지션", "")), str(r.get("주요업무", "")))
        role_counts[role] = role_counts.get(role, 0) + 1

        if str(r.get("마감유형", "")) == "rolling":
            rolling += 1

        url = str(r.get("URL", "") or "")
        plat = platform_of(url)
        pc = platforms.setdefault(
            plat,
            {"platform": plat, "collected": 0, "new_week": 0, "closed": 0, "last_collected": ""},
        )
        pc["collected"] += 1

        created = str(r.get("등록일", "") or "")
        is_new = False
        try:
            cd = datetime.strptime(created, "%Y-%m-%d").date()
            if 0 <= (today - cd).days <= 7:
                new_this_week += 1
                is_new = True
            if created > pc["last_collected"]:
                pc["last_collected"] = created
        except ValueError:
            pass
        if is_new:
            pc["new_week"] += 1
            new_role_counts[role] = new_role_counts.get(role, 0) + 1

        deadline_str = str(r.get("마감일(파싱)", "") or "")
        if str(r.get("마감유형", "")) == "fixed" and deadline_str:
            try:
                d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                diff = (d - today).days
                if 0 <= diff <= upcoming_days:
                    upcoming.append({
                        "company": r.get("회사명", ""),
                        "position": r.get("포지션", ""),
                        "deadline": deadline_str,
                        "days_left": diff,
                        "status": st,
                    })
                elif diff < 0:
                    pc["closed"] += 1
            except ValueError:
                pass

        recent_all.append({
            "company": r.get("회사명", ""),
            "position": r.get("포지션", ""),
            "status": st,
            "url": url,
            "created": created,
            "is_new": is_new,
        })

    upcoming.sort(key=lambda x: x["days_left"])
    role_counts = dict(sorted(role_counts.items(), key=lambda kv: -kv[1]))
    platform_counts = sorted(platforms.values(), key=lambda p: -p["collected"])
    recent = sorted(recent_all, key=lambda x: x["created"], reverse=True)[:5]
    new_top_roles = sorted(new_role_counts.items(), key=lambda kv: -kv[1])[:2]

    return {
        "total": len(rows),
        "status_counts": status_counts,
        "role_counts": role_counts,
        "upcoming": upcoming,
        "rolling": rolling,
        "new_this_week": new_this_week,
        "platform_counts": platform_counts,
        "recent": recent,
        "insights": {
            "new_total": new_this_week,
            "new_top_roles": new_top_roles,
            "upcoming_count": len(upcoming),
            "interest_not_applied": status_counts.get("interest", 0),
        },
    }


def send_notifications(jobs: list[dict]) -> bool:
    return slack.send_deadline_alert(jobs)


def mark_all_notified(jobs: list[dict]) -> None:
    """마감 알림 발송 완료 표시 (개별 실패는 무시)."""
    for job in jobs:
        try:
            sheets.mark_notified(job["url"])
        except Exception:
            pass


def send_application_reminders(jobs: list[dict]) -> bool:
    return slack.send_application_reminder(jobs)


def mark_all_reminded(jobs: list[dict]) -> None:
    """지원 후속 리마인더 발송 완료 표시 (개별 실패는 무시)."""
    for job in jobs:
        try:
            sheets.mark_reminder_sent(job["url"])
        except Exception:
            pass


def change_status(url: str, status: str) -> bool:
    canonical = canonicalize_url(url)
    return sheets.update_status(canonical, status)


def update_memo(url: str, memo: str) -> bool:
    canonical = canonicalize_url(url)
    return sheets.update_memo(canonical, memo)


def health() -> dict:
    """사이드바 환경 점검용 (읽기 전용). config 값 존재 여부만 반환."""
    return {
        "gemini": bool(config.GEMINI_API_KEY),
        "slack": bool(config.SLACK_WEBHOOK_URL),
        "sheets_id": bool(config.GOOGLE_SHEETS_ID),
        "credentials_file": os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE),
    }
