"""검색기 순수 로직 테스트 — 네트워크 無.

extract_detail_urls(상대/절대 href → 정규화 상세 URL, dedup, limit)와
각 검색기의 id_pattern/url_template가 해당 파서의 can_handle과 일치하는지 검증.
실행: python tests/test_searchers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from searchers.jobkorea import JobkoreaSearcher
from searchers.saramin import SaraminSearcher
from searchers.wanted import WantedSearcher
from parsers.jobkorea import JobkoreaParser
from parsers.saramin import SaraminParser
from parsers.wanted import WantedParser


def test_jobkorea_extract():
    s = JobkoreaSearcher()
    hrefs = [
        "/Recruit/GI_Read/49350299?Oem_Code=C1&stext=AI",   # 상대 + 추적 파라미터
        "/Recruit/GI_Read/49350299?listno=3",                # 같은 id 중복
        "https://www.jobkorea.co.kr/Recruit/GI_Read/49386935",
        "/Recruit/Co_Read/123",                              # 회사 페이지 — 제외
        None, "",                                            # 빈 값 — 무시
        "/Search/?stext=AI",                                 # 검색 링크 — 제외
    ]
    assert s._matches(hrefs, 10) == [
        "https://www.jobkorea.co.kr/Recruit/GI_Read/49350299",
        "https://www.jobkorea.co.kr/Recruit/GI_Read/49386935",
    ], s._matches(hrefs, 10)
    print("✅ jobkorea extract")


def test_saramin_extract():
    s = SaraminSearcher()
    hrefs = [
        "/zf_user/jobs/relay/view?view_type=search&rec_idx=12345678&searchword=AI",
        "/zf_user/jobs/relay/view?rec_idx=12345678",         # 같은 id 중복
        "/zf_user/jobs/relay/view?rec_idx=87654321",
        "/zf_user/company/view?csn=1",                       # 회사 — 제외
    ]
    assert s._matches(hrefs, 10) == [
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=12345678",
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=87654321",
    ], s._matches(hrefs, 10)
    print("✅ saramin extract")


def test_wanted_extract():
    s = WantedSearcher()
    hrefs = [
        "/wd/65223?utm_source=x",
        "/wd/65223",                                         # 같은 id 중복
        "https://www.wanted.co.kr/wd/70001",
        "/company/123",                                      # 제외
        "/wdlist?query=AI",                                  # 목록 — 제외
    ]
    assert s._matches(hrefs, 10) == [
        "https://www.wanted.co.kr/wd/65223",
        "https://www.wanted.co.kr/wd/70001",
    ], s._matches(hrefs, 10)
    print("✅ wanted extract")


def test_limit_and_dedup():
    s = JobkoreaSearcher()
    hrefs = [f"/Recruit/GI_Read/{i}" for i in range(20)] + ["/Recruit/GI_Read/0"]
    urls = s._matches(hrefs, 5)
    assert len(urls) == 5, urls                              # limit 적용
    assert urls[0].endswith("/GI_Read/0"), urls[0]           # 순서 보존
    print("✅ limit & dedup")


def test_templates_match_parser_can_handle():
    """검색기가 만든 URL을 반드시 대응 파서가 수집할 수 있어야 한다 (계약)."""
    assert WantedParser().can_handle(WantedSearcher().URL_TEMPLATE.format(id="1"))
    assert SaraminParser().can_handle(SaraminSearcher().URL_TEMPLATE.format(id="1"))
    assert JobkoreaParser().can_handle(JobkoreaSearcher().URL_TEMPLATE.format(id="1"))
    print("✅ 검색기 URL ↔ 파서 can_handle 계약")


if __name__ == "__main__":
    test_jobkorea_extract()
    test_saramin_extract()
    test_wanted_extract()
    test_limit_and_dedup()
    test_templates_match_parser_can_handle()
    print("모든 검증 통과")
