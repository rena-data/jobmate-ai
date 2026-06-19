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
    """마감일이 days일 이내인 공고 목록 반환."""
    ws = _get_sheet()
    records = ws.get_all_records()

    today = date.today()
    upcoming = []

    for row in records:
        deadline_str = row.get("마감일(파싱)", "")
        deadline_type = row.get("마감유형", "")
        notified_at = row.get("알림발송일", "")
        status = row.get("상태", "")

        # 이미 알림 보낸 것은 스킵
        if notified_at:
            continue

        # 이미 지원했거나 종료/보류된 건은 마감 알림 제외
        # (legacy "closed" 포함)
        if status in ("applied", "final_pass", "rejected", "hold", "closed"):
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
            })

    return upcoming


# 지원 파이프라인 상태 (관심→지원완료→서류합격→면접→최종합격, +불합격/보류).
# legacy "closed"는 표시용으로만 허용하고 신규 선택지에서는 제외.
VALID_STATUSES = [
    "interest", "applied", "document_pass", "interview", "final_pass",
    "rejected", "hold",
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
