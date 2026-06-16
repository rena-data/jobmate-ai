"""JobMate AI — Streamlit 웹 UI.

CLI(main.py)와 동일한 로직(service.py)을 웹에서 제공한다.
service만 import한다 (asyncio/playwright/parser 직접 import 금지).
실행: streamlit run app.py
"""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st

import config
import service

st.set_page_config(page_title="JobMate AI", page_icon="💼", layout="wide")


# ---------------------------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------------------------
DEFAULTS = {
    "pending_post": None,      # 방금 수집한 JobPost(dict). 수집→저장/취소 사이 유지
    "pending_meta": None,      # parser_name / used_fallback / robots_msg / warnings
    "last_saved": None,        # 저장 완료 토스트 메시지
    "upcoming_jobs": None,     # 마감 조회 결과 (발송 버튼 재실행 대비)
    "notify_sent": False,      # 중복 발송 가드
    "jobs_cache": None,        # 목록 탭 캐시
    "jobs_cache_online": None, # 목록 탭 캐시 소스 (True=온라인)
    "status_records": None,    # 상태 변경 탭 공고 목록 캐시
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
# 사이드바: 환경 상태 (읽기 전용)
# ---------------------------------------------------------------------------
def _render_sidebar() -> None:
    with st.sidebar:
        st.header("환경 상태")
        h = service.health()
        labels = {
            "gemini": "Gemini API Key",
            "slack": "Slack Webhook",
            "sheets_id": "Google Sheets ID",
            "credentials_file": "credentials.json",
        }
        for key, label in labels.items():
            if h.get(key):
                st.success(f"{label} 설정됨")
            else:
                st.error(f"{label} 없음")
        st.caption("값은 `.env` / `credentials.json`에서 직접 관리합니다.")


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
        view = [
            {
                "회사": r.get("회사명", ""),
                "포지션": r.get("포지션", ""),
                "마감일": r.get("마감일(파싱)", "") or r.get("마감일(원본)", ""),
                "상태": r.get("상태", ""),
                "등록일": r.get("등록일", ""),
            }
            for r in records
        ]
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


# ---------------------------------------------------------------------------
# 탭 3: 마감 알림
# ---------------------------------------------------------------------------
def _render_notify_tab() -> None:
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
    new_status = st.selectbox("변경할 상태", service.VALID_STATUSES, key="status_value")

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
            st.success(f"상태 변경 완료: {new_status}")
        else:
            st.warning("해당 공고를 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
_render_sidebar()
st.title("JobMate AI · 채용 공고 수집/관리")

tab_collect, tab_list, tab_notify, tab_status = st.tabs(
    ["수집", "목록", "마감 알림", "상태 변경"]
)
with tab_collect:
    _render_collect_tab()
with tab_list:
    _render_list_tab()
with tab_notify:
    _render_notify_tab()
with tab_status:
    _render_status_tab()
