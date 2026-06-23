"""auto_collect 오케스트레이션 테스트 — 네트워크 無 (검색기/collect/시트 몽키패치).

2단계 중복 제거(URL + 회사+직무, 시트 기존분 + 이번 실행 내), 검색기 fail-soft,
resolve_keywords 폴백, _job_key 정규화를 검증.
실행: python tests/test_auto_collect.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import service
from service import CollectResult
from parsers.base import JobPost


def test_job_key_normalization():
    # 공백 축약 + 소문자 → 같은 키
    assert service._job_key("Toss", "AI Engineer") == service._job_key(" toss ", "ai  engineer")
    # 회사 같아도 직무 다르면 다른 키
    assert service._job_key("토스", "백엔드") != service._job_key("토스", "프론트엔드")
    # 둘 다 비면 None (중복판정 제외)
    assert service._job_key("", "") is None
    print("✅ _job_key 정규화")


def test_two_stage_dedup():
    # 기존 시트: URL=.../sheet, (기존회사, 기존직무)
    existing = [{"URL": "https://ex.com/sheet", "회사명": "기존회사", "포지션": "기존직무"}]
    service.sheets.get_all_posts = lambda: list(existing)

    cands = [
        "https://ex.com/new",      # 신규
        "https://ex.com/cached",   # 캐시 중복(URL)
        "https://ex.com/sheet",    # 시트 URL 중복
        "https://ex.com/dupjob",   # URL은 새것이나 (기존회사,기존직무) → 회사+직무 중복
        "https://ex.com/fail",     # 수집 실패
        "https://ex.com/new2a",    # 신규 (중복회사, 중복직무)
        "https://ex.com/new2b",    # 위와 동일 회사+직무 → 이번 실행 내 중복
    ]
    posts = {
        "https://ex.com/new": ("새회사", "새직무"),
        "https://ex.com/dupjob": ("기존회사", "기존직무"),
        "https://ex.com/new2a": ("중복회사", "중복직무"),
        "https://ex.com/new2b": ("중복회사", "중복직무"),
    }
    saved: list[tuple] = []

    service.discover = lambda kw, plat, limit: list(cands)
    service.is_cached = lambda url: url == "https://ex.com/cached"

    def fake_collect(url):
        if url == "https://ex.com/fail":
            return CollectResult(canonical_url=url, post=None, error="boom")
        c, p = posts[url]
        return CollectResult(canonical_url=url, post=JobPost(url=url, company=c, position=p))

    service.collect = fake_collect
    service.save_auto = lambda post, *, keyword, platform: saved.append(post.url)

    res = service.auto_collect(["AI"], ["원티드"], 10)

    assert res.discovered == 7, res.discovered
    assert res.new == 2, res.new            # new, new2a
    assert res.duplicate == 4, res.duplicate  # cached, sheet, dupjob, new2b
    assert res.failed == 1, res.failed
    assert saved == ["https://ex.com/new", "https://ex.com/new2a"], saved
    print("✅ 2단계 중복 제거 (URL + 회사+직무, 시트 기존분 + 실행 내)")


def test_searcher_error_failsoft():
    service.sheets.get_all_posts = lambda: []

    def boom(kw, plat, limit):
        raise RuntimeError("검색 실패")

    service.discover = boom
    res = service.auto_collect(["AI"], ["사람인"], 5)
    assert res.discovered == 0 and res.new == 0, res
    assert len(res.errors) == 1 and "사람인" in res.errors[0], res.errors
    print("✅ 검색기 오류 fail-soft")


def test_resolve_keywords_fallback():
    service.sheets.get_keywords = lambda: []
    assert service.resolve_keywords() == list(service.config.AUTOCOLLECT_KEYWORDS)

    service.sheets.get_keywords = lambda: ["커스텀1", "커스텀2"]
    assert service.resolve_keywords() == ["커스텀1", "커스텀2"]

    def boom():
        raise RuntimeError("no sheet")

    service.sheets.get_keywords = boom
    assert service.resolve_keywords() == list(service.config.AUTOCOLLECT_KEYWORDS)
    print("✅ resolve_keywords 폴백 (시트 우선 → config)")


if __name__ == "__main__":
    test_job_key_normalization()
    test_two_stage_dedup()
    test_searcher_error_failsoft()
    test_resolve_keywords_fallback()
    print("모든 검증 통과")
