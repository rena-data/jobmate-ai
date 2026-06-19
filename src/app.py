"""JobMate AI — Streamlit 웹 UI.

CLI(main.py)와 동일한 로직(service.py)을 웹에서 제공한다.
service만 import한다 (asyncio/playwright/parser 직접 import 금지).
실행: streamlit run app.py
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime

import pandas as pd
import streamlit as st

import config
import service

st.set_page_config(page_title="JobMate AI", page_icon="💼", layout="wide")

# 사이드바: 텍스트 약간 확대 + 환경 상태를 최하단에 고정
st.markdown(
    """
    <style>
    /* 사이드바 본문 텍스트 약간 확대 */
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label { font-size: 1.05rem; }
    /* 메뉴(카테고리) 강조 — 크게 + 굵게 (그룹 헤더 느낌) */
    section[data-testid="stSidebar"] [data-testid="stPageLink"] * {
        font-size: 1.15rem !important;
        font-weight: 700 !important;
    }
    /* 1) 최상위 컨테이너: 풀하이트 flex 컬럼 */
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        display: flex !important;
        flex-direction: column !important;
        min-height: calc(100vh - 1rem);
    }
    /* 2) 하위 컨테이너 체인을 모두 '부모를 꽉 채우는 flex 컬럼'으로
          (UserContent → 그 child → 실제 콘텐츠 stVerticalBlock 까지) */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div,
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 auto !important;
        min-height: 0 !important;
    }
    /* 3) 환경 상태(leaf)만 최하단으로 — 브랜드/메뉴는 상단 유지 */
    .st-key-sidebar_health { margin-top: auto !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------------------------
DEFAULTS = {
    "pending_post": None,      # 방금 수집한 JobPost(dict). 수집→저장/취소 사이 유지
    "pending_meta": None,      # parser_name / used_fallback / robots_msg / warnings
    "last_saved": None,        # 저장 완료 토스트 메시지
    "upcoming_jobs": None,     # 마감 조회 결과 (발송 버튼 재실행 대비)
    "notify_sent": False,      # 중복 발송 가드
    "stale_jobs": None,        # 지원 후속(지원 후 N일) 조회 결과
    "stale_sent": False,       # 후속 리마인더 중복 발송 가드
    "jobs_cache": None,        # 목록 탭 캐시
    "jobs_cache_online": None, # 목록 탭 캐시 소스 (True=온라인)
    "status_records": None,    # 상태 변경 탭 공고 목록 캐시
    "dash_rows": None,         # 대시보드 탭 데이터 캐시
    "detail_opened_url": None, # 상세 모달 재오픈 가드 (목록 행 선택)
}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)

# 미리보기에서 편집 가능한 텍스트 필드 (deadline_type은 selectbox로 별도 처리)
EDIT_FIELDS = [
    "company", "company_type", "employee_count", "company_description",
    "position", "responsibilities", "requirements", "preferred",
    "deadline_raw", "deadline_parsed", "memo",
]
DEADLINE_TYPES = ["fixed", "rolling", "unknown"]


def _clear_preview_state() -> None:
    """미리보기/편집 위젯 상태를 모두 정리 (이전 공고 값 누수 방지)."""
    st.session_state.pending_post = None
    st.session_state.pending_meta = None
    for f in EDIT_FIELDS + ["deadline_type"]:
        st.session_state.pop(f"edit_{f}", None)


# ---------------------------------------------------------------------------
# 상태 배지 / D-day / 공고 상세 모달 (목록 행 선택 시 오픈)
# ---------------------------------------------------------------------------
_STATUS_COLORS = {
    "interest": "#5B6B8C",
    "applied": "#1B2A4A",
    "document_pass": "#0F766E",
    "interview": "#B45309",
    "final_pass": "#15803D",
    "rejected": "#B91C1C",
    "hold": "#6B7280",
    "closed": "#9CA3AF",
}


def _status_badge(status: str) -> str:
    """상태 코드 → 색상 배지 HTML (st.markdown unsafe_allow_html=True 용)."""
    label = service.STATUS_LABELS.get(status, status or "—")
    color = _STATUS_COLORS.get(status, "#6B7280")
    return (
        f"<span style='background:{color};color:#fff;padding:2px 10px;"
        f"border-radius:10px;font-size:0.85rem;font-weight:600;'>{label}</span>"
    )


def _dday_text(parsed: str, dtype: str) -> str:
    """확정(fixed) 마감의 D-day 텍스트. 그 외/파싱불가면 빈 문자열."""
    if dtype != "fixed" or not parsed:
        return ""
    try:
        d = datetime.strptime(parsed, "%Y-%m-%d").date()
    except ValueError:
        return ""
    diff = (d - date.today()).days
    if diff < 0:
        return "마감"
    return "오늘!" if diff == 0 else f"D-{diff}"


@st.dialog("공고 상세", width="large")
def _render_job_detail_dialog(record: dict) -> None:
    """온라인(시트) 공고 한 건의 상세 + 상태/메모 편집 모달."""
    url = record.get("URL", "")
    company = record.get("회사명", "")
    position = record.get("포지션", "")
    cur_status = str(record.get("상태", "") or "interest")
    role = service.classify_role(position, record.get("주요업무", ""))

    st.markdown(f"### {company or '(회사 미상)'}")
    st.markdown(f"**{position or '(포지션 미상)'}**")
    meta = " · ".join(
        x for x in [role, record.get("업종", ""), record.get("직원수", "")] if x
    )
    if meta:
        st.caption(meta)
    if record.get("회사설명"):
        st.write(record["회사설명"])

    deadline = record.get("마감일(파싱)", "") or record.get("마감일(원본)", "")
    dday = _dday_text(record.get("마감일(파싱)", ""), record.get("마감유형", ""))
    c1, c2 = st.columns(2)
    c1.markdown(f"**마감** {deadline or '미정'}" + (f"  ({dday})" if dday else ""))
    with c2:
        st.markdown("**현재 상태**")
        st.markdown(_status_badge(cur_status), unsafe_allow_html=True)

    st.divider()
    for label in ("주요업무", "자격요건", "우대사항"):
        val = record.get(label, "")
        if val:
            with st.expander(label, expanded=(label == "주요업무")):
                st.write(val)
    if url:
        st.link_button("🔗 원문 보기", url)

    st.divider()
    st.markdown("##### 지원 관리")
    options = list(service.VALID_STATUSES)
    if cur_status and cur_status not in options:  # legacy(closed) 보존
        options = [cur_status] + options
    new_status = st.selectbox(
        "상태",
        options,
        index=options.index(cur_status) if cur_status in options else 0,
        format_func=lambda s: service.STATUS_LABELS.get(s, s),
        key=f"detail_status_{url}",
    )
    cur_memo = record.get("비고", "") or ""
    new_memo = st.text_area("메모", value=cur_memo, height=120, key=f"detail_memo_{url}")

    if st.button("💾 저장", type="primary", key=f"detail_save_{url}"):
        if not url:
            st.error("URL이 없어 저장할 수 없습니다.")
            return
        try:
            with st.spinner("Google Sheets에 저장 중…"):
                if new_status != cur_status:
                    service.change_status(url, new_status)
                if new_memo != cur_memo:
                    service.update_memo(url, new_memo)
        except Exception as e:
            st.error(f"저장 실패: {e}")
            return
        st.session_state.jobs_cache = None
        st.session_state.status_records = None
        st.session_state.dash_rows = None
        st.success("저장되었습니다.")
        st.rerun()


# ---------------------------------------------------------------------------
# 사이드바: 환경 상태 (읽기 전용)
# ---------------------------------------------------------------------------
def _render_health_content() -> None:
    """환경 상태 — SaaS/Admin 풋터 스타일 (상태 점 표시)."""
    h = service.health()
    items = [
        ("AI 분석 (Gemini)", bool(h.get("gemini"))),
        ("데이터 (Google Sheets)", bool(h.get("sheets_id") and h.get("credentials_file"))),
        ("알림 (Slack)", bool(h.get("slack"))),
    ]
    st.markdown("##### 환경 상태")
    lines = [f"{'🟢' if ok else '🔴'} {label}" for label, ok in items]
    st.markdown("  \n".join(lines))
    st.caption("값은 `.env` / `credentials.json`에서 관리")


# ---------------------------------------------------------------------------
# 탭 1: 수집
# ---------------------------------------------------------------------------
def _render_collect_tab() -> None:
    st.subheader("채용 공고 수집")

    if st.session_state.last_saved:
        st.success(st.session_state.last_saved)
        st.session_state.last_saved = None

    with st.form("collect_form"):
        url = st.text_input(
            "채용 공고 URL",
            placeholder="https://www.wanted.co.kr/wd/...",
        )
        submitted = st.form_submit_button("수집", type="primary")
    st.caption("ⓘ 수집 시 Playwright 브라우저 창이 잠깐 열립니다 (로컬 전용). 10~30초 소요될 수 있습니다.")

    if submitted:
        _handle_collect(url)

    if st.session_state.pending_post is not None:
        _render_preview_and_save()


def _handle_collect(url: str) -> None:
    if not url or not url.strip().startswith("http"):
        st.warning("올바른 URL을 입력해주세요. (http로 시작)")
        return

    _clear_preview_state()
    result = None
    with st.status("수집 중… 브라우저 창이 잠깐 열립니다.", expanded=True) as box:
        try:
            result = service.collect(url.strip())
            box.update(label="수집 완료", state="complete")
        except Exception as e:  # 백스톱: 트레이스백 노출 금지
            box.update(label="수집 실패", state="error")
            st.error(f"예기치 못한 오류: {e}")

    if result is None:
        return

    if result.already_cached:
        st.warning(f"이미 등록된 URL입니다: {result.canonical_url}")
    elif not result.robots_ok:
        st.warning(f"robots.txt에서 접근이 제한된 URL입니다. ({result.robots_msg})")
    elif result.post is None:
        st.error(result.error or "수집에 실패했습니다.")
    else:
        d = asdict(result.post)
        d["deadline_type"] = result.post.deadline_type.value
        st.session_state.pending_post = d
        st.session_state.pending_meta = {
            "parser_name": result.parser_name,
            "used_fallback": result.used_fallback,
            "robots_msg": result.robots_msg,
            "warnings": result.warnings,
        }
        # 편집 위젯 시드 (value= 대신 session_state로 초기화하여 경고 방지)
        for f in EDIT_FIELDS:
            st.session_state[f"edit_{f}"] = d.get(f) or ""
        st.session_state["edit_deadline_type"] = d.get("deadline_type") or "unknown"


def _render_preview_and_save() -> None:
    meta = st.session_state.pending_meta or {}
    st.divider()
    st.markdown(f"**✔ 수집 완료 · 파서: {meta.get('parser_name', '')}**")
    if meta.get("robots_msg"):
        st.caption(f"robots.txt: {meta['robots_msg']}")
    if meta.get("used_fallback"):
        st.warning("전용 파서 실패 → Gemini 폴백으로 추출했습니다. 내용을 꼭 확인하세요.")
    for w in meta.get("warnings", []):
        st.caption(w)

    st.markdown("##### 미리보기 (저장 전 수정 가능)")
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("회사명", key="edit_company")
        st.text_input("업종", key="edit_company_type")
        st.text_input("직원수", key="edit_employee_count")
        st.text_input("포지션", key="edit_position")
    with c2:
        st.text_input("마감일(원본)", key="edit_deadline_raw")
        st.text_input("마감일(파싱) — YYYY-MM-DD", key="edit_deadline_parsed")
        st.selectbox("마감유형", DEADLINE_TYPES, key="edit_deadline_type")
        st.text_input("회사설명", key="edit_company_description")

    st.text_area("주요업무", key="edit_responsibilities", height=120)
    st.text_area("자격요건", key="edit_requirements", height=120)
    st.text_area("우대사항", key="edit_preferred", height=120)
    st.text_area("비고(메모)", key="edit_memo", height=80)
    st.caption(f"URL: {st.session_state.pending_post.get('url', '')}")

    b1, b2, _ = st.columns([1, 1, 5])
    with b1:
        if st.button("💾 저장", type="primary", key="save_btn"):
            _handle_save()
    with b2:
        if st.button("취소", key="cancel_btn"):
            _clear_preview_state()
            st.rerun()


def _handle_save() -> None:
    pending = st.session_state.pending_post or {}
    edited = {f: st.session_state.get(f"edit_{f}", "") for f in EDIT_FIELDS}
    edited["deadline_type"] = st.session_state.get("edit_deadline_type", "unknown")
    edited["url"] = pending.get("url", "")
    edited["created_at"] = pending.get("created_at", "")
    edited["status"] = pending.get("status", "interest")

    try:
        post = service.build_post(edited)
        with st.spinner("Google Sheets에 저장 중…"):
            service.save(post)
    except PermissionError:
        st.error("Google Sheets 권한 오류. 서비스 계정 이메일에 편집자 권한을 부여했는지 확인해주세요.")
        return
    except Exception as e:
        msg = str(e)
        if "quota" in msg.lower():
            st.error("Google Sheets API 한도 초과. 잠시 후 다시 시도해주세요.")
        else:
            st.error(f"저장 실패: {msg}")
        return

    st.session_state.jobs_cache = None
    st.session_state.status_records = None
    st.session_state.dash_rows = None
    st.session_state.last_saved = f"저장 완료: {post.company} · {post.position}"
    _clear_preview_state()
    st.rerun()


# ---------------------------------------------------------------------------
# 탭 2: 목록
# ---------------------------------------------------------------------------
def _render_list_tab() -> None:
    st.subheader("저장된 공고 목록")
    c1, c2 = st.columns([4, 1])
    with c1:
        source = st.radio(
            "데이터 소스",
            ["로컬 캐시", "Google Sheets (온라인)"],
            horizontal=True,
            key="list_source",
        )
    with c2:
        st.write("")
        if st.button("새로고침", key="list_refresh"):
            st.session_state.jobs_cache = None

    online = source.startswith("Google")

    if st.session_state.jobs_cache is None or st.session_state.jobs_cache_online != online:
        try:
            with st.spinner("불러오는 중…"):
                st.session_state.jobs_cache = service.list_jobs(online=online)
                st.session_state.jobs_cache_online = online
        except Exception as e:
            st.error(f"목록 조회 실패: {e}")
            st.session_state.jobs_cache = []
            st.session_state.jobs_cache_online = online

    records = st.session_state.jobs_cache or []
    st.caption(f"{len(records)}건")
    if not records:
        st.info("저장된 공고가 없습니다.")
        return

    if online:
        st.caption("ⓘ 행을 클릭하면 상세 보기 + 상태/메모 편집 창이 열립니다.")
        view = [
            {
                "회사": r.get("회사명", ""),
                "포지션": r.get("포지션", ""),
                "마감일": r.get("마감일(파싱)", "") or r.get("마감일(원본)", ""),
                "상태": service.STATUS_LABELS.get(str(r.get("상태", "")), r.get("상태", "")),
                "등록일": r.get("등록일", ""),
            }
            for r in records
        ]
        event = st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="list_df",
        )
        sel = event.selection.rows if event and event.selection else []
        if sel:
            rec = records[sel[0]]
            # 같은 행을 다시 선택하기 전까지는 (모달 닫기/저장 후) 재오픈 방지
            if st.session_state.detail_opened_url != rec.get("URL", ""):
                st.session_state.detail_opened_url = rec.get("URL", "")
                _render_job_detail_dialog(rec)
        else:
            st.session_state.detail_opened_url = None
    else:
        view = [
            {
                "회사": r.get("company", ""),
                "포지션": r.get("position", ""),
                "등록일": r.get("last_seen", ""),
            }
            for r in records
        ]
        st.dataframe(view, width="stretch", hide_index=True)
        st.caption("ⓘ 상세 보기는 'Google Sheets (온라인)' 소스에서 지원됩니다.")


# ---------------------------------------------------------------------------
# 탭 3: 마감 알림
# ---------------------------------------------------------------------------
def _render_notify_tab() -> None:
    _render_deadline_section()
    st.divider()
    _render_stale_section()


def _render_deadline_section() -> None:
    st.subheader("마감 임박 알림")
    st.caption(f"마감 D-{config.NOTIFY_DAYS_BEFORE} 이내의 공고를 확인하고 Slack으로 알립니다.")

    if st.button("마감 임박 조회", key="notify_query"):
        try:
            with st.spinner("시트 조회 중…"):
                st.session_state.upcoming_jobs = service.find_upcoming(config.NOTIFY_DAYS_BEFORE)
            st.session_state.notify_sent = False
        except Exception as e:
            st.error(f"시트 조회 실패: {e}")
            st.session_state.upcoming_jobs = None

    jobs = st.session_state.upcoming_jobs
    if jobs is None:
        return
    if not jobs:
        st.info("마감 임박 공고가 없습니다.")
        return

    view = [
        {
            "회사": j.get("company", ""),
            "포지션": j.get("position", ""),
            "마감일": j.get("deadline", ""),
            "D-day": "오늘!" if j.get("days_left") == 0 else f"D-{j.get('days_left')}",
        }
        for j in jobs
    ]
    st.dataframe(view, width="stretch", hide_index=True)

    if st.session_state.notify_sent:
        st.success("이미 발송했습니다.")
        return

    if st.button("📨 Slack으로 발송", type="primary", key="notify_send"):
        try:
            ok = service.send_notifications(jobs)
        except Exception as e:
            st.error(f"발송 실패: {e}")
            return
        if ok:
            service.mark_all_notified(jobs)
            st.session_state.notify_sent = True
            st.success(f"Slack 알림 발송 완료! ({len(jobs)}건)")
        else:
            st.error("Slack Webhook URL이 설정되지 않았거나 발송에 실패했습니다.")


def _render_stale_section() -> None:
    st.subheader(f"지원 후 {config.STALE_APPLY_DAYS}일+ 후속 체크")
    st.caption("지원완료 후 진행이 없는 공고를 확인하고 Slack 리마인더를 보냅니다.")

    if st.button("후속 체크 조회", key="stale_query"):
        try:
            with st.spinner("시트 조회 중…"):
                st.session_state.stale_jobs = service.find_stale_applications(config.STALE_APPLY_DAYS)
            st.session_state.stale_sent = False
        except Exception as e:
            st.error(f"시트 조회 실패: {e}")
            st.session_state.stale_jobs = None

    jobs = st.session_state.stale_jobs
    if jobs is None:
        return
    if not jobs:
        st.info("후속 체크 대상 공고가 없습니다.")
        return

    view = [
        {
            "회사": j.get("company", ""),
            "포지션": j.get("position", ""),
            "지원일": j.get("applied_date", ""),
            "경과": f"{j.get('elapsed')}일",
        }
        for j in jobs
    ]
    st.dataframe(view, width="stretch", hide_index=True)

    if st.session_state.stale_sent:
        st.success("이미 발송했습니다.")
        return

    if st.button("📨 후속 리마인더 발송", type="primary", key="stale_send"):
        try:
            ok = service.send_application_reminders(jobs)
        except Exception as e:
            st.error(f"발송 실패: {e}")
            return
        if ok:
            service.mark_all_reminded(jobs)
            st.session_state.stale_sent = True
            st.success(f"후속 리마인더 발송 완료! ({len(jobs)}건)")
        else:
            st.error("Slack Webhook URL이 설정되지 않았거나 발송에 실패했습니다.")


# ---------------------------------------------------------------------------
# 탭 4: 상태 변경
# ---------------------------------------------------------------------------
def _render_status_tab() -> None:
    st.subheader("지원 상태 변경")
    c1, c2 = st.columns([4, 1])
    with c2:
        st.write("")
        if st.button("목록 새로고침", key="status_refresh"):
            st.session_state.status_records = None

    if st.session_state.status_records is None:
        try:
            with st.spinner("공고 목록 불러오는 중…"):
                st.session_state.status_records = service.list_jobs(online=True)
        except Exception as e:
            st.error(f"공고 목록 조회 실패: {e}")
            st.session_state.status_records = []

    records = st.session_state.status_records or []
    options = {}
    for r in records:
        url = r.get("URL", "")
        if not url:
            continue
        options[f"{r.get('회사명', '')} — {r.get('포지션', '')}"] = url

    if not options:
        st.info("상태를 변경할 공고가 없습니다. (Google Sheets에 저장된 공고가 필요합니다)")
        return

    label = st.selectbox("공고 선택", list(options.keys()), key="status_job")
    new_status = st.selectbox(
        "변경할 상태",
        service.VALID_STATUSES,
        format_func=lambda s: service.STATUS_LABELS.get(s, s),
        key="status_value",
    )

    if st.button("상태 적용", type="primary", key="status_apply"):
        url = options[label]
        try:
            with st.spinner("적용 중…"):
                updated = service.change_status(url, new_status)
        except Exception as e:
            st.error(f"상태 변경 실패: {e}")
            return
        if updated:
            st.session_state.jobs_cache = None
            st.session_state.status_records = None
            st.session_state.dash_rows = None
            st.success(f"상태 변경 완료: {service.STATUS_LABELS.get(new_status, new_status)}")
        else:
            st.warning("해당 공고를 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 대시보드 렌더 헬퍼 (플랫폼 현황 / 최근 공고 / D-day 색상 / 인사이트)
# ---------------------------------------------------------------------------
def _lookup_row(rows: list[dict], url: str) -> dict | None:
    for r in rows:
        if str(r.get("URL", "")) == url:
            return r
    return None


def _new_badge() -> str:
    return ("<span style='background:#2563eb;color:#fff;padding:2px 10px;"
            "border-radius:10px;font-size:0.85rem;font-weight:700;'>신규</span>")


def _render_platform_status(platform_counts: list[dict]) -> None:
    if not platform_counts:
        st.caption("데이터 없음")
        return
    view = [
        {"플랫폼": p["platform"], "수집": p["collected"], "신규(주)": p["new_week"],
         "마감": p["closed"], "최근 수집": p["last_collected"] or "—"}
        for p in platform_counts
    ]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_recent_jobs(recent: list[dict], rows: list[dict]) -> None:
    if not recent:
        st.caption("최근 수집한 공고가 없습니다.")
        return
    for i, j in enumerate(recent):
        c1, c2, c3, c4 = st.columns([5, 2, 1.3, 1.3])
        c1.markdown(f"**{j['company']}** · {j['position']}")
        badge = _new_badge() if j["is_new"] else _status_badge(j["status"])
        c2.markdown(badge, unsafe_allow_html=True)
        if c3.button("⭐ 관심", key=f"recent_int_{i}"):
            try:
                service.change_status(j["url"], "interest")
            except Exception as e:
                st.error(f"실패: {e}")
            else:
                st.session_state.dash_rows = None
                st.session_state.jobs_cache = None
                st.session_state.status_records = None
                st.rerun()
        if c4.button("📋 상세", key=f"recent_det_{i}"):
            rec = _lookup_row(rows, j["url"])
            if rec:
                _render_job_detail_dialog(rec)


def _dday_cell_color(v: str) -> str:
    s = str(v)
    if s == "오늘!":
        n = 0
    elif s.startswith("D-"):
        try:
            n = int(s[2:])
        except ValueError:
            return ""
    else:
        return ""
    if n <= 1:
        return "background-color:#B91C1C;color:white;font-weight:700"
    if n <= 3:
        return "background-color:#D97706;color:white;font-weight:700"
    if n <= 5:
        return "background-color:#CA8A04;color:white;font-weight:700"
    return ""


def _render_insights(ins: dict) -> None:
    parts = [f"이번 주 신규 {ins['new_total']}건"]
    if ins["new_top_roles"]:
        roles = " · ".join(f"{r} {c}" for r, c in ins["new_top_roles"])
        parts.append(f"주요 직군 {roles}")
    parts.append(f"마감 임박 {ins['upcoming_count']}건")
    parts.append(f"관심 등록 미지원 {ins['interest_not_applied']}건")
    st.info("🤖 AI 채용 인사이트 — " + " / ".join(parts))
    st.caption("※ 추세 %가 아닌 실제 집계 기준")


# ---------------------------------------------------------------------------
# 탭 0: 대시보드
# ---------------------------------------------------------------------------
def _render_dashboard_tab() -> None:
    st.subheader("대시보드")
    c1, c2 = st.columns([4, 1])
    with c2:
        st.write("")
        if st.button("새로고침", key="dash_refresh"):
            st.session_state.dash_rows = None

    if st.session_state.dash_rows is None:
        try:
            with st.spinner("불러오는 중…"):
                st.session_state.dash_rows = service.list_jobs(online=True)
        except Exception as e:
            st.error(f"시트 조회 실패: {e}")
            st.session_state.dash_rows = []

    rows = st.session_state.dash_rows or []
    if not rows:
        st.info("저장된 공고가 없습니다. '수집' 탭에서 공고를 추가해 보세요.")
        return

    s = service.dashboard_summary(rows)
    labelmap = service.STATUS_LABELS

    # 상단 KPI 4개 (고정)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 수집 공고", f"{s['total']}건", help="시트에 저장된 전체 공고 수")
    k2.metric("신규 공고", f"{s['new_this_week']}건", help="최근 7일 내 등록")
    k3.metric("마감 임박", f"{len(s['upcoming'])}건", help="확정 마감 D-7 이내")
    k4.metric("상시 채용", f"{s['rolling']}건", help="마감유형이 상시(rolling)")

    # 플랫폼별 수집 현황
    st.divider()
    st.markdown("##### 플랫폼별 수집 현황")
    _render_platform_status(s["platform_counts"])

    # 직군별 / 상태별(지원) 분포
    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.markdown("##### 직군별 분포")
        if s["role_counts"]:
            df = pd.DataFrame(
                {"직군": list(s["role_counts"].keys()), "건수": list(s["role_counts"].values())}
            ).set_index("직군")
            st.bar_chart(df, horizontal=True)
        else:
            st.caption("데이터 없음")
    with cB:
        st.markdown("##### 상태별(지원) 분포")
        sc_labeled = {labelmap.get(k, k): v for k, v in s["status_counts"].items()}
        df2 = pd.DataFrame(
            {"상태": list(sc_labeled.keys()), "건수": list(sc_labeled.values())}
        ).set_index("상태")
        st.bar_chart(df2, horizontal=True)

    # 최근 수집 공고
    st.divider()
    st.markdown("##### 최근 수집 공고")
    _render_recent_jobs(s["recent"], rows)

    # 마감 임박 (D-day 색상)
    st.divider()
    st.markdown("##### 마감 임박 (D-7)")
    if s["upcoming"]:
        view = [
            {
                "회사": u["company"],
                "직무": u["position"],
                "마감일": u["deadline"],
                "D-day": "오늘!" if u["days_left"] == 0 else f"D-{u['days_left']}",
                "상태": labelmap.get(u["status"], u["status"]),
            }
            for u in s["upcoming"]
        ]
        sty = pd.DataFrame(view).style.map(_dday_cell_color, subset=["D-day"])
        st.dataframe(sty, width="stretch", hide_index=True)
    else:
        st.caption("마감 임박(D-7) 공고가 없습니다.")

    # AI 인사이트
    st.divider()
    _render_insights(s["insights"])


# ---------------------------------------------------------------------------
# 메인 — 좌측 사이드바: 브랜드(상단) → 메뉴(일반 링크) → 환경 상태(최하단)
# ---------------------------------------------------------------------------
_pages = [
    st.Page(_render_dashboard_tab, title="대시보드", icon="📊", url_path="dashboard", default=True),
    st.Page(_render_collect_tab, title="수집", icon="➕", url_path="collect"),
    st.Page(_render_list_tab, title="목록", icon="📋", url_path="list"),
    st.Page(_render_notify_tab, title="마감 알림", icon="🔔", url_path="notify"),
    st.Page(_render_status_tab, title="지원상태 변경", icon="✏️", url_path="status"),
]
_nav = st.navigation(_pages, position="hidden")  # 기본 메뉴 숨김 → 아래 page_link로 직접 배치

with st.sidebar:
    # 상단 고정: 브랜드 + 메뉴
    st.markdown("## 💼 JobMate AI")
    st.caption("채용 공고 수집·관리·알림")
    st.divider()
    st.page_link(_pages[0])           # 대시보드
    st.markdown("**채용공고**")
    st.page_link(_pages[1])           # 수집
    st.page_link(_pages[2])           # 목록
    st.markdown("**알림 · 관리**")
    st.page_link(_pages[3])           # 마감 알림
    st.page_link(_pages[4])           # 지원상태 변경
    # 하단 고정: 환경 상태 (CSS margin-top:auto로 사이드바 최하단)
    with st.container(key="sidebar_health"):
        st.divider()
        _render_health_content()

# 선택된 페이지를 메인 영역에 렌더
_nav.run()
