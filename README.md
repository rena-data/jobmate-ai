# JobMate AI

채용 공고 URL을 입력하면 공고 내용을 자동으로 정리해서 Google Sheets에 저장해주고, 마감 2일 전·지원 후 후속이 없을 때 Slack으로 알려주는 도구입니다.

## 이런 분에게 유용합니다

- 채용 공고를 여러 사이트에서 확인하면서 스프레드시트에 하나씩 정리하는 게 귀찮은 분
- 마감일을 놓쳐서 지원을 못한 경험이 있는 분
- 지원한 공고를 한 곳에서 관리하고 싶은 분

## 어떻게 동작하나요?

```
1. 웹 화면 또는 터미널에서 채용 공고 URL을 입력합니다
2. 자동으로 회사명, 포지션, 자격요건, 우대사항, 마감일을 추출합니다
3. 결과를 보여주고, 저장할지 물어봅니다
4. "y"를 누르면 Google Sheets에 자동 저장됩니다
5. 마감 2일 전, 그리고 지원 후 7일째 후속이 없으면 Slack으로 알림이 옵니다
```

## 지원 사이트

| 사이트 | 방식 | 정확도 |
|--------|------|--------|
| 원티드 (wanted.co.kr) | 전용 파서 | 7/7 |
| 사람인 (saramin.co.kr) | 전용 파서 | 5~7/7 |
| 잡코리아 (jobkorea.co.kr) | 전용 파서 (Gemini 불필요) | 양호 |
| 그룹바이 (groupby.kr) | 전용 파서 (Gemini 불필요) | 양호 |
| 점핏 (jumpit.saramin.co.kr) | AI 자동 추출 (Gemini) | 양호 |
| 로켓펀치 (rocketpunch.com) | - | 미지원 (봇 차단) |
| 기타 사이트 | AI 자동 추출 (Gemini) | 사이트별 상이 |

> **입력은 "개별 공고" URL만 지원합니다.** 목록/검색 페이지(예: 원티드 `/wdlist/...`, 사람인 `/jobs/list/...`, 그룹바이 `/positions`)가 아니라, 공고 하나를 클릭했을 때 나오는 주소(예: 원티드 `/wd/258066`, 그룹바이 `/positions/10760`)를 넣어주세요.

---

## ⚠️ 사용 시 유의사항 (면책)

- 본 프로젝트는 **개인 학습·연구 및 개인 자동화** 목적으로 공개된 코드입니다.
- 채용 사이트 수집은 각 사이트의 **이용약관(ToS)·robots.txt·관련 법령**의 적용을 받으며, 사용에 따른 모든 책임은 **사용자 본인**에게 있습니다.
- 기본 안전장치(요청 간 딜레이, robots.txt 확인, 개인용 소량 수집)를 임의로 우회·확대하지 마세요. 과도한 자동 수집은 대상 사이트에 부담을 주고 약관 위반이 될 수 있습니다.
- 수집한 데이터(회사명·공고 내용 등)의 저장·활용 시 저작권·개인정보 관련 법령을 준수하세요.
- 본 코드는 "있는 그대로(AS-IS)" 제공되며, 사용 결과에 대해 작성자는 어떠한 보증·책임도 지지 않습니다.

---

# 설치 가이드 (처음부터 따라하기)

> 아래 과정은 한 번만 하면 됩니다. 이후에는 바로 사용할 수 있습니다.

## 준비물

시작하기 전에 아래 3가지가 필요합니다:

1. **Google 계정** (Google Sheets, Gemini API용)
2. **Slack 워크스페이스** (마감 알림용)
3. **Python 3.10 이상** (프로그램 실행용)

> Python이 설치되어 있는지 확인하려면 터미널에서 `python3 --version`을 입력해보세요.
> 버전 번호가 나오면 설치되어 있는 것입니다.

---

## STEP 1. 프로젝트 다운로드

터미널(맥: Terminal 앱, 윈도우: PowerShell)을 열고 아래 명령어를 순서대로 입력합니다.

```bash
# 프로젝트 다운로드
git clone https://github.com/rena-data/jobmate-ai.git

# 프로젝트 폴더로 이동
cd jobmate-ai
```

## STEP 2. Python 환경 설정

```bash
# 가상환경 만들기 (프로젝트 전용 Python 환경)
python3 -m venv .venv

# 가상환경 활성화 (맥/리눅스)
source .venv/bin/activate

# 가상환경 활성화 (윈도우)
# .venv\Scripts\activate

# 필요한 라이브러리 설치
pip install -r requirements.txt

# 크롤링용 브라우저 설치
playwright install chromium
```

> 가상환경이 활성화되면 터미널 앞에 `(.venv)`가 표시됩니다.
> 매번 프로그램을 실행하기 전에 `source .venv/bin/activate`를 먼저 입력해야 합니다.

## STEP 3. Gemini API 키 발급

Gemini API는 원티드/사람인 외의 사이트에서 공고를 분석할 때 사용합니다.

1. https://aistudio.google.com 에 접속합니다 (Google 로그인)
2. 왼쪽 메뉴에서 **Get API Key** 클릭
3. **Create API Key** 버튼 클릭
4. 생성된 API 키를 복사해둡니다 (나중에 사용)

## STEP 4. Google Sheets 연동

채용 공고 데이터가 저장될 스프레드시트를 연결합니다.

### 4-1. 스프레드시트 준비

1. https://sheets.google.com 에서 새 스프레드시트를 만듭니다
2. 스프레드시트 URL에서 ID를 복사합니다:
   ```
   https://docs.google.com/spreadsheets/d/여기가_시트_ID/edit
                                          ^^^^^^^^^^^^^^
                                          이 부분을 복사
   ```

### 4-2. Google Cloud 서비스 계정 만들기

프로그램이 스프레드시트에 자동으로 데이터를 쓰려면 "서비스 계정"이 필요합니다.

1. https://console.cloud.google.com 에 접속합니다
2. 상단의 프로젝트 선택 > **새 프로젝트** 만들기 (이름은 아무거나, 예: "jobmate")
3. 왼쪽 메뉴 **API 및 서비스** > **라이브러리** 클릭
4. 검색창에 **Google Sheets API** 입력 > 클릭 > **사용** 버튼 클릭
5. 다시 라이브러리로 돌아가서 **Google Drive API** 검색 > **사용** 클릭
6. 왼쪽 메뉴 **API 및 서비스** > **사용자 인증 정보** 클릭
7. 상단 **+ 사용자 인증 정보 만들기** > **서비스 계정** 선택
8. 서비스 계정 이름 입력 (예: `jobmate-sheets`) > **만들기 및 계속** > **완료**
9. 방금 만든 서비스 계정 이메일을 클릭합니다 (예: `jobmate-sheets@...iam.gserviceaccount.com`)
10. **키** 탭 > **키 추가** > **새 키 만들기** > **JSON** 선택 > **만들기**
11. JSON 파일이 자동 다운로드됩니다

### 4-3. 파일 배치 및 공유 설정

1. 다운로드된 JSON 파일의 이름을 `credentials.json`으로 변경합니다
2. 이 파일을 `jobmate-ai` 폴더 안에 넣습니다
3. `credentials.json` 파일을 열어서 `client_email` 값을 복사합니다
   ```
   "client_email": "jobmate-sheets@프로젝트명.iam.gserviceaccount.com"
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                    이 이메일 주소를 복사
   ```
4. 아까 만든 Google Sheets를 열고 > 우측 상단 **공유** 버튼 클릭
5. 복사한 이메일 주소를 붙여넣기 > **편집자** 권한 선택 > **보내기**

> 이 설정을 하면 프로그램이 스프레드시트에 자동으로 데이터를 쓸 수 있게 됩니다.

## STEP 5. Slack 알림 설정

마감 2일 전에 Slack으로 알림을 받을 수 있습니다.

1. https://api.slack.com/apps 에 접속합니다
2. **Create New App** > **From scratch** 선택
3. App Name에 원하는 이름 입력 (예: `JobMate Alert`) > 워크스페이스 선택 > **Create App**
4. 왼쪽 메뉴 **Incoming Webhooks** 클릭
5. **Activate Incoming Webhooks** 스위치를 **On**으로 변경
6. 하단 **Add New Webhook to Workspace** 클릭
7. 알림 받을 채널 선택 > **허용**
8. 생성된 Webhook URL을 복사합니다 (`https://hooks.slack.com/services/...` 형태)

## STEP 6. 환경변수 파일 만들기

위에서 준비한 정보들을 `.env` 파일에 저장합니다.

```bash
# .env 파일 생성
cp .env.example .env
```

생성된 `.env` 파일을 텍스트 편집기로 열고 아래 내용을 채워넣습니다:

```
GEMINI_API_KEY=여기에_STEP3에서_복사한_API키_붙여넣기
SLACK_WEBHOOK_URL=여기에_STEP5에서_복사한_Webhook_URL_붙여넣기
GOOGLE_SHEETS_ID=여기에_STEP4에서_복사한_시트ID_붙여넣기
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
```

> `.env` 파일은 개인 비밀 정보가 담겨있으므로 GitHub에 올라가지 않습니다 (`.gitignore`로 제외됨).

---

# 사용법

> 매번 사용 전에 가상환경을 활성화해야 합니다: `source .venv/bin/activate`

## 웹 화면으로 사용하기 (추천)

브라우저에서 클릭만으로 공고를 수집/관리할 수 있는 화면입니다.

```bash
streamlit run src/app.py
```

실행하면 자동으로 브라우저에 화면이 열립니다 (안 열리면 터미널에 표시되는 `http://localhost:8501` 주소를 직접 열어주세요).

좌측 **사이드바 메뉴**는 4개 그룹으로 구성됩니다 (테마: 네이비 사이드바 + 라이트 본문):

| 메뉴 | 동작 |
|------|------|
| **대시보드** | KPI 4개(총 수집·신규·마감 임박 D-7·상시채용) + 플랫폼별 수집 현황 + 직군별/상태별(지원) 분포 + 최근 수집 공고(상태 배지·⭐관심·📋상세) + 마감 임박(D-day 색상) + AI 인사이트 |
| **채용공고 › 수집** | URL을 붙여넣고 `수집` → 미리보기에서 내용 확인·수정 → `저장` |
| **채용공고 › 목록** | 저장된 공고 보기 (로컬 캐시 / Google Sheets). 행을 클릭하면 **상세 보기 + 상태·메모 편집** 창이 열립니다 |
| **알림·관리 › 마감 임박** | 마감 임박 공고 조회 → `Slack으로 발송` |
| **알림·관리 › 지원상태 변경** | 공고 선택 → 상태(관심/지원완료/서류합격/면접/최종합격/불합격/보류) 변경 |

사이드바 **하단**에서 API 키·인증 파일 설정 상태(환경 상태)를 한눈에 확인할 수 있습니다. 직군 분류(Backend/Data/AI 등)와 플랫폼별 현황·인사이트는 모두 규칙 기반 실집계로 자동 계산됩니다.

> 수집할 때 크롤링용 브라우저 창이 잠깐 떴다 닫힙니다 (봇 차단 회피를 위한 정상 동작입니다).
> 종료하려면 터미널에서 `Ctrl + C`를 누릅니다.

## 인터랙티브 모드 (터미널)

터미널에서 바로 쓰는 방식입니다. 프로그램을 실행하면 URL 입력창이 나타납니다.

```bash
python src/main.py
```

실행하면 이렇게 보입니다:

```
╭──────────────────────────────────────────────────────╮
│ JobMate AI                                           │
│ 채용 공고 URL을 붙여넣으세요.                        │
│                                                      │
│ url 붙여넣기 | list | notify | status | q → 종료     │
╰──────────────────────────────────────────────────────╯

>> (여기에 URL을 붙여넣으세요)
```

| 입력 | 동작 |
|------|------|
| URL 붙여넣기 | 공고 분석 → 미리보기 → 저장 |
| `list` | 저장된 공고 목록 (Sheets에서 최신 조회) |
| `notify` | 마감 임박 공고 Slack 알림 |
| `status URL applied` | 공고 상태 변경 |
| `help` | 도움말 |
| `q` | 종료 |

URL을 붙여넣으면 자동으로 분석이 시작됩니다:

```
>> https://www.wanted.co.kr/wd/258066

⠋ 수집 중... (파서: WantedParser)

┌─────────────┬──────────────────────────────────────────────┐
│ 항목        │ 내용                                         │
├─────────────┼──────────────────────────────────────────────┤
│ 회사명      │ 그린랩스                                     │
│ 직원수      │ 300명                                        │
│ 포지션      │ 데이터 분석가(Data Analyst)                  │
│ 자격요건    │ SQL 활용, 데이터 분석 방법 이해...           │
│ 마감유형    │ rolling (상시채용)                            │
└─────────────┴──────────────────────────────────────────────┘

Google Sheets에 저장하시겠습니까? [y/n]: y
Google Sheets에 저장 완료!

>> (다음 URL을 바로 붙여넣기 가능)
```

> 같은 URL을 다시 입력하면 "이미 등록된 URL입니다"라고 알려줍니다.

## 직접 명령어 사용

인터랙티브 모드 대신 명령어를 직접 입력할 수도 있습니다.

```bash
# 공고 추가
python src/main.py add "https://www.wanted.co.kr/wd/258066"

# 확인 없이 바로 저장
python src/main.py add "https://www.wanted.co.kr/wd/258066" --yes

# 저장된 공고 목록 (로컬 캐시)
python src/main.py list

# 저장된 공고 목록 (Sheets에서 최신 조회, 상태 포함)
python src/main.py list --online

# 공고 상태 변경
python src/main.py status "공고URL" applied

# 마감 임박 + 지원 후속 알림 (수동)
python src/main.py notify

# 마감 임박 + 지원 후속 알림 (자동, cron용)
python src/main.py notify --auto

# 키워드로 채용 플랫폼을 검색해 신규 공고 자동 수집 (신규 기능)
python src/main.py autocollect                          # 시트/config 키워드 + 전체 플랫폼
python src/main.py autocollect -k "AI Engineer" -p 잡코리아 -l 5
python src/main.py autocollect --auto                   # 확인 없이 (cron용)
```

### 상태 종류

| 상태 | 의미 |
|------|------|
| `interest` | 관심공고 (기본값) |
| `applied` | 지원완료 |
| `document_fail` | 서류탈락 |
| `document_pass` | 서류합격 |
| `interview` | 면접예정 |
| `interview_fail` | 면접탈락 |
| `final_pass` | 최종합격 |
| `rejected` | 불합격 |
| `hold` | 보류 |

> 이전 버전의 `closed`(마감) 값은 표시상 계속 인식되지만, 신규 선택지에서는 제외되었습니다.

## 키워드 자동 수집 (신규)

URL을 직접 붙여넣지 않아도, 키워드로 채용 플랫폼을 검색해 **신규 공고를 스스로 발견·수집**합니다.

- **대상 플랫폼**: 원티드 · 사람인 · 잡코리아 (전용 파서 보유). 점핏은 다음 단계, 로켓펀치는 봇 차단으로 제외.
- **중복 제거(2단계)**: ① 발견한 URL을 로컬 캐시 + 시트와 대조하고, ② 수집 후 **동일 회사 + 동일 직무**가 이미 있으면(시트 기존분 + 이번 실행분) 저장하지 않습니다. URL이 달라도 같은 공고면 중복으로 처리합니다.
- **기존 수동 수집과 병행**: 자동 수집한 공고는 같은 시트에 저장되며, `수집방식` 컬럼으로 자동/수동을 구분합니다(목록·상세 모달에 표시).
- **검색 키워드**: 기본값은 `config.py`의 `AUTOCOLLECT_KEYWORDS`(AX, 바이브코딩, AI기획, AI Engineer, LLM, Prompt Engineer, AI Product Manager). 코드 수정 없이 바꾸려면 Google Sheets에 **`키워드 관리`** 탭을 만들고 첫 행에 `키워드`(필수)·`사용`(선택) 헤더를 둔 뒤 키워드를 한 줄씩 적으면 됩니다(시트가 있으면 시트 우선, 없으면 config 기본값).

```bash
# 기본 키워드 + 전체 플랫폼으로 1회 실행
python src/main.py autocollect

# 특정 키워드/플랫폼만, 키워드×플랫폼 당 최대 5건
python src/main.py autocollect -k "AI Engineer" -p 잡코리아 -l 5
```

## 매일 자동으로 알림 받기 (선택사항)

매일 아침 자동으로 마감 체크 + 지원 후속 체크를 하고 싶다면 cron을 설정합니다.

```bash
# cron 설정 열기
crontab -e

# 아래 줄 추가 (매일 아침 8시 마감/후속 알림)
0 8 * * * /프로젝트경로/jobmate-ai/scripts/cron_notify.sh

# 키워드 자동 수집 (1일 2회: 오전 9시 / 오후 6시) — 신규 기능
0 9  * * * /프로젝트경로/jobmate-ai/scripts/cron_autocollect.sh
0 18 * * * /프로젝트경로/jobmate-ai/scripts/cron_autocollect.sh
```

> `/프로젝트경로/`는 실제 프로젝트가 있는 경로로 바꿔주세요.
> 경로를 모르겠으면 프로젝트 폴더에서 `pwd` 명령어를 입력하면 확인할 수 있습니다.
>
> ⚠️ **macOS 자동 수집 주의**: 사람인은 봇 감지로 보이는 브라우저(headless=False)가 필요합니다. cron이 뜰 때 GUI 로그인 세션이 있어야 하며(09:00/18:00은 보통 충족), 프로젝트가 `~/Desktop` 하위면 '전체 디스크 접근 권한' 부여 또는 Desktop 밖으로 이동이 필요할 수 있습니다. (마감 알림 cron은 브라우저를 쓰지 않아 영향 없음.)

---

# 자주 묻는 질문

### Q. "source .venv/bin/activate"를 할 때마다 입력해야 하나요?

네, 터미널을 새로 열 때마다 한 번 입력해야 합니다. 터미널 앞에 `(.venv)`가 보이면 이미 활성화된 상태입니다.

### Q. 원티드 말고 다른 사이트도 되나요?

원티드·사람인·잡코리아·그룹바이는 전용 파서가 있어서 정확하게 추출합니다(Gemini 불필요 → 일일 한도와 무관). 점핏 등 그 외 사이트는 AI(Gemini)가 자동으로 분석합니다. 로켓펀치는 봇 차단 정책으로 인해 지원하지 않습니다.

### Q. 수집할 때 `Executable doesn't exist` / `playwright install` 에러가 떠요

크롤링용 브라우저가 아직 설치되지 않은 경우입니다. 가상환경을 활성화한 뒤 아래 명령을 한 번 실행하면 해결됩니다 (가상환경을 새로 만들면 다시 실행해야 합니다).

```bash
source .venv/bin/activate
playwright install chromium
```

### Q. Google Sheets에 데이터가 안 들어가요

- `.env` 파일의 `GOOGLE_SHEETS_ID`가 정확한지 확인하세요
- `credentials.json` 파일이 프로젝트 폴더에 있는지 확인하세요
- Google Sheets에서 서비스 계정 이메일에 **편집자** 권한을 줬는지 확인하세요

### Q. Slack 알림이 안 와요

- `.env` 파일의 `SLACK_WEBHOOK_URL`이 정확한지 확인하세요
- `python src/main.py notify`를 수동으로 실행해서 마감 임박 공고가 있는지 확인하세요
- 상시채용(rolling) 공고는 마감일이 없으므로 알림 대상이 아닙니다

---

# 프로젝트 구조

```
jobmate-ai/
├── README.md            # 이 문서
├── requirements.txt     # 필요한 라이브러리 목록
├── .env                 # API 키 등 비밀 정보 (GitHub 제외)
├── credentials.json     # Google 인증 파일 (GitHub 제외)
├── src/                 # 앱 소스
│   ├── app.py           # 웹 화면 (Streamlit)
│   ├── main.py          # 터미널 프로그램 (인터랙티브 + add/list/notify/status/autocollect)
│   ├── service.py       # 공통 로직 (웹·터미널 공유) + 대시보드 집계 + 자동 수집 오케스트레이션
│   ├── classify.py      # 규칙 기반 직군 분류 (Backend/Data/AI 등)
│   ├── config.py        # 설정값 (경로·시크릿·자동 수집 키워드/플랫폼)
│   ├── sheets.py        # Google Sheets 연동
│   ├── slack.py         # Slack 알림
│   ├── parsers/         # 사이트별 크롤링 모듈 (개별 공고 URL → JobPost)
│   │   ├── base.py      # 공통 인터페이스 + 유틸리티
│   │   ├── wanted.py    # 원티드 전용
│   │   ├── saramin.py   # 사람인 전용
│   │   ├── jobkorea.py  # 잡코리아 전용 (ld+json + iframe)
│   │   ├── groupby.py   # 그룹바이 전용 (__NEXT_DATA__ JSON)
│   │   └── fallback.py  # 기타 사이트 (Gemini AI 자동 추출)
│   └── searchers/       # 키워드 검색 모듈 (키워드 → 개별 공고 URL 목록) [신규]
│       ├── base.py      # 검색기 인터페이스 + URL 추출 순수 함수
│       ├── wanted.py    # 원티드 검색 (SPA 스크롤)
│       ├── saramin.py   # 사람인 검색 (headless=False)
│       └── jobkorea.py  # 잡코리아 검색 (서버 렌더링)
├── tests/               # 테스트 스크립트
│   ├── test_parsers.py           # 전용 파서 테스트
│   ├── test_fallback.py          # 폴백 파서 테스트
│   ├── test_classify.py          # 직군 분류 테스트
│   ├── test_dashboard_summary.py # 대시보드 집계(플랫폼/최근/인사이트) 테스트
│   ├── test_searchers.py         # 검색기 URL 추출 + 파서 계약 테스트 [신규]
│   └── test_auto_collect.py      # 자동 수집 오케스트레이션 테스트 [신규]
├── scripts/
│   ├── cron_notify.sh       # 자동 알림 스크립트 (cron)
│   └── cron_autocollect.sh  # 키워드 자동 수집 스크립트 (cron, 1일 2회) [신규]
├── data/                # 런타임 (GitHub 제외)
│   ├── cache.json       # 중복 방지용 캐시
│   └── jobmate.log      # 실행 로그
└── docs/                # 문서 (GitHub 제외)
```

## Google Sheets에 저장되는 항목

| 항목 | 설명 |
|------|------|
| URL | 원본 공고 링크 |
| 회사명 | 회사 이름 |
| 업종 | 업종/산업 분류 |
| 직원수 | 직원 규모 |
| 회사설명 | 회사 소개 |
| 포지션 | 채용 직무명 |
| 주요업무 | 업무 내용 |
| 자격요건 | 필수 자격 |
| 우대사항 | 우대 조건 |
| 마감일 | 지원 마감 날짜 |
| 상태 | interest(관심) / applied(지원완료) / document_pass(서류합격) / interview(면접) / final_pass(최종합격) / rejected(불합격) / hold(보류) |
| 비고 | 개인 메모 (상세 보기에서 편집) |

> 상태를 **지원완료**로 바꾸면 `지원일`이 자동 기록되고, 지원 후 **7일** 경과 시 Slack 후속 리마인더가 발송됩니다. 알림 발송 이력(`알림발송일`·`지원리마인더발송일`)도 자동 컬럼으로 관리됩니다(`STALE_APPLY_DAYS`로 기간 조정).

---

# 고도화 로드맵

- ✅ 로컬 웹 대시보드 (Streamlit) — 완료
- ✅ 대시보드 워크스페이스 재구성 (플랫폼 현황·최근 공고·상태 7단계 파이프라인·공고 상세 모달·개인 메모·D-day 색상·AI 인사이트) — 완료
- AI 3줄 요약 / 자동 태깅 (Gemini)
- 이력서 기반 적합도/추천
- 사람인 대기업 공채 엣지케이스 보강
- 기업 리뷰 자동 수집
- JD 기반 자소서 첨삭 AI

---

# 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 파일을 참고하세요. 본 코드는 개인 학습·연구용으로 제공되며, 사용에 따른 책임은 사용자에게 있습니다(상단 "사용 시 유의사항" 참고).
