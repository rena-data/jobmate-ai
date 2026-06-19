from __future__ import annotations

import requests
from rich.console import Console

import config

console = Console()


def send_deadline_alert(jobs: list[dict]) -> bool:
    """마감 임박 공고들을 Slack으로 알림 발송."""
    if not config.SLACK_WEBHOOK_URL:
        console.print("[yellow]Slack Webhook URL이 설정되지 않았습니다.[/yellow]")
        return False

    if not jobs:
        return True

    message = {
        "text": f"[채용 마감 임박] {len(jobs)}건의 공고가 곧 마감됩니다.",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"채용 마감 임박 ({len(jobs)}건)",
                },
            },
            {"type": "divider"},
        ],
    }

    for job in jobs:
        days_text = "오늘 마감!" if job["days_left"] == 0 else f"D-{job['days_left']}"
        company_type = job.get("company_type", "")
        company_line = f"*{job['company']}*"
        if company_type:
            company_line += f"  |  {company_type}"

        requirements = job.get("requirements", "")
        req_preview = ""
        if requirements:
            req_preview = requirements[:80]
            if len(requirements) > 80:
                req_preview += "..."
            req_preview = f"\n> {req_preview}"

        block_text = (
            f"{company_line}\n"
            f":briefcase:  *{job['position']}*\n"
            f":calendar:  마감: {job['deadline']} (*{days_text}*)"
            f"{req_preview}\n"
            f"<{job['url']}|:link: 공고 보기>"
        )

        message["blocks"].append(
            {"type": "section", "text": {"type": "mrkdwn", "text": block_text}}
        )
        message["blocks"].append({"type": "divider"})

    resp = requests.post(config.SLACK_WEBHOOK_URL, json=message, timeout=10)
    return resp.status_code == 200


def send_application_reminder(jobs: list[dict]) -> bool:
    """지원 후 N일 경과(후속 없음) 공고들을 Slack 리마인더로 발송."""
    if not config.SLACK_WEBHOOK_URL:
        console.print("[yellow]Slack Webhook URL이 설정되지 않았습니다.[/yellow]")
        return False

    if not jobs:
        return True

    message = {
        "text": f"[지원 후속 체크] 지원 후 후속이 없는 공고 {len(jobs)}건",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"지원 후속 체크 ({len(jobs)}건)",
                },
            },
            {"type": "divider"},
        ],
    }

    for job in jobs:
        company_type = job.get("company_type", "")
        company_line = f"*{job['company']}*"
        if company_type:
            company_line += f"  |  {company_type}"

        block_text = (
            f"{company_line}\n"
            f":briefcase:  *{job['position']}*\n"
            f":calendar:  지원: {job['applied_date']} (*{job['elapsed']}일 경과*)\n"
            f"<{job['url']}|:link: 공고 보기>"
        )

        message["blocks"].append(
            {"type": "section", "text": {"type": "mrkdwn", "text": block_text}}
        )
        message["blocks"].append({"type": "divider"})

    resp = requests.post(config.SLACK_WEBHOOK_URL, json=message, timeout=10)
    return resp.status_code == 200
