"""dashboard_summary 집계 테스트 (네트워크 無, 순수 함수).

상태 7종 + 레거시 'closed' 혼합, 상시채용/마감임박/이번주 신규 집계 검증.
실행: python tests/test_dashboard_summary.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from service import dashboard_summary, VALID_STATUSES, STATUS_LABELS, platform_of

TODAY = date.today().isoformat()
SOON = (date.today() + timedelta(days=3)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
OLD = (date.today() - timedelta(days=30)).isoformat()
PAST = (date.today() - timedelta(days=5)).isoformat()


def test_platform_of():
    assert platform_of("https://www.wanted.co.kr/wd/123") == "원티드"
    assert platform_of("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1") == "사람인"
    assert platform_of("https://www.jobkorea.co.kr/Recruit/GI_Read/123") == "잡코리아"
    assert platform_of("https://groupby.kr/positions/4") == "그룹바이"
    assert platform_of("https://example.com/job/1") == "기타"
    assert platform_of("") == "기타"
    print("✅ platform_of")


def _row(status="interest", dtype="unknown", deadline="", created="", position="백엔드 엔지니어", url="u"):
    return {
        "URL": url, "회사명": "C", "업종": "", "직원수": "", "회사설명": "",
        "포지션": position, "주요업무": "", "자격요건": "", "우대사항": "",
        "마감일(원본)": "", "마감일(파싱)": deadline, "마감유형": dtype,
        "등록일": created, "상태": status, "비고": "",
    }


ROWS = [
    _row(status="interest", created=TODAY),               # interest + 이번주 신규
    _row(status="applied"),
    _row(status="document_pass"),
    _row(status="interview"),
    _row(status="final_pass"),
    _row(status="rejected"),
    _row(status="hold"),
    _row(status="closed"),                                # 레거시 → 카운트 제외
    _row(status="interest", dtype="rolling"),             # interest + 상시채용
    _row(status="interest", dtype="fixed", deadline=SOON),  # interest + 마감임박(D-3)
]


def main() -> None:
    s = dashboard_summary(ROWS)

    # status_counts 키는 VALID_STATUSES와 정확히 일치 (동적 생성, 레거시 closed 제외)
    assert set(s["status_counts"].keys()) == set(VALID_STATUSES), s["status_counts"].keys()
    assert "closed" not in s["status_counts"], "레거시 closed가 카운트에 포함됨"

    assert s["total"] == 10, s["total"]
    assert s["status_counts"]["interest"] == 3, s["status_counts"]
    for st_key in ("applied", "document_pass", "interview", "final_pass", "rejected", "hold"):
        assert s["status_counts"][st_key] == 1, (st_key, s["status_counts"])

    assert s["rolling"] == 1, s["rolling"]
    assert s["new_this_week"] == 1, s["new_this_week"]

    assert len(s["upcoming"]) == 1, s["upcoming"]
    assert s["upcoming"][0]["days_left"] == 3, s["upcoming"][0]

    # 모든 상태가 한글 라벨을 가진다
    assert all(k in STATUS_LABELS for k in VALID_STATUSES)

    print(f"✅ dashboard_summary: total={s['total']}, "
          f"interest={s['status_counts']['interest']}, rolling={s['rolling']}, "
          f"new={s['new_this_week']}, upcoming={len(s['upcoming'])}")
    print("모든 검증 통과")


def test_platform_recent_insights():
    rows = [
        _row(url="https://www.wanted.co.kr/wd/1", created=TODAY, position="백엔드 엔지니어", status="interest"),
        _row(url="https://www.wanted.co.kr/wd/2", created=YESTERDAY, position="AI Engineer", status="applied"),
        _row(url="https://www.saramin.co.kr/x?rec_idx=3", created=OLD, position="프론트엔드 개발자",
             status="interest", dtype="fixed", deadline=PAST),
        _row(url="https://groupby.kr/positions/4", created=TODAY, position="데이터 분석가", status="interest"),
    ]
    s = dashboard_summary(rows)

    pc = {p["platform"]: p for p in s["platform_counts"]}
    assert pc["원티드"]["collected"] == 2, pc
    assert pc["사람인"]["collected"] == 1, pc
    assert pc["그룹바이"]["collected"] == 1, pc
    assert pc["원티드"]["new_week"] == 2, pc          # TODAY + YESTERDAY
    assert pc["사람인"]["closed"] == 1, pc            # PAST 확정 마감 지남
    assert pc["원티드"]["last_collected"] == TODAY, pc

    assert len(s["recent"]) == 4, s["recent"]
    assert s["recent"][0]["created"] == TODAY, s["recent"][0]
    assert s["recent"][0]["is_new"] is True

    ins = s["insights"]
    assert ins["new_total"] == s["new_this_week"]
    assert ins["upcoming_count"] == len(s["upcoming"])
    assert ins["interest_not_applied"] == s["status_counts"]["interest"]
    print("✅ platform_recent_insights")


if __name__ == "__main__":
    test_platform_of()
    main()
    test_platform_recent_insights()
