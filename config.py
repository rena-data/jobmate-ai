import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "credentials.json"),
)

CACHE_FILE = BASE_DIR / "cache.json"
LOG_FILE = BASE_DIR / "jobmate.log"

# Playwright
PLAYWRIGHT_HEADLESS = False  # 초기엔 headless=False 권장 (봇 감지 대응)
PAGE_LOAD_TIMEOUT = 30_000   # ms

# 크롤링 안전장치
REQUEST_DELAY_SECONDS = 2  # 요청 간 최소 딜레이 (초)
CHECK_ROBOTS_TXT = True     # robots.txt 확인 여부

# Deadline
NOTIFY_DAYS_BEFORE = 2  # D-2 알림
