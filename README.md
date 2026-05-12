# JobMate AI

채용 공고 URL만 입력하면 자동으로 분석해서 Google Sheets에 저장하고, 마감 2일 전에 Slack으로 알림을 보내는 개인용 자동화 CLI 도구.

## 기능

- **채용 공고 자동 수집**: URL 입력 → 회사정보, 포지션, 자격요건, 우대사항, 마감일 자동 추출
- **Google Sheets 자동 저장**: 수집 데이터를 스프레드시트에 자동 기록
- **마감 알림**: D-2 마감 임박 공고를 매일 아침 Slack으로 알림
- **스마트 파서**: 원티드 전용 파서 + Gemini AI 범용 폴백 (어떤 사이트든 대응)
- **안전장치**: robots.txt 체크, 요청 딜레이, URL 중복 방지

## 기술 스택

| 역할 | 기술 |
|------|------|
| CLI | Python, Typer, Rich |
| 크롤링 | Playwright, BeautifulSoup4 |
| AI 폴백 | Google Gemini API (google-genai) |
| 본문 추출 | trafilatura |
| 저장 | Google Sheets API (gspread) |
| 알림 | Slack Incoming Webhook |
| 스케줄링 | cron |

## 빠른 시작

### 1. 설치

```bash
git clone <repo-url>
cd jobmate-ai

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Playwright 브라우저 설치
playwright install chromium
```

### 2. 환경 설정

`.env.example`을 복사하여 `.env` 생성:

```bash
cp .env.example .env
```

`.env` 내용:

```
GEMINI_API_KEY=<Google AI Studio에서 발급한 API 키>
SLACK_WEBHOOK_URL=<Slack Incoming Webhook URL>
GOOGLE_SHEETS_ID=<Google Sheets ID (URL에서 /d/ 뒤의 값)>
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
```

### 3. Google Sheets 연동

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. **API 및 서비스 > 라이브러리**에서 아래 2개 API 활성화:
   - Google Sheets API
   - Google Drive API
3. **API 및 서비스 > 사용자 인증 정보 > + 사용자 인증 정보 만들기 > 서비스 계정**
4. 서비스 계정 생성 후 **키 탭 > 키 추가 > 새 키 만들기 > JSON** 다운로드
5. 다운로드한 파일을 `credentials.json`으로 이름 변경 후 프로젝트 루트에 배치
6. JSON 파일 안의 `client_email` 값을 복사
7. Google Sheets에서 해당 이메일에 **편집자** 권한으로 공유

### 4. Slack 연동

1. https://api.slack.com/apps 접속
2. **Create New App > From scratch** > 이름 입력 > 워크스페이스 선택
3. 좌측 **Incoming Webhooks** > Activate > **Add New Webhook to Workspace**
4. 알림 채널 선택 > Webhook URL 복사 > `.env`에 설정

### 5. Gemini API 키

1. https://aistudio.google.com 접속
2. **Get API Key** > API 키 복사 > `.env`에 설정

## 사용법

```bash
# 가상환경 활성화
source .venv/bin/activate

# 채용 공고 추가 (미리보기 → 확인 → 저장)
python main.py add "https://www.wanted.co.kr/wd/258066"

# 확인 없이 바로 저장
python main.py add "https://www.wanted.co.kr/wd/258066" --yes

# 저장된 공고 목록 확인
python main.py list

# 마감 임박 알림 (수동, 확인 후 Slack 발송)
python main.py notify

# 마감 임박 알림 (자동, cron용)
python main.py notify --auto
```

### 실행 예시

```
$ python main.py add "https://www.wanted.co.kr/wd/258066"

robots.txt: robots.txt 없음/접근불가 (HTTP 403)
요청 딜레이 2초...
수집 중... (파서: WantedParser)

┌─────────────┬──────────────────────────────────────────────┐
│ 항목        │ 내용                                         │
├─────────────┼──────────────────────────────────────────────┤
│ 회사명      │ 그린랩스                                     │
│ 직원수      │ 300명                                        │
│ 포지션      │ 데이터 분석가(Data Analyst)                  │
│ 자격요건    │ SQL, 데이터 분석 방법 이해, A/B 테스트...    │
│ 우대사항    │ 클라우드 환경, 시각화 도구, 이커머스 경험... │
│ 마감유형    │ rolling (상시채용)                            │
└─────────────┴──────────────────────────────────────────────┘

Google Sheets에 저장하시겠습니까? [y/n]: y
Google Sheets에 저장 완료!
```

## cron 설정 (매일 자동 알림)

매일 아침 8시에 마감 임박 공고를 Slack으로 알려줍니다.

```bash
crontab -e
```

아래 줄 추가:

```
0 8 * * * /path/to/jobmate-ai/cron_notify.sh
```

실행 로그 확인:

```bash
cat /tmp/jobmate_cron.log
```

## 프로젝트 구조

```
jobmate-ai/
├── main.py              # CLI 진입점 (add, list, notify)
├── config.py            # 설정 (환경변수, 딜레이 등)
├── sheets.py            # Google Sheets 연동
├── slack.py             # Slack 알림 발송
├── cache.json           # URL 중복 방지 캐시
├── cron_notify.sh       # cron 자동 알림 스크립트
├── .env                 # 환경변수 (API 키 등)
├── credentials.json     # Google 서비스 계정 키
├── requirements.txt
├── parsers/
│   ├── base.py          # BaseParser 인터페이스 + JobPost 모델
│   ├── wanted.py        # 원티드 전용 파서
│   └── fallback.py      # Gemini AI 범용 폴백 파서
└── docs/
    ├── 작업내용_정리.md
    └── blog_post.md
```

## Google Sheets 컬럼 구조

| 컬럼 | 설명 |
|------|------|
| URL | 원본 공고 링크 |
| 회사명 | 회사 이름 |
| 업종 | 업종 분류 |
| 직원수 | 직원 규모 |
| 회사설명 | 회사 소개 |
| 포지션 | 채용 직무명 |
| 주요업무 | 업무 내용 |
| 자격요건 | 필수 자격 |
| 우대사항 | 우대 조건 |
| 마감일(원본) | 사이트 표시 원본 텍스트 |
| 마감일(파싱) | YYYY-MM-DD 정규화 |
| 마감유형 | fixed / rolling / unknown |
| 등록일 | 수집 날짜 |
| 상태 | interest / applied / interview / closed |
| 비고 | 메모 |

## 지원 사이트

| 사이트 | 파서 | 상태 |
|--------|------|------|
| 원티드 (wanted.co.kr) | 전용 파서 | 지원 |
| 기타 모든 사이트 | Gemini AI 폴백 | 지원 (정확도 변동 가능) |
| 사람인 | 전용 파서 예정 | 고도화 예정 |
| 잡코리아 | 전용 파서 예정 | 고도화 예정 |

## 고도화 로드맵

### Phase 1: 사이트 확장
- 사람인, 잡코리아, 로켓펀치 전용 파서 추가
- 사이트별 파서 안정성 검증

### Phase 2: 기능 확장
- 지원 상태 관리 (관심 → 지원 → 면접 → 결과)
- 기업 리뷰 자동 수집
- 기술 스택 기반 공고 필터링

### Phase 3: AI 고도화
- JD 기반 자소서 첨삭 AI
- AI 문체 인간화 엔진
- 기업 유형별 톤 프리셋

### Phase 4: 서비스화 (선택)
- 로컬 웹 UI (FastAPI + Jinja2)
- SaaS 전환 검토

## 라이선스

개인 사용 목적 프로젝트
