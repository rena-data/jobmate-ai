"""규칙 기반 직군 분류.

position / 주요업무 텍스트의 키워드로 직군 카테고리를 부여한다.
Gemini 불필요(무료·즉시·오프라인), 시트 스키마 변경 없이 온더플라이로 계산되어
기존에 저장된 공고에도 바로 적용된다.
"""

from __future__ import annotations

import re

# (카테고리, 키워드 정규식 리스트) — 위에서부터 먼저 매칭(겹침은 우선순위로 해소).
# 짧은 영어 약어는 \b 경계로 오매칭 방지. 한글은 \s* 로 공백 변형 흡수.
_RULES: list[tuple[str, list[str]]] = [
    ("AI/ML", [r"\bAI\b", r"인공지능", r"머신러닝", r"machine\s*learning", r"\bML\b",
               r"딥러닝", r"deep\s*learning", r"\bLLM\b", r"데이터\s*사이언", r"data\s*scien",
               r"\bMLOps\b", r"생성형", r"프롬프트"]),
    ("데이터", [r"데이터\s*분석", r"data\s*analyst", r"데이터\s*엔지니", r"data\s*engineer",
              r"\bBI\b", r"analytics", r"빅데이터", r"\bDBA\b", r"데이터\s*플랫폼", r"데이터\s*리서치"]),
    ("백엔드", [r"백\s?엔드", r"back[\s-]?end", r"서버\s*개발", r"\bserver\b", r"\bAPI\b",
              r"spring", r"\bnode", r"django", r"golang", r"\bkotlin\b"]),
    ("프론트엔드", [r"프론트", r"front[\s-]?end", r"\breact\b", r"\bvue\b", r"angular",
                r"웹\s*퍼블", r"\bUI\s*개발"]),
    ("모바일", [r"안드로이드", r"android", r"\biOS\b", r"모바일", r"flutter",
              r"react\s*native", r"\bswift\b"]),
    ("DevOps/인프라", [r"devops", r"인프라", r"\bSRE\b", r"클라우드", r"\bcloud\b",
                     r"플랫폼\s*엔지니", r"kubernetes", r"쿠버네티스", r"시스템\s*엔지니"]),
    ("PM/기획", [r"\bPM\b", r"\bPO\b", r"프로덕트\s*매니", r"product\s*manager",
               r"product\s*owner", r"서비스\s*기획", r"기획자", r"프로덕트\s*오너", r"사업\s*기획"]),
    ("디자인", [r"디자이너", r"designer", r"\bUX\b", r"\bUI\s*디자인", r"\bBX\b",
              r"그래픽\s*디자", r"프로덕트\s*디자"]),
    ("마케팅/사업", [r"마케팅", r"marketing", r"사업\s*개발", r"\bBD\b", r"그로스", r"growth",
                  r"퍼포먼스", r"콘텐츠\s*마케", r"브랜드\s*마케", r"세일즈", r"\bsales\b",
                  r"파트너십", r"제휴"]),
    ("개발(기타)", [r"개발자", r"engineer", r"엔지니어", r"developer", r"프로그래머", r"소프트웨어"]),
]

# 분류 가능한 전체 카테고리(마지막은 폴백)
CATEGORIES: list[str] = [name for name, _ in _RULES] + ["기타"]


def classify_role(position: str, responsibilities: str = "") -> str:
    """포지션(+주요업무)에서 직군 카테고리를 추정. 매칭 없으면 '기타'."""
    text = f"{position or ''} {responsibilities or ''}"
    for name, patterns in _RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return name
    return "기타"
