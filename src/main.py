from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.panel import Panel
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

from parsers.base import canonicalize_url, JobPost
import service

app = typer.Typer(
    help="JobMate AI - 채용 공고 자동 수집/관리 CLI",
    invoke_without_command=True,
)
console = Console()


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
    logger.info(f"add 시작 (interactive): {url}")

    try:
        with console.status("[cyan]수집 중...[/cyan]", spinner="dots"):
            result = service.collect(url)
    except KeyboardInterrupt:
        console.print("\n[dim]취소되었습니다.[/dim]")
        return

    if result.already_cached:
        console.print(f"[yellow]이미 등록된 URL입니다: {result.canonical_url}[/yellow]")
        return
    if not result.robots_ok:
        console.print(f"[dim]robots.txt: {result.robots_msg}[/dim]")
        console.print("[yellow]robots.txt에서 접근이 제한된 URL입니다.[/yellow]")
        return
    if result.post is None:
        console.print(f"[red]{result.error}[/red]")
        return

    _emit_collect_notes(result)
    _display_preview(result.post)

    confirm = typer.confirm("Google Sheets에 저장하시겠습니까?")
    if not confirm:
        console.print("[dim]저장을 취소했습니다.[/dim]")
        return

    _save_and_report(result.post)


def _emit_collect_notes(result: service.CollectResult) -> None:
    """수집 부가 정보(robots 상태, 폴백 경고)를 콘솔에 출력."""
    if result.robots_msg:
        console.print(f"[dim]robots.txt: {result.robots_msg}[/dim]")
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")


def _save_and_report(post: JobPost) -> bool:
    """Google Sheets에 저장하고 결과 메시지 출력. 성공 여부 반환."""
    try:
        service.save(post)
        logger.info(f"저장 완료: {post.company} - {post.position}")
        console.print("[green]Google Sheets에 저장 완료![/green]")
        return True
    except PermissionError:
        console.print("[red]Google Sheets 권한 오류. 서비스 계정 이메일에 편집자 권한을 부여했는지 확인해주세요.[/red]")
        return False
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            console.print("[red]Google Sheets API 한도 초과. 잠시 후 다시 시도해주세요.[/red]")
        else:
            console.print(f"[red]저장 실패: {error_msg}[/red]")
        return False


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

    try:
        with console.status("[cyan]수집 중...[/cyan]", spinner="dots"):
            result = service.collect(url)
    except KeyboardInterrupt:
        console.print("\n[dim]취소되었습니다.[/dim]")
        raise typer.Exit()

    if result.already_cached:
        console.print(f"[yellow]이미 등록된 URL입니다: {result.canonical_url}[/yellow]")
        raise typer.Exit()
    if not result.robots_ok:
        console.print(f"[dim]robots.txt: {result.robots_msg}[/dim]")
        console.print(f"[yellow]robots.txt에서 접근이 제한된 URL입니다: {result.canonical_url}[/yellow]")
        raise typer.Exit()
    if result.post is None:
        console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(1)

    _emit_collect_notes(result)

    # 미리보기
    _display_preview(result.post)

    # 저장 확인
    if not skip_confirm:
        confirm = typer.confirm("Google Sheets에 저장하시겠습니까?")
        if not confirm:
            console.print("[dim]저장을 취소했습니다.[/dim]")
            raise typer.Exit()

    # 저장
    if not _save_and_report(result.post):
        raise typer.Exit(1)


@app.command()
def notify(
    auto: bool = typer.Option(False, "--auto", "-a", help="확인 없이 자동 발송 (cron용)"),
):
    """마감 임박(D-2) + 지원 후 N일 경과 공고를 확인하고 Slack 알림을 발송합니다."""
    logger.info("notify 실행")
    console.print("[cyan]마감 임박 / 지원 후속 공고 확인 중...[/cyan]")

    try:
        upcoming = service.find_upcoming(config.NOTIFY_DAYS_BEFORE)
        stale = service.find_stale_applications(config.STALE_APPLY_DAYS)
    except Exception as e:
        console.print(f"[red]시트 조회 실패: {e}[/red]")
        raise typer.Exit(1)

    if not upcoming and not stale:
        console.print("[dim]알림 대상 공고가 없습니다.[/dim]")
        raise typer.Exit()

    if upcoming:
        table = Table(title=f"마감 임박 공고 ({len(upcoming)}건)")
        table.add_column("회사", style="bold")
        table.add_column("포지션")
        table.add_column("마감일")
        table.add_column("D-day", style="red bold")
        for job in upcoming:
            days_text = "오늘!" if job["days_left"] == 0 else f"D-{job['days_left']}"
            table.add_row(job["company"], job["position"], job["deadline"], days_text)
        console.print(table)

    if stale:
        table = Table(title=f"지원 후 {config.STALE_APPLY_DAYS}일+ 경과 ({len(stale)}건)")
        table.add_column("회사", style="bold")
        table.add_column("포지션")
        table.add_column("지원일")
        table.add_column("경과", style="yellow bold")
        for job in stale:
            table.add_row(job["company"], job["position"], job["applied_date"], f"{job['elapsed']}일")
        console.print(table)

    # Slack 발송
    if not auto:
        confirm = typer.confirm("Slack으로 알림을 보내시겠습니까?")
        if not confirm:
            raise typer.Exit()

    sent_any = False
    if upcoming:
        if service.send_notifications(upcoming):
            service.mark_all_notified(upcoming)
            logger.info(f"마감 알림 발송: {len(upcoming)}건")
            console.print(f"[green]마감 알림 발송 완료! ({len(upcoming)}건)[/green]")
            sent_any = True
        else:
            logger.error("마감 알림 발송 실패")
            console.print("[red]마감 알림 발송 실패[/red]")
    if stale:
        if service.send_application_reminders(stale):
            service.mark_all_reminded(stale)
            logger.info(f"지원 후속 리마인더 발송: {len(stale)}건")
            console.print(f"[green]지원 후속 리마인더 발송 완료! ({len(stale)}건)[/green]")
            sent_any = True
        else:
            logger.error("지원 후속 리마인더 발송 실패")
            console.print("[red]지원 후속 리마인더 발송 실패[/red]")
    if not sent_any:
        console.print("[dim]발송된 알림이 없습니다.[/dim]")


@app.command()
def autocollect(
    keyword: list[str] = typer.Option(
        None, "--keyword", "-k",
        help="검색 키워드 (반복 지정 가능). 미지정 시 '키워드 관리' 시트/config 기본값 사용",
    ),
    platform: list[str] = typer.Option(
        None, "--platform", "-p",
        help="대상 플랫폼 (원티드/사람인/잡코리아). 미지정 시 전체",
    ),
    limit: int = typer.Option(None, "--limit", "-l", help="키워드×플랫폼 당 최대 신규 수"),
    auto: bool = typer.Option(False, "--auto", "-a", help="확인 없이 실행 (cron용)"),
):
    """키워드로 채용 플랫폼을 검색해 신규 공고를 자동 수집합니다 (신규 기능)."""
    keywords = list(keyword) if keyword else service.resolve_keywords()
    platforms = list(platform) if platform else list(config.AUTOCOLLECT_PLATFORMS)
    limit_per = limit or config.AUTOCOLLECT_LIMIT_PER

    logger.info(f"autocollect 시작: keywords={keywords} platforms={platforms} limit={limit_per}")

    console.print(Panel.fit(
        f"[bold]키워드[/bold]: {', '.join(keywords)}\n"
        f"[bold]플랫폼[/bold]: {', '.join(platforms)}\n"
        f"[bold]키워드×플랫폼 당 최대[/bold]: {limit_per}건\n"
        f"[dim]예상 작업: 최대 {len(keywords) * len(platforms) * limit_per}건 상세 수집[/dim]",
        title="자동 수집 설정",
    ))

    if not auto:
        if not typer.confirm("검색 + 자동 수집을 시작하시겠습니까?"):
            console.print("[dim]취소되었습니다.[/dim]")
            raise typer.Exit()

    try:
        with console.status("[cyan]키워드 검색 + 수집 중...[/cyan]", spinner="dots"):
            result = service.auto_collect(keywords, platforms, limit_per)
    except KeyboardInterrupt:
        console.print("\n[dim]중단되었습니다.[/dim]")
        raise typer.Exit()

    # 키워드 × 플랫폼 통계
    table = Table(title="자동 수집 결과")
    table.add_column("키워드", style="bold")
    table.add_column("플랫폼")
    table.add_column("발견", justify="right")
    table.add_column("신규", justify="right", style="green bold")
    table.add_column("중복", justify="right", style="dim")
    table.add_column("실패", justify="right", style="red")
    for s in result.stats:
        table.add_row(
            s.keyword, s.platform, str(s.discovered),
            str(s.new), str(s.duplicate), str(s.failed),
        )
    console.print(table)

    # 신규 수집 공고 목록
    new_items = [it for it in result.items if it.outcome == "new"]
    if new_items:
        nt = Table(title=f"신규 수집 공고 ({len(new_items)}건)")
        nt.add_column("플랫폼")
        nt.add_column("회사", style="bold")
        nt.add_column("포지션")
        for it in new_items:
            nt.add_row(it.platform, it.company or "-", it.position or "-")
        console.print(nt)

    # 검색기 레벨 오류
    for err in result.errors:
        console.print(f"[red]⚠ {err}[/red]")

    console.print(
        f"[green]완료[/green] — 발견 {result.discovered} / 신규 {result.new} / "
        f"중복 {result.duplicate} / 실패 {result.failed}"
    )
    logger.info(
        f"autocollect 완료: discovered={result.discovered} new={result.new} "
        f"dup={result.duplicate} failed={result.failed} errors={len(result.errors)}"
    )


@app.command()
def status(
    url: str = typer.Argument(..., help="상태를 변경할 공고 URL"),
    new_status: str = typer.Argument(..., help="변경할 상태 (interest/applied/document_fail/document_pass/interview/interview_fail/final_pass/rejected/hold)"),
):
    """공고의 지원 상태를 변경합니다."""
    if new_status not in service.VALID_STATUSES:
        console.print(f"[red]유효하지 않은 상태: {new_status}[/red]")
        console.print(f"[dim]사용 가능: {', '.join(service.VALID_STATUSES)}[/dim]")
        raise typer.Exit(1)

    canonical = canonicalize_url(url)
    try:
        updated = service.change_status(canonical, new_status)
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
                records = service.list_jobs(online=True)
        except Exception as e:
            console.print(f"[red]시트 조회 실패: {e}[/red]")
            raise typer.Exit(1)

        if not records:
            console.print("[dim]저장된 공고가 없습니다.[/dim]")
            raise typer.Exit()

        STATUS_STYLE = {
            "interest": "[dim]관심[/dim]",
            "applied": "[green]지원완료[/green]",
            "document_pass": "[cyan]서류합격[/cyan]",
            "interview": "[cyan]면접[/cyan]",
            "final_pass": "[bold green]최종합격[/bold green]",
            "rejected": "[red]불합격[/red]",
            "hold": "[yellow]보류[/yellow]",
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
        cache = service.list_jobs(online=False)
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
