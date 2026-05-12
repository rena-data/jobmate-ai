#!/bin/bash
# JobMate AI - 매일 아침 마감 임박 공고 Slack 알림
# cron 등록: crontab -e → 0 9 * * * /path/to/jobmate-ai/cron_notify.sh

cd /path/to/jobmate-ai
/path/to/jobmate-ai/.venv/bin/python main.py notify --auto >> /tmp/jobmate_cron.log 2>&1
