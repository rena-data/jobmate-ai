"""Gemini 폴백 파서 테스트 스크립트.

Phase 1: 페이지 수집 + 텍스트 추출 (Gemini 없이)
Phase 2: Gemini 파싱 (쿼터 가용 시)
"""
from __future__ import annotations

import asyncio
import sys
import time

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from parsers.fallback import FallbackParser
from parsers.base import canonicalize_url

console = Console()

TEST_URLS = [
    ("잡코리아", "https://www.jobkorea.co.kr/Recruit/GI_Read/46910777"),
    ("점핏", "https://jumpit.saramin.co.kr/position/53070423"),
    ("로켓펀치", "https://www.rocketpunch.com/jobs/140348"),
]


async def test_fetch_and_extract(parser: FallbackParser, name: str, url: str) -> dict:
    """Phase 1: 페이지 수집 + 텍스트 추출만 테스트."""
    canonical = canonicalize_url(url)
    console.print(f"\n[bold cyan]--- {name} ---[/bold cyan]")
    console.print(f"[dim]{canonical}[/dim]")

    # 1) 페이지 수집
    console.print("[cyan]  1) Playwright 페이지 수집...[/cyan]")
    start = time.time()
    try:
        html = await parser._fetch_page(canonical)
        fetch_time = time.time() - start
        html_len = len(html)
        console.print(f"[green]     HTML 수집 완료: {html_len:,}자 ({fetch_time:.1f}초)[/green]")
    except Exception as e:
        console.print(f"[red]     페이지 수집 실패: {e}[/red]")
        return {"name": name, "fetch": False, "extract": False, "error": str(e)}

    # 2) 텍스트 추출 (trafilatura)
    console.print("[cyan]  2) trafilatura 텍스트 추출...[/cyan]")
    try:
        text = parser._extract_main_content(html)
        text_len = len(text)
        console.print(f"[green]     텍스트 추출 완료: {text_len:,}자[/green]")

        # 품질 체크: 핵심 키워드 존재 여부
        keywords = ["채용", "모집", "경력", "자격", "우대", "업무", "담당", "지원", "마감"]
        found = [kw for kw in keywords if kw in text]
        console.print(f"[dim]     채용 키워드 감지: {', '.join(found) if found else '없음'} ({len(found)}/{len(keywords)})[/dim]")

        # 본문 미리보기 (앞 300자)
        preview = text[:300].replace("\n", " ")
        console.print(f"[dim]     미리보기: {preview}...[/dim]")

        return {
            "name": name,
            "fetch": True,
            "extract": True,
            "html_len": html_len,
            "text_len": text_len,
            "keywords_found": len(found),
            "fetch_time": fetch_time,
            "text": text,
        }
    except Exception as e:
        console.print(f"[red]     텍스트 추출 실패: {e}[/red]")
        return {"name": name, "fetch": True, "extract": False, "error": str(e)}


async def test_gemini(parser: FallbackParser, text: str, name: str) -> dict | None:
    """Phase 2: Gemini 파싱 테스트."""
    console.print(f"[cyan]  3) Gemini 구조화 추출...[/cyan]")
    try:
        data = parser._extract_with_gemini(text)
        filled = sum(1 for v in data.values() if v)
        total = len(data)
        console.print(f"[green]     Gemini 추출 완료: {filled}/{total} 필드[/green]")
        for k, v in data.items():
            display = (str(v)[:80] + "...") if len(str(v)) > 80 else str(v)
            style = "" if v else "dim"
            console.print(f"[{style}]     {k}: {display}[/{style}]")
        return {"name": name, "gemini": True, "data": data, "filled": filled, "total": total}
    except Exception as e:
        console.print(f"[red]     Gemini 실패: {e}[/red]")
        return {"name": name, "gemini": False, "error": str(e)}


async def main():
    parser = FallbackParser()
    use_gemini = "--gemini" in sys.argv

    mode = "Phase 1+2 (Gemini 포함)" if use_gemini else "Phase 1 (수집+추출만)"
    console.print(Panel(
        f"[bold]Gemini 폴백 파서 테스트[/bold]\n"
        f"[dim]모드: {mode}  |  대상: {len(TEST_URLS)}개 사이트[/dim]\n"
        f"[dim]Gemini 포함 테스트: python test_fallback.py --gemini[/dim]",
        border_style="cyan",
    ))

    results = []
    for i, (name, url) in enumerate(TEST_URLS):
        result = await test_fetch_and_extract(parser, name, url)
        results.append(result)

        # Gemini 테스트
        if use_gemini and result.get("extract") and result.get("text"):
            gemini_result = await test_gemini(parser, result["text"], name)
            if gemini_result:
                result["gemini_result"] = gemini_result
            # Gemini 쿼터 보호
            if i < len(TEST_URLS) - 1:
                console.print("[dim]  Gemini 쿼터 보호: 5초 대기...[/dim]")
                await asyncio.sleep(5)

    # 요약
    console.print()
    console.print(Panel("[bold]테스트 요약[/bold]", border_style="green"))
    summary = Table()
    summary.add_column("사이트", style="bold")
    summary.add_column("페이지 수집")
    summary.add_column("텍스트 추출")
    summary.add_column("HTML 크기")
    summary.add_column("텍스트 크기")
    summary.add_column("키워드")
    if use_gemini:
        summary.add_column("Gemini")

    for r in results:
        fetch = "[green]OK[/green]" if r.get("fetch") else "[red]FAIL[/red]"
        extract = "[green]OK[/green]" if r.get("extract") else "[red]FAIL[/red]"
        html_len = f"{r.get('html_len', 0):,}" if r.get("fetch") else "-"
        text_len = f"{r.get('text_len', 0):,}" if r.get("extract") else "-"
        keywords = f"{r.get('keywords_found', 0)}/9" if r.get("extract") else "-"

        row = [r["name"], fetch, extract, html_len, text_len, keywords]
        if use_gemini:
            gr = r.get("gemini_result", {})
            if gr.get("gemini"):
                row.append(f"[green]{gr['filled']}/{gr['total']}[/green]")
            elif gr:
                row.append("[red]FAIL[/red]")
            else:
                row.append("-")
        summary.add_row(*row)

    console.print(summary)

    success = sum(1 for r in results if r.get("extract"))
    console.print(f"\n[bold]수집+추출 성공: {success}/{len(results)}[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
