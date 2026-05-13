from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

import config

# 파일 로깅 설정
logging.basicConfig(
    filename=str(config.LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("jobmate")
from parsers.base import canonicalize_url, check_robots_txt, JobPost
from parsers.wanted import WantedParser
from parsers.saramin import SaraminParser
from parsers.fallback import FallbackParser
import sheets
import slack

app = typer.Typer(
    help="JobMate AI - 채용 공고 자동 수집/관리 CLI",
    invoke_without_command=True,
)
console = Console()

# 파서 등록 (우선순위 순)
PARSERS = [
    WantedParser(),
    SaraminParser(),
    FallbackParser(),  # 항상 마지막 (폴백)
]


@app.callback()
def main(ctx: typer.Context):
    """JobMate AI - 채용 공고 자동 수집/관리 CLI"""
    if ctx.invoked_subcommand is not None:
        return

    # 서브명령 없이 실행 → 인터랙티브 모드
    _interactive_mode()


def _interactive_mode():
    """인터랙티브 모드: URL 입력 프롬프트를 반복 표시."""
    console.print()
    console.print(Panel(
        "[bold cyan]JobMate AI[/bold cyan]\n"
        "[dim]채용 공고 URL을 붙여넣으세요. 자동으로 분석하여 Google Sheets에 저장합니다.[/dim]\n\n"
        "[dim]명령어:  url 붙여넣기 → 공고 추가  |  list → 목록  |  notify → 알림  |  q → 종료[/dim]",
        border_style="cyan",
    ))
    console.print()

    while True:
        try:
            user_input = console.input("[bold cyan]>> [/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]종료합니다.[/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("q", "quit", "exit"):
            console.print("[dim]종료합니다.[/dim]")
            break
        elif cmd == "list":
            list_posts(online=True)
            console.print()
        elif cmd == "notify":
            notify(auto=False)
            console.print()
        elif cmd.startswith("status "):
            parts = cmd.split(None, 2)
            if len(parts) == 3:
                status(url=parts[1], new_status=parts[2])
            else:
                console.print("[dim]사용법: status <url> <상태>[/dim]")
            console.print()
        elif cmd == "help":
            console.print(
                "[dim]url 붙여넣기 → 공고 추가  |  list → 목록  |  notify → 알림\n"
                "status <url> <상태> → 상태 변경  |  q → 종료[/dim]"
            )
            console.print()
        elif user_input.startswith("http"):
            # URL로 판단 → add 실행
            _add_url(user_input)
            console.print()
        else:
            console.print("[yellow]URL을 입력하거나 명령어를 입력해주세요. (help로 도움말)[/yellow]")
            console.print()


def _add_url(url: str):
    """인터랙티브 모드에서 URL 추가 실행."""
    canonical = canonicalize_url(url)

    if _is_cached(canonical):
        console.print(f"[yellow]이미 등록된 URL입니다: {canonical}[/yellow]")
        return

    if config.CHECK_ROBOTS_TXT:
        allowed, status_msg = check_robots_txt(canonical)
        console.print(f"[dim]robots.txt: {status_msg}[/dim]")
        if not allowed:
            console.print(f"[yellow]robots.txt에서 접근이 제한된 URL입니다.[/yellow]")
            return

    if config.REQUEST_DELAY_SECONDS > 0:
        console.print(f"[dim]요청 딜레이 {config.REQUEST_DELAY_SECONDS}초...[/dim]")
        time.sleep(config.REQUEST_DELAY_SECONDS)

    parser = None
    for p in PARSERS:
        if p.can_handle(canonical):
            parser = p
            parser_name = type(p).__name__
            break

    if parser is None:
        console.print("[red]지원하지 않는 URL입니다.[/red]")
        return

    logger.info(f"add 시작 (interactive): {url}")

    try:
        with console.status(f"[cyan]수집 중... (파서: {parser_name})[/cyan]", spinner="dots"):
            post = asyncio.run(parser.parse(canonical))
    except KeyboardInterrupt:
        console.print("\n[dim]취소되었습니다.[/dim]")
        return
    except TimeoutError:
        console.print("[red]페이지 로딩 시간 초과.[/red]")
        return
    except Exception as e:
        error_msg = str(e)
        if "net::ERR" in error_msg or "Timeout" in error_msg:
            console.print("[red]네트워크 오류. 인터넷 연결을 확인해주세요.[/red]")
        else:
            console.print(f"[red]크롤링 실패: {error_msg}[/red]")

        if parser_name != "FallbackParser":
            console.print("[yellow]Gemini 폴백으로 재시도합니다...[/yellow]")
            try:
                with console.status("[cyan]폴백 수집 중...[/cyan]", spinner="dots"):
                    post = asyncio.run(FallbackParser().parse(canonical))
            except Exception as e2:
                console.print(f"[red]폴백도 실패: {e2}[/red]")
                return
        else:
            return

    _display_preview(post)

    confirm = typer.confirm("Google Sheets에 저장하시겠습니까?")
    if not confirm:
        console.print("[dim]저장을 취소했습니다.[/dim]")
        return

    try:
        sheets.save_job_post(post)
        _add_to_cache(post)
        logger.info(f"저장 완료 (interactive): {post.company} - {post.position}")
        console.print("[green]Google Sheets에 저장 완료![/green]")
    except PermissionError:
        console.print("[red]Google Sheets 권한 오류.[/red]")
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            console.print("[red]Google Sheets API 한도 초과.[/red]")
        else:
            console.print(f"[red]저장 실패: {error_msg}[/red]")


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
    logger.info(f"add 시작: {url}")
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
    except KeyboardInterrupt:
        console.print("\n[dim]취소되었습니다.[/dim]")
        raise typer.Exit()
    except TimeoutError:
        console.print("[red]페이지 로딩 시간 초과. 네트워크 연결을 확인하거나 잠시 후 다시 시도해주세요.[/red]")
        raise typer.Exit(1)
    except Exception as e:
        error_msg = str(e)
        if "net::ERR" in error_msg or "Timeout" in error_msg:
            console.print("[red]네트워크 오류. 인터넷 연결을 확인해주세요.[/red]")
        else:
            console.print(f"[red]크롤링 실패: {error_msg}[/red]")

        # 전용 파서 실패 시 폴백 시도
        if parser_name != "FallbackParser":
            console.print("[yellow]Gemini 폴백으로 재시도합니다...[/yellow]")
            try:
                post = asyncio.run(FallbackParser().parse(canonical))
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
        logger.info(f"저장 완료: {post.company} - {post.position}")
        console.print("[green]Google Sheets에 저장 완료![/green]")
    except PermissionError:
        console.print("[red]Google Sheets 권한 오류. 서비스 계정 이메일에 편집자 권한을 부여했는지 확인해주세요.[/red]")
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            console.print("[red]Google Sheets API 한도 초과. 잠시 후 다시 시도해주세요.[/red]")
        else:
            console.print(f"[red]저장 실패: {error_msg}[/red]")
        raise typer.Exit(1)


@app.command()
def notify(
    auto: bool = typer.Option(False, "--auto", "-a", help="확인 없이 자동 발송 (cron용)"),
):
    """마감 D-2 이내 공고를 확인하고 Slack 알림을 발송합니다."""
    logger.info("notify 실행")
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
        logger.info(f"Slack 알림 발송 완료: {len(upcoming)}건")
        console.print("[green]Slack 알림 발송 완료![/green]")
    else:
        logger.error("Slack 발송 실패")
        console.print("[red]Slack 발송 실패[/red]")


@app.command()
def status(
    url: str = typer.Argument(..., help="상태를 변경할 공고 URL"),
    new_status: str = typer.Argument(..., help="변경할 상태 (interest / applied / interview / closed)"),
):
    """공고의 지원 상태를 변경합니다."""
    if new_status not in sheets.VALID_STATUSES:
        console.print(f"[red]유효하지 않은 상태: {new_status}[/red]")
        console.print(f"[dim]사용 가능: {', '.join(sheets.VALID_STATUSES)}[/dim]")
        raise typer.Exit(1)

    canonical = canonicalize_url(url)
    try:
        updated = sheets.update_status(canonical, new_status)
    except Exception as e:
        console.print(f"[red]상태 변경 실패: {e}[/red]")
        raise typer.Exit(1)

    if updated:
        console.print(f"[green]상태 변경 완료: {new_status}[/green]")
    else:
        console.print(f"[yellow]해당 URL을 찾을 수 없습니다: {canonical}[/yellow]")


@app.command(name="list")
def list_posts(
    online: bool = typer.Option(False, "--online", "-o", help="Google Sheets에서 최신 데이터 조회"),
):
    """저장된 공고 목록을 표시합니다."""
    if online:
        try:
            with console.status("[cyan]Sheets에서 조회 중...[/cyan]", spinner="dots"):
                records = sheets.get_all_posts()
        except Exception as e:
            console.print(f"[red]시트 조회 실패: {e}[/red]")
            raise typer.Exit(1)

        if not records:
            console.print("[dim]저장된 공고가 없습니다.[/dim]")
            raise typer.Exit()

        STATUS_STYLE = {
            "interest": "[dim]관심[/dim]",
            "applied": "[green]지원완료[/green]",
            "interview": "[cyan]면접[/cyan]",
            "closed": "[red]마감[/red]",
        }

        table = Table(title=f"저장된 공고 ({len(records)}건)")
        table.add_column("#", style="dim", width=4)
        table.add_column("회사", style="bold")
        table.add_column("포지션", max_width=30)
        table.add_column("마감일", width=12)
        table.add_column("상태", width=8)
        table.add_column("등록일", width=12)

        for i, row in enumerate(records, 1):
            status_val = str(row.get("상태", ""))
            status_display = STATUS_STYLE.get(status_val, status_val)
            deadline = str(row.get("마감일(파싱)", "")) or str(row.get("마감일(원본)", "-"))
            table.add_row(
                str(i),
                str(row.get("회사명", "")),
                str(row.get("포지션", "")),
                deadline,
                status_display,
                str(row.get("등록일", "")),
            )

        console.print(table)
    else:
        cache = _load_cache()
        if not cache:
            console.print("[dim]저장된 공고가 없습니다. (--online으로 Sheets에서 조회 가능)[/dim]")
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
