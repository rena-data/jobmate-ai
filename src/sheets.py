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

        # 마감됨/지원완료는 스킵
        if status in ("closed", "applied"):
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


VALID_STATUSES = ["interest", "applied", "interview", "closed"]


def update_status(url: str, status: str) -> bool:
    """공고의 지원 상태를 업데이트."""
    ws = _get_sheet()
    headers = ws.row_values(1)

    if "상태" not in headers:
        return False
    status_col = headers.index("상태") + 1

    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            ws.update_cell(i + 1, status_col, status)
            return True
    return False


def mark_notified(url: str) -> None:
    """알림 발송 완료 표시."""
    ws = _get_sheet()
    headers = ws.row_values(1)

    # "알림발송일" 컬럼 확인/추가
    if "알림발송일" not in headers:
        col_idx = len(headers) + 1
        ws.update_cell(1, col_idx, "알림발송일")
    else:
        col_idx = headers.index("알림발송일") + 1

    # URL로 행 찾기
    urls = ws.col_values(1)
    for i, u in enumerate(urls):
        if u == url:
            ws.update_cell(i + 1, col_idx, date.today().isoformat())
            return
