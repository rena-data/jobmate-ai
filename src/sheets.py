from __future__ import annotations

from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

import config
from parsers.base import JobPost


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _get_sheet(worksheet_name: str = "Job Posts") -> gspread.Worksheet:
    client = _get_client()
    spreadsheet = client.open_by_key(config.GOOGLE_SHEETS_ID)

    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=20)
        ws.append_row(JobPost.sheet_headers())

    return ws


def _ensure_column(ws: gspread.Worksheet, name: str) -> int:
    """헤더에 name 컬럼이 없으면 끝에 추가하고, 1-based 컬럼 인덱스를 반환."""
    headers = ws.row_values(1)
    if name in headers:
        return headers.index(name) + 1
    col_idx = len(headers) + 1
    ws.update_cell(1, col_idx, name)
    return col_idx


def is_url_exists(url: str) -> bool:
    """시트에 이미 해당 URL이 존재하는지 확인."""
    ws = _get_sheet()
    urls = ws.col_values(1)  # URL 컬럼 (1번째)
    return url in urls


def get_all_posts() -> list[dict]:
    """시트에서 모든 공고를 조회."""
    ws = _get_sheet()
    return ws.get_all_records()


def save_job_post(post: JobPost) -> None:
    """JobPost를 Google Sheets에 저장."""
    ws = _get_sheet()

    # 헤더가 없으면 추가
    if not ws.row_values(1):
        ws.append_row(JobPost.sheet_headers())

    ws.append_row(post.to_sheet_row())


def get_upcoming_deadlines(days: int = 2) -> list[dict]:
    """마감일이 days일 이내인 공고 목록 반환.

    각 항목에 'notified'(알림발송일 문자열, 미발송이면 "")를 함께 담는다.
    알림 발송 이력으로는 제외하지 않는다 — 같은 공고도 다시 발송할 수 있다.
    (중복 방지는 '수집 데이터'에만 적용. 'notified'는 마지막 발송일 표시용일 뿐 필터 아님.)
    """
    ws = _get_sheet()
    records = ws.get_all_records()

    today = date.today()
    upcoming = []

    for row in records:
        deadline_str = row.get("마감일(파싱)", "")
        deadline_type = row.get("마감유형", "")
        notified_at = str(row.get("알림발송일", "") or "")
        status = row.get("상태", "")

        # 이미 지원했거나 탈락/종료/보류된 건은 마감 알림 제외
        # (legacy "closed" 포함)
        if status in ("applied", "document_fail", "interview_fail",
                      "final_pass", "rejected", "hold", "closed"):
            continue

        if deadline_type != "fixed" or not deadline_str:
            continue

        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        diff = (deadline - today).days
        if 0 <= diff <= days:
            upcoming.append({
                "company": row.get("회사명", ""),
                "company_type": row.get("업종", ""),
                "position": row.get("포지션", ""),
                "requirements": row.get("자격요건", ""),
                "deadline": deadline_str,
                "url": row.get("URL", ""),
                "days_left": diff,
                "notified": notified_at,
            })

    return upcoming


# 지원 파이프라인 상태 (관심공고→지원완료→서류탈락/서류합격→면접예정→면접탈락→
# 최종합격, +불합격/보류). legacy "closed"는 표시용으로만 허용하고 신규 선택지에서는 제외.
VALID_STATUSES = [
    "interest", "applied", "document_fail", "document_pass",
    "interview", "interview_fail", "final_pass", "rejected", "hold",
]


def update_status(url: str, status: str) -> bool:
    """공고의 지원 상태를 업데이트. '지원완료' 전환 시 '지원일'을 기록한다."""
    ws = _get_sheet()
    headers = ws.row_values(1)

    if "상태" not in headers:
        return False
    status_col = headers.index("상태") + 1

    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            row_idx = i + 1
            ws.update_cell(row_idx, status_col, status)
            # 지원완료로 바뀌면 '지원일'을 한 번만 기록 (기존 값 보존)
            if status == "applied":
                applied_col = _ensure_column(ws, "지원일")
                if not ws.cell(row_idx, applied_col).value:
                    ws.update_cell(row_idx, applied_col, date.today().isoformat())
            return True
    return False


def update_memo(url: str, memo: str) -> bool:
    """공고의 비고(메모)를 업데이트. update_status와 동일 패턴."""
    ws = _get_sheet()
    headers = ws.row_values(1)

    if "비고" not in headers:
        return False
    memo_col = headers.index("비고") + 1

    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            ws.update_cell(i + 1, memo_col, memo)
            return True
    return False


def mark_notified(url: str) -> None:
    """마감 알림 발송 완료 표시."""
    ws = _get_sheet()
    col_idx = _ensure_column(ws, "알림발송일")
    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            ws.update_cell(i + 1, col_idx, date.today().isoformat())
            return


def get_stale_applications(days: int = 7) -> list[dict]:
    """지원완료 후 days일 이상 경과 + 후속 리마인더 미발송 공고 목록."""
    ws = _get_sheet()
    records = ws.get_all_records()

    today = date.today()
    stale = []

    for row in records:
        if str(row.get("상태", "")) != "applied":
            continue
        applied_str = str(row.get("지원일", "") or "")
        if not applied_str:
            continue
        # 이미 리마인더 보낸 건은 스킵
        if str(row.get("지원리마인더발송일", "") or ""):
            continue
        try:
            applied = datetime.strptime(applied_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        elapsed = (today - applied).days
        if elapsed >= days:
            stale.append({
                "company": row.get("회사명", ""),
                "company_type": row.get("업종", ""),
                "position": row.get("포지션", ""),
                "applied_date": applied_str,
                "elapsed": elapsed,
                "url": row.get("URL", ""),
            })

    return stale


def mark_reminder_sent(url: str) -> None:
    """지원 후속 리마인더 발송 완료 표시."""
    ws = _get_sheet()
    col_idx = _ensure_column(ws, "지원리마인더발송일")
    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            ws.update_cell(i + 1, col_idx, date.today().isoformat())
            return


# ---------------------------------------------------------------------------
# 자동 수집 (auto-collect) — 신규 기능
# ---------------------------------------------------------------------------
KEYWORD_SHEET_NAME = "키워드 관리"


def get_keywords() -> list[str]:
    """'키워드 관리' 탭에서 활성 검색 키워드 목록을 읽는다.

    헤더 '키워드'(필수) + '사용'(선택, N/FALSE/0/미사용이면 제외)을 본다.
    탭이 없으면 빈 리스트 → 호출자가 config 기본값으로 폴백.
    (_get_sheet는 미사용 — 자동 생성 시 공고용 헤더가 붙는 것을 피한다.)
    """
    client = _get_client()
    ss = client.open_by_key(config.GOOGLE_SHEETS_ID)
    try:
        ws = ss.worksheet(KEYWORD_SHEET_NAME)
    except gspread.WorksheetNotFound:
        return []

    out: list[str] = []
    for r in ws.get_all_records():
        kw = str(r.get("키워드", "") or "").strip()
        if not kw:
            continue
        use = str(r.get("사용", "Y") or "Y").strip().upper()
        if use in ("N", "FALSE", "0", "미사용", "X"):
            continue
        out.append(kw)
    return out


def save_keywords(keywords: list[str]) -> None:
    """'키워드 관리' 탭을 (없으면 생성 후) 헤더 + 키워드 목록으로 덮어쓴다.

    공백 제거 + 순서 보존 중복 제거. '사용' 컬럼은 모두 Y로 기록한다.
    """
    client = _get_client()
    ss = client.open_by_key(config.GOOGLE_SHEETS_ID)
    try:
        ws = ss.worksheet(KEYWORD_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=KEYWORD_SHEET_NAME, rows=200, cols=4)

    seen: set[str] = set()
    clean: list[str] = []
    for kw in keywords:
        k = str(kw).strip()
        if k and k not in seen:
            seen.add(k)
            clean.append(k)

    rows = [["키워드", "사용"]] + [[k, "Y"] for k in clean]
    ws.clear()
    ws.append_rows(rows)


def annotate_collection(
    url: str, *, search_keyword: str, platform: str,
    is_new: str = "Y", method: str = "자동",
) -> None:
    """자동 수집 메타데이터를 해당 URL 행에 기록.

    기존 15컬럼 positional 레이아웃(JobPost.to_sheet_row)은 건드리지 않고,
    _ensure_column으로 끝열에 메타 컬럼을 추가/사용한다 (mark_notified 패턴).
    수동 수집 행은 이 컬럼들이 비어 있어 자동/수동 구분이 가능하다.
    """
    ws = _get_sheet()
    kw_col = _ensure_column(ws, "검색키워드")
    plat_col = _ensure_column(ws, "수집플랫폼")
    new_col = _ensure_column(ws, "신규여부")
    method_col = _ensure_column(ws, "수집방식")
    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            row = i + 1
            ws.update_cell(row, kw_col, search_keyword)
            ws.update_cell(row, plat_col, platform)
            ws.update_cell(row, new_col, is_new)
            ws.update_cell(row, method_col, method)
            return
