# Agenstin

로컬에서 동작하는 AI 비서. CLI와 Slack 봇 두 가지 인터페이스를 제공합니다.

## 주요 기능

- **ReAct 엔진** — Think → Act → Observe 루프로 도구를 자율적으로 사용하여 답변 생성
- **듀얼 LLM** — Ollama(로컬) 또는 Anthropic Claude API 중 선택
- **Slack 봇** — Socket Mode 기반, DM/멘션 응답 + 채널 프로액티브 응답 + 인시던트 자동 분석
- **MCP 연동** — Codex 등 MCP 서버 도구를 사내 코드베이스 조회에 활용
- **메모리 시스템** — 마크다운 기반 장기 기억 + 하이브리드 검색 (벡터 + BM25)
- **10가지 내장 도구** — 파일 읽기, 쉘 실행, 웹 검색, 브라우징, Claude 에스컬레이션 등

## 아키텍처

```
인터페이스        main.py (CLI)  /  slack_app.py (Slack 봇)
                        │
코어 엔진         ReactEngine (core/react.py)
                  ├─ core/llm.py          LLM 호출 (Ollama / Anthropic)
                  ├─ core/mcp_prefetch.py  사내 키워드 감지 → MCP 선조회
                  └─ core/mcp_client.py    MCP 서버 연결/호출

도구 레이어       tools/
                  ├─ file_tool.py      파일 읽기/목록
                  ├─ shell_tool.py     읽기 전용 쉘 명령
                  ├─ search_tool.py    Google/Naver 웹 검색
                  ├─ browser_tool.py   웹페이지 텍스트/스크린샷
                  ├─ claude_tool.py    Claude CLI 에스컬레이션
                  └─ memory_tool.py    기억 검색/저장

메모리 레이어     memory/
                  ├─ manager.py   MemoryManager (파사드)
                  ├─ store.py     파일 I/O
                  ├─ chunker.py   마크다운 청크 분할
                  ├─ index.py     SQLite + BM25 + 벡터 인덱스
                  └─ embedder.py  Ollama 임베딩
```

## 요구사항

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (패키지 관리)
- [Ollama](https://ollama.ai/) (로컬 모델 사용 시)
- [Playwright](https://playwright.dev/) (브라우저 도구 사용 시)

## 설치

```bash
# 1. 저장소 클론
git clone <repo-url>
cd agenstin

# 2. 의존성 설치
uv sync

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키 등을 채워주세요

# 4. (선택) Ollama 모델 다운로드
ollama pull qwen2.5:14b
ollama pull nomic-embed-text  # 메모리 벡터 검색용

# 5. (선택) Playwright 브라우저 설치
uv run playwright install chromium
```

## 환경변수 (.env)

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic 사용 시 | Anthropic API 키 |
| `NAVER_CLIENT_ID` | 네이버 검색 시 | 네이버 Open API Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 검색 시 | 네이버 Open API Client Secret |
| `SLACK_BOT_TOKEN` | Slack 봇 사용 시 | Slack Bot User OAuth Token (`xoxb-`) |
| `SLACK_APP_TOKEN` | Slack 봇 사용 시 | Slack App-Level Token (`xapp-`) |
| `INCIDENT_WORKSPACE` | 인시던트 분석 시 | 인시던트 분석 대상 서브프로젝트 코드베이스 루트 경로 |

## 실행

### CLI 모드

```bash
uv run python main.py
```

터미널에서 대화형으로 사용합니다. `Enter`로 줄바꿈, `Esc+Enter`로 전송, `exit`로 종료.

### Slack 봇 모드

```bash
uv run python slack_app.py
```

Slack 앱 설정이 사전에 필요합니다:

1. https://api.slack.com/apps 에서 앱 생성
2. Socket Mode 활성화 → App-Level Token 발급 (`connections:write`)
3. OAuth & Permissions에서 Bot Token Scopes 추가:
   - `chat:write`, `reactions:write`, `reactions:read`
   - `app_mentions:read`, `im:history`, `im:read`, `im:write`
   - `channels:history`
4. Event Subscriptions에서 구독: `message.im`, `app_mention`, `message.channels`
5. `.env`에 토큰 설정
6. 봇을 채널에 초대: `/invite @Agenstin`

## Slack 봇 메시지 처리 흐름

Slack 봇은 메시지 유형에 따라 다르게 동작합니다:

```
Slack 메시지 수신
  │
  ├─ 인시던트 채널의 봇 메시지?
  │   └─ YES → Claude Opus (deep think)로 코드베이스 분석
  │            인시던트 텍스트에서 서브프로젝트 자동 식별
  │            → 해당 프로젝트 git pull → Claude CLI로 근본 원인 분석
  │            → 스레드에 분석 결과 전송
  │
  ├─ DM 또는 @멘션?
  │   └─ YES → ReactEngine으로 항상 응답
  │            스레드 컨텍스트 자동 조회
  │
  └─ 공개 채널 일반 메시지?
      └─ 사전 필터 (봇/시스템/짧은 메시지 제외)
         → 채널 쿨다운 확인 (2분)
         → LLM 스크리닝 (기술적 질문인지 판별)
         → 통과 시 이모지 리액션 + 스레드로 응답
```

### 인시던트 자동 분석

`config.py`의 `INCIDENT_CHANNEL_IDS`에 등록된 채널에서 봇 메시지(AlertNow 등)가 감지되면:

1. 인시던트 텍스트에서 서브프로젝트 키워드 매칭 (`INCIDENT_PROJECT_MAP`)
2. 해당 프로젝트 디렉토리에서 `git pull`로 최신 소스 확보
3. Claude CLI (Opus, effort high)로 코드베이스를 탐색하며 근본 원인 분석
4. 분석 결과를 스레드에 전송

인시던트 분석을 사용하려면:
- `.env`에 `INCIDENT_WORKSPACE` 설정 (서브프로젝트들이 있는 루트 디렉토리)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 설치 필요 (`claude` 명령이 PATH에 있어야 함)

## 팀별 커스터마이징

이 프로젝트는 호갱노노 팀 기준으로 기본 설정이 되어 있습니다. 다른 팀(예: 직방)에서 사용할 경우 아래 항목을 수정해야 합니다.

### 1. 인시던트 서브프로젝트 매핑 — `config.py:346`

`INCIDENT_PROJECT_MAP`에서 팀의 서브프로젝트에 맞게 키워드→디렉토리 매핑을 수정합니다.

```python
# 기본값 (호갱노노)
INCIDENT_PROJECT_MAP = {
    "hogangnono-batch": "hogangnono-batch",
    "hogangnono-api": "hogangnono-api",
    ...
}

# 예: 직방 팀으로 변경
INCIDENT_PROJECT_MAP = {
    "apt": "apt",
    "io-api": "io-api",
    "io-push": "io-push",
    ...
}
```

### 2. 인시던트 채널 ID — `config.py:336`

`INCIDENT_CHANNEL_IDS`를 팀의 인시던트 알림 채널로 변경합니다.

```python
INCIDENT_CHANNEL_IDS = [
    "C047Q9XDGAJ",  # ← 팀의 인시던트 채널 ID로 교체
]
```

### 3. MCP 선조회 키워드/레포 목록 — `core/mcp_prefetch.py:28, 40`

사용자 질문에서 사내 코드베이스 관련 질문을 감지하는 키워드와 알려진 레포 목록입니다.

```python
# _COMPANY_KEYWORDS (28행) — 사내 키워드 감지용
_COMPANY_KEYWORDS = [
    "직방", "zigbang", "호갱노노", "hogangnono",  # ← 팀 서비스명 추가/변경
    "apt", "io-api", ...
]

# _KNOWN_REPOS (40행) — MCP 조회 시 레포 이름 추출용
_KNOWN_REPOS = [
    "apt", "io-api", "io-push", ...
    "hogangnono", "hogangnono-api", ...  # ← 팀 레포명 추가/변경
]
```

### 수정 위치 요약

| 파일 | 위치 | 내용 | 비고 |
|------|------|------|------|
| `config.py` | `INCIDENT_PROJECT_MAP` | 인시던트 키워드 → 서브프로젝트 디렉토리 매핑 | 팀 프로젝트에 맞게 교체 |
| `config.py` | `INCIDENT_CHANNEL_IDS` | 인시던트 알림 Slack 채널 ID | 팀 채널로 교체 |
| `core/mcp_prefetch.py` | `_COMPANY_KEYWORDS` | 사내 질문 감지 키워드 | 팀 서비스/제품명 추가 |
| `core/mcp_prefetch.py` | `_KNOWN_REPOS` | MCP 조회 대상 레포 목록 | 팀 레포명 추가 |
| `.env` | `INCIDENT_WORKSPACE` | 코드베이스 루트 경로 | 로컬 환경에 맞게 설정 |

## 설정 (config.py)

`config.py`에서 동작을 조정할 수 있습니다:

| 구분 | 주요 설정 |
|------|----------|
| LLM | `LLM_PROVIDER` (`"ollama"` / `"anthropic"`), 모델명, temperature, max tokens |
| 보안 | 파일 경로 화이트리스트, 쉘 명령 화이트리스트, 위험 패턴 차단 |
| MCP | MCP 서버 목록, 타임아웃 |
| 메모리 | 임베딩 모델, 검색 가중치, 시간 감쇠 |
| Slack | 세션 만료, 채널 쿨다운, 프로액티브 리스너, 인시던트 분석 |

## 프로젝트 구조

```
agenstin/
├── main.py          # CLI 엔트리포인트
├── slack_app.py     # Slack 봇 엔트리포인트
├── config.py        # 전체 설정 (환경변수 + 동작 파라미터)
├── core/            # 코어 엔진
│   ├── llm.py           # LLM 클라이언트 (Ollama / Anthropic)
│   ├── react.py         # ReAct 루프 엔진
│   ├── mcp_client.py    # MCP 서버 연결
│   ├── mcp_prefetch.py  # 사내 키워드 → MCP 선조회
│   └── incident.py      # 인시던트 분석 (Claude Opus)
├── tools/           # 내장 도구
│   ├── base.py          # 도구 기본 클래스
│   ├── file_tool.py     # 파일 읽기/목록
│   ├── shell_tool.py    # 쉘 명령 실행
│   ├── search_tool.py   # Google/Naver 검색
│   ├── browser_tool.py  # 웹 브라우징/스크린샷
│   ├── claude_tool.py   # Claude CLI 에스컬레이션
│   └── memory_tool.py   # 기억 검색/저장
├── memory/          # 메모리 시스템
│   ├── manager.py       # MemoryManager (파사드)
│   ├── store.py         # 파일 I/O
│   ├── chunker.py       # 마크다운 청크 분할
│   ├── index.py         # SQLite + 하이브리드 검색
│   └── embedder.py      # Ollama 벡터 임베딩
├── pyproject.toml   # 프로젝트 메타 + 의존성
├── .env.example     # 환경변수 템플릿
└── .gitignore
```
