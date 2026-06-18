"""직군 분류 규칙 테스트.

실행: python tests/test_classify.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from classify import classify_role, CATEGORIES

CASES = [
    ("데이터 사이언티스트, 디시젼", "AI/ML"),
    ("AI Engineer", "AI/ML"),
    ("데이터 분석가(Data Analyst)", "데이터"),
    ("백엔드 엔지니어", "백엔드"),
    ("Backend Engineer", "백엔드"),
    ("프론트엔드 개발자 (React)", "프론트엔드"),
    ("iOS 개발자", "모바일"),
    ("DevOps 엔지니어", "DevOps/인프라"),
    ("Product Manager", "PM/기획"),
    ("프로덕트 디자이너", "디자인"),
    ("주니어 파트너십 사업개발 매니저", "마케팅/사업"),
    ("소프트웨어 엔지니어", "개발(기타)"),
    ("고객 서비스 매니저", "기타"),
]


def main() -> None:
    ok = 0
    for position, expected in CASES:
        got = classify_role(position)
        mark = "✅" if got == expected else "❌"
        if got == expected:
            ok += 1
        print(f"{mark} {position!r:42} → {got:14} (기대 {expected})")
    print(f"\n{ok}/{len(CASES)} 통과")
    assert all(c in CATEGORIES for _, c in CASES), "기대 카테고리가 CATEGORIES에 없음"
    assert ok == len(CASES), f"{len(CASES) - ok}건 실패"


if __name__ == "__main__":
    main()
