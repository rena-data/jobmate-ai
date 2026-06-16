#!/bin/bash
# JobMate AI - 매일 아침 마감 임박 공고 Slack 알림
# 사용법: crontab -e → 0 8 * * * /path/to/jobmate-ai/cron_notify.sh

# 스크립트 위치(scripts/) 기준으로 프로젝트 루트 자동 설정
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"
"$ROOT/.venv/bin/python" src/main.py notify --auto >> /tmp/jobmate_cron.log 2>&1
