"""원티드/사람인 전용 파서 엣지케이스 테스트.

Sheets 저장 없이 파싱 결과만 확인합니다.
"""
from __future__ import annotations

import asyncio
import time

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# 앱 소스(src/)를 import 경로에 추가 — tests/에서 실행해도 parsers를 찾도록
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from parsers.wanted import WantedParser
from parsers.saramin import SaraminParser
from parsers.base import canonicalize_url

console = Console()

WANTED_URLS = [
    ("당근마켓 DS", "https://www.wanted.co.kr/wd/65223"),
    ("핑크퐁 인턴", "https://www.wanted.co.kr/wd/256524"),
    ("토스뱅크 DA", "https://www.wanted.co.kr/wd/195143"),
]

SARAMIN_URLS = [
    ("현대모비스 신입", "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=53186193"),
    ("업스테이지 PO", "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=53235620"),
    ("사람인 데이터", "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=53685800"),
]


def score_post(post) -> tuple[int, int, list[str]]:
    """파싱 품질 점수 계산. (채워진수, 전체, 누락필드)"""
    fields = {
        "회사명": post.company,
        "업종": post.company_type,
        "포지션": post.position,
        "주요업무": post.responsibilities,
        "자격요건": post.requirements,
        "우대사항": post.preferred,
        "마감일": post.deadline_raw,
    }
    filled = sum(1 for v in fields.values() if v)
    missing = [k for k, v in fields.items() if not v]
    return filled, len(fields), missing


def display_result(name: str, post, elapsed: float):
    """파싱 결과 출력."""
    filled, total, missing = score_post(post)
    score_style = "green" if filled >= 5 else "yellow" if filled >= 3 else "red"

    table = Table(title=f"[{score_style}][{filled}/{total}][/{score_style}] {name}")
    table.add_column("항목", style="bold", width=15)
    table.add_column("내용", width=80)

    rows = [
        ("회사명", post.company),
        ("업종", post.company_type),
        ("직원수", post.employee_count),
        ("회사설명", post.company_description),
        ("포지션", post.position),
        ("주요업무", (post.responsibilities or "")[:150]),
        ("자격요건", (post.requirements or "")[:150]),
        ("우대사항", (post.preferred or "")[:150]),
        ("마감일(원본)", post.deadline_raw),
        ("마감일(파싱)", post.deadline_parsed or ""),
        ("마감유형", post.deadline_type.value),
    ]

    for label, value in rows:
        style = "" if value and value not in ("unknown",) else "dim"
        table.add_row(label, value or "[미확인]", style=style)

    table.add_row("소요시간", f"{elapsed:.1f}초", style="dim")
    if missing:
        table.add_row("누락 필드", ", ".join(missing), style="red")
    console.print(table)
    console.print()


async def test_parser(parser, name: str, url: str) -> dict:
    """단일 URL 파싱 테스트."""
    canonical = canonicalize_url(url)
    console.print(f"[cyan]테스트: {name}[/cyan]")

    start = time.time()
    try:
        post = await parser.parse(canonical)
        elapsed = time.time() - start
        display_result(name, post, elapsed)
        filled, total, missing = score_post(post)
        return {"name": name, "success": True, "filled": filled, "total": total, "missing": missing, "elapsed": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        console.print(f"[red]실패 ({name}): {e}[/red]\n")
        return {"name": name, "success": False, "error": str(e), "elapsed": elapsed}


async def main():
    console.print(Panel(
        "[bold]원티드/사람인 전용 파서 엣지케이스 테스트[/bold]\n"
        f"[dim]원티드 {len(WANTED_URLS)}건 + 사람인 {len(SARAMIN_URLS)}건[/dim]",
        border_style="cyan",
    ))

    results = []

    # 원티드 테스트
    console.print("\n[bold magenta]== 원티드 파서 ==[/bold magenta]\n")
    wanted = WantedParser()
    for name, url in WANTED_URLS:
        r = await test_parser(wanted, name, url)
        results.append(("원티드", r))

    # 사람인 테스트
    console.print("\n[bold magenta]== 사람인 파서 ==[/bold magenta]\n")
    saramin = SaraminParser()
    for name, url in SARAMIN_URLS:
        r = await test_parser(saramin, name, url)
        results.append(("사람인", r))

    # 요약
    console.print(Panel("[bold]테스트 요약[/bold]", border_style="green"))
    summary = Table()
    summary.add_column("파서", style="bold")
    summary.add_column("공고")
    summary.add_column("결과")
    summary.add_column("점수")
    summary.add_column("누락")
    summary.add_column("시간")

    for parser_name, r in results:
        if r["success"]:
            score = f"{r['filled']}/{r['total']}"
            score_style = "green" if r["filled"] >= 5 else "yellow" if r["filled"] >= 3 else "red"
            status = f"[{score_style}]OK[/{score_style}]"
            missing = ", ".join(r["missing"]) if r["missing"] else "-"
        else:
            status = "[red]FAIL[/red]"
            score = "-"
            missing = r.get("error", "")[:40]

        summary.add_row(parser_name, r["name"], status, score, missing, f"{r['elapsed']:.1f}초")

    console.print(summary)

    total = len(results)
    ok = sum(1 for _, r in results if r["success"])
    high = sum(1 for _, r in results if r["success"] and r["filled"] >= 5)
    console.print(f"\n[bold]결과: {ok}/{total} 성공, 고품질(5+): {high}/{total}[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
