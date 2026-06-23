#!/bin/bash
# JobMate AI - 키워드 기반 자동 수집 (1일 2회: 09:00, 18:00)
# 사용법: crontab -e 에 아래 두 줄 추가
#   0 9  * * * /path/to/jobmate-ai/scripts/cron_autocollect.sh
#   0 18 * * * /path/to/jobmate-ai/scripts/cron_autocollect.sh
#
# ⚠️ macOS 주의: 사람인은 봇 감지로 headless=False(보이는 브라우저)가 필요하다.
#   - cron 실행 시 GUI 로그인 세션이 있어야 브라우저가 뜬다(09:00/18:00은 근무시간이라 보통 충족).
#   - 프로젝트가 ~/Desktop 하위면 macOS TCC가 접근을 막을 수 있음 → 시스템 설정의
#     '전체 디스크 접근 권한'에 cron/python을 추가하거나, 프로젝트를 Desktop 밖으로 옮긴다.
#   - notify cron(cron_notify.sh)은 브라우저를 쓰지 않으므로 영향 없음.

# 스크립트 위치(scripts/) 기준으로 프로젝트 루트 자동 설정
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"
"$ROOT/.venv/bin/python" src/main.py autocollect --auto >> /tmp/jobmate_autocollect.log 2>&1
