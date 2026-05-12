#!/bin/bash
# JobMate AI - 매일 아침 마감 임박 공고 Slack 알림
# 사용법: crontab -e → 0 8 * * * /path/to/jobmate-ai/cron_notify.sh

# 스크립트 위치 기준으로 프로젝트 경로 자동 설정
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"
"$SCRIPT_DIR/.venv/bin/python" main.py notify --auto >> /tmp/jobmate_cron.log 2>&1
