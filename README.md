# Agenstin

Sonnet 라우터 + Claude Code CLI 기반 AI 비서. CLI와 Slack 봇 두 가지 인터페이스를 제공합니다.

## 아키텍처

```
메시지 수신 (CLI / Slack)
  │
  ├─ Sonnet 라우터 (claude-sonnet-4-6)
  │   ├─ 채널 메시지 스크리닝 (응답할 가치 판별)
  │   ├─ 간단한 질문 → Sonnet이 직접 답변
  │   └─ 복잡한 작업 → [DELEGATE] → Claude Code CLI
  │
  ├─ Claude Code CLI
  │   ├─ 코드 분석, 파일 탐색, 쉘 명령
  │   ├─ MCP 연동 (Claude Code 네이티브 설정)
  │   └─ 웹 검색, 브라우징
  │
  └─ 인시던트 분석
      └─ Claude Opus (deep think) → 코드베이스 근본 원인 분석 + PR 생성
```

## 주요 기능

- **Sonnet 라우터** — 빠르고 저렴한 Sonnet으로 메시지 분류 및 간단한 응답
- **Claude Code CLI 위임** — 복잡한 코드 분석, 파일 탐색 등은 Claude Code에 위임
- **Slack 봇** — Socket Mode 기반, DM/멘션 응답 + 채널 프로액티브 응답 + 인시던트 자동 분석
- **메모리 시스템** — SOUL.md (성격) + MEMORY.md (장기 기억) + 일별 로그

## 요구사항

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (패키지 관리)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` 명령이 PATH에 있어야 함)

## 설치

```bash
# 1. 저장소 클론
git clone <repo-url>
cd agenstin

# 2. 의존성 설치
uv sync

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY를 채워주세요

# 4. Claude Code CLI 설치 (아직 없다면)
npm install -g @anthropic-ai/claude-code
```

## 환경변수 (.env)

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | 필수 | Anthropic API 키 (Sonnet 라우터용) |
| `SLACK_BOT_TOKEN` | Slack 사용 시 | Slack Bot User OAuth Token (`xoxb-`) |
| `SLACK_APP_TOKEN` | Slack 사용 시 | Slack App-Level Token (`xapp-`) |
| `INCIDENT_WORKSPACE` | 인시던트 분석 시 | 서브프로젝트 코드베이스 루트 경로 |

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

```
Slack 메시지 수신
  │
  ├─ 인시던트 채널의 봇 메시지?
  │   └─ YES → Claude Opus (deep think)로 코드베이스 분석
  │            → 스레드에 분석 결과 + PR URL 전송
  │
  ├─ DM 또는 @멘션?
  │   └─ YES → Sonnet 라우터로 응답
  │            간단한 질문 → 직접 답변
  │            복잡한 작업 → Claude Code CLI 위임
  │
  └─ 공개 채널 일반 메시지?
      └─ Sonnet 스크리닝 (기술적 질문인지 판별)
         → 통과 시 이모지 리액션 + 스레드로 응답
```

### 인시던트 자동 분석

`config.py`의 `INCIDENT_CHANNEL_IDS`에 등록된 채널에서 봇 메시지(AlertNow 등)가 감지되면:

1. 인시던트 텍스트에서 서브프로젝트 키워드 매칭 (`INCIDENT_PROJECT_MAP`)
2. 해당 프로젝트 디렉토리에서 `git pull`로 최신 소스 확보
3. Claude Code CLI (Opus, effort high)로 코드베이스를 탐색하며 근본 원인 분석
4. 근본 원인이 명확하면 fix 브랜치 생성 + PR 생성
5. 분석 결과를 스레드에 전송

## 팀별 커스터마이징

### 1. 인시던트 서브프로젝트 매핑 — `config.py`

```python
INCIDENT_PROJECT_MAP = {
    "hogangnono-batch": "hogangnono-batch",
    "hogangnono-api": "hogangnono-api",
    ...
}
```

### 2. 인시던트 채널 ID — `config.py`

```python
INCIDENT_CHANNEL_IDS = [
    "C047Q9XDGAJ",  # ← 팀의 인시던트 채널 ID로 교체
]
```

## 설정 (config.py)

| 구분 | 주요 설정 |
|------|----------|
| Sonnet 라우터 | `ROUTER_MODEL`, `ROUTER_MAX_TOKENS` |
| Claude CLI | `CLAUDE_CLI_PATH`, `CLAUDE_TIMEOUT`, `CLAUDE_DEEP_TIMEOUT` |
| 메모리 | `WORKSPACE_DIR`, `MEMORY_EXCERPT_MAX_LENGTH` |
| Slack | 세션 만료, 채널 쿨다운, 프로액티브 리스너 |
| 인시던트 | 채널 ID, 프로젝트 매핑, 타임아웃 |

## 프로젝트 구조

```
agenstin/
├── main.py          # CLI 엔트리포인트
├── slack_app.py     # Slack 봇 엔트리포인트
├── config.py        # 전체 설정
├── core/
│   ├── router.py        # Sonnet 라우터 (스크리닝 + 라우팅 + 응답)
│   ├── claude_cli.py    # Claude Code CLI 래퍼
│   └── incident.py      # 인시던트 분석
├── memory/
│   ├── manager.py       # MemoryManager (파사드)
│   └── store.py         # 파일 I/O (SOUL.md, MEMORY.md, 일별 로그)
├── pyproject.toml
├── .env.example
└── .gitignore
```
