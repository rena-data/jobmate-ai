from __future__ import annotations

import asyncio
import json
import time

import typer
from rich.console import Console
from rich.table import Table

import config
from parsers.base import canonicalize_url, check_robots_txt, JobPost
from parsers.wanted import WantedParser
from parsers.fallback import FallbackParser
import sheets
import slack

app = typer.Typer(help="JobMate AI - 채용 공고 자동 수집/관리 CLI")
console = Console()

# 파서 등록 (우선순위 순)
PARSERS = [
    WantedParser(),
    FallbackParser(),  # 항상 마지막 (폴백)
]


def _load_cache() -> list[dict]:
    try:
        with open(config.CACHE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_cache(cache: list[dict]) -> None:
    with open(config.CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _is_cached(url: str) -> bool:
    cache = _load_cache()
    return any(item["url"] == url for item in cache)


def _add_to_cache(post: JobPost) -> None:
    cache = _load_cache()
    cache.append({
        "url": post.url,
        "company": post.company,
        "position": post.position,
        "last_seen": post.created_at,
    })
    _save_cache(cache)


def _display_preview(post: JobPost) -> None:
    """크롤링 결과 미리보기 테이블."""
    table = Table(title="공고 수집 결과", show_header=True, header_style="bold cyan")
    table.add_column("항목", style="bold", width=15)
    table.add_column("내용", width=80)

    table.add_row("회사명", post.company or "[dim]미확인[/dim]")
    table.add_row("업종", post.company_type or "[dim]미확인[/dim]")
    table.add_row("직원수", post.employee_count or "[dim]미확인[/dim]")
    table.add_row("회사설명", post.company_description or "[dim]미확인[/dim]")
    table.add_row("포지션", post.position or "[dim]미확인[/dim]")
    table.add_row("주요업무", _truncate(post.responsibilities, 200) or "[dim]미확인[/dim]")
    table.add_row("자격요건", _truncate(post.requirements, 200) or "[dim]미확인[/dim]")
    table.add_row("우대사항", _truncate(post.preferred, 200) or "[dim]미확인[/dim]")
    table.add_row("마감일(원본)", post.deadline_raw or "[dim]미확인[/dim]")
    table.add_row("마감일(파싱)", post.deadline_parsed or "[dim]미확인[/dim]")
    table.add_row("마감유형", post.deadline_type.value)
    table.add_row("URL", post.url)

    console.print(table)


def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


@app.command()
def add(
    url: str = typer.Argument(..., help="채용 공고 URL"),
    skip_confirm: bool = typer.Option(False, "--yes", "-y", help="확인 없이 바로 저장"),
):
    """채용 공고 URL을 분석하여 Google Sheets에 저장합니다."""
    canonical = canonicalize_url(url)

    # 중복 체크
    if _is_cached(canonical):
        console.print(f"[yellow]이미 등록된 URL입니다: {canonical}[/yellow]")
        raise typer.Exit()

    # robots.txt 확인
    if config.CHECK_ROBOTS_TXT:
        allowed, status = check_robots_txt(canonical)
        console.print(f"[dim]robots.txt: {status}[/dim]")
        if not allowed:
            console.print(f"[yellow]robots.txt에서 접근이 제한된 URL입니다: {canonical}[/yellow]")
            raise typer.Exit()

    # 요청 딜레이 (연속 요청 방지)
    if config.REQUEST_DELAY_SECONDS > 0:
        console.print(f"[dim]요청 딜레이 {config.REQUEST_DELAY_SECONDS}초...[/dim]")
        time.sleep(config.REQUEST_DELAY_SECONDS)

    # 적절한 파서 선택
    parser = None
    for p in PARSERS:
        if p.can_handle(canonical):
            parser = p
            parser_name = type(p).__name__
            break

    if parser is None:
        console.print("[red]지원하지 않는 URL입니다.[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]수집 중... (파서: {parser_name})[/cyan]")

    try:
        post = asyncio.run(parser.parse(canonical))
    except Exception as e:
        console.print(f"[red]크롤링 실패: {e}[/red]")

        # 원티드 파서 실패 시 폴백 시도
        if parser_name != "FallbackParser":
            console.print("[yellow]Gemini 폴백으로 재시도합니다...[/yellow]")
            try:
                fallback = FallbackParser()
                post = asyncio.run(fallback.parse(canonical))
            except Exception as e2:
                console.print(f"[red]폴백도 실패: {e2}[/red]")
                raise typer.Exit(1)
        else:
            raise typer.Exit(1)

    # 미리보기
    _display_preview(post)

    # 저장 확인
    if not skip_confirm:
        confirm = typer.confirm("Google Sheets에 저장하시겠습니까?")
        if not confirm:
            console.print("[dim]저장을 취소했습니다.[/dim]")
            raise typer.Exit()

    # 저장
    try:
        sheets.save_job_post(post)
        _add_to_cache(post)
        console.print("[green]Google Sheets에 저장 완료![/green]")
    except Exception as e:
        console.print(f"[red]저장 실패: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def notify(
    auto: bool = typer.Option(False, "--auto", "-a", help="확인 없이 자동 발송 (cron용)"),
):
    """마감 D-2 이내 공고를 확인하고 Slack 알림을 발송합니다."""
    console.print("[cyan]마감 임박 공고 확인 중...[/cyan]")

    try:
        upcoming = sheets.get_upcoming_deadlines(days=config.NOTIFY_DAYS_BEFORE)
    except Exception as e:
        console.print(f"[red]시트 조회 실패: {e}[/red]")
        raise typer.Exit(1)

    if not upcoming:
        console.print("[dim]마감 임박 공고가 없습니다.[/dim]")
        raise typer.Exit()

    # 결과 표시
    table = Table(title=f"마감 임박 공고 ({len(upcoming)}건)")
    table.add_column("회사", style="bold")
    table.add_column("포지션")
    table.add_column("마감일")
    table.add_column("D-day", style="red bold")

    for job in upcoming:
        days_text = "오늘!" if job["days_left"] == 0 else f"D-{job['days_left']}"
        table.add_row(job["company"], job["position"], job["deadline"], days_text)

    console.print(table)

    # Slack 발송
    if not auto:
        confirm = typer.confirm("Slack으로 알림을 보내시겠습니까?")
        if not confirm:
            raise typer.Exit()

    success = slack.send_deadline_alert(upcoming)
    if success:
        for job in upcoming:
            try:
                sheets.mark_notified(job["url"])
            except Exception:
                pass
        console.print("[green]Slack 알림 발송 완료![/green]")
    else:
        console.print("[red]Slack 발송 실패[/red]")


@app.command(name="list")
def list_posts():
    """저장된 공고 목록을 표시합니다."""
    cache = _load_cache()
    if not cache:
        console.print("[dim]저장된 공고가 없습니다.[/dim]")
        raise typer.Exit()

    table = Table(title=f"저장된 공고 ({len(cache)}건)")
    table.add_column("#", style="dim", width=4)
    table.add_column("회사", style="bold")
    table.add_column("포지션")
    table.add_column("등록일")

    for i, item in enumerate(cache, 1):
        table.add_row(
            str(i),
            item.get("company", ""),
            item.get("position", ""),
            item.get("last_seen", ""),
        )

    console.print(table)


if __name__ == "__main__":
    app()
