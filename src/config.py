import os
from pathlib import Path
from dotenv import load_dotenv

# src/config.py 기준 → 프로젝트 루트는 한 단계 위(src의 부모)
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# .env는 루트에서 명시적으로 로드 (실행 위치와 무관하게 동작)
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")

# 서비스 계정 파일: 상대경로면 루트 기준으로 해석 (cwd 무관)
_sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
GOOGLE_SERVICE_ACCOUNT_FILE = _sa_file if os.path.isabs(_sa_file) else str(BASE_DIR / _sa_file)

# 런타임 데이터는 data/ 폴더에 보관
CACHE_FILE = DATA_DIR / "cache.json"
LOG_FILE = DATA_DIR / "jobmate.log"

# Playwright
PLAYWRIGHT_HEADLESS = False  # 초기엔 headless=False 권장 (봇 감지 대응)
PAGE_LOAD_TIMEOUT = 30_000   # ms

# 크롤링 안전장치
REQUEST_DELAY_SECONDS = 2  # 요청 간 최소 딜레이 (초)
CHECK_ROBOTS_TXT = True     # robots.txt 확인 여부

# Deadline
NOTIFY_DAYS_BEFORE = 2  # D-2 알림

# 지원 후 N일 경과 시 후속 리마인더 (지원완료 상태 + 무진행)
STALE_APPLY_DAYS = 7

# ---------------------------------------------------------------------------
# 자동 수집 (auto-collect) — 신규 기능. 기존 수동 수집 동작에는 영향 없음.
# 키워드는 'AUTOCOLLECT_KEYWORDS'를 기본값으로 쓰되, Google Sheets '키워드 관리'
# 탭이 있으면 그쪽을 우선 사용한다 (service.resolve_keywords).
# ---------------------------------------------------------------------------
AUTOCOLLECT_KEYWORDS = [
    "AX", "바이브코딩", "AI기획", "AI Engineer",
    "LLM", "Prompt Engineer", "AI Product Manager",
]
# 자동 수집 대상 플랫폼 (전용 파서 보유분만). 점핏은 다음 라운드, 로켓펀치는 봇차단으로 제외.
AUTOCOLLECT_PLATFORMS = ["원티드", "사람인", "잡코리아"]
# 키워드 × 플랫폼 당 최대 신규 후보 URL 수 (과도한 크롤링 방지)
AUTOCOLLECT_LIMIT_PER = 10
