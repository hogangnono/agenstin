"""
Agenstin — 로컬 AI 비서 설정

모든 보안/동작 관련 설정을 이 파일에서 관리합니다.
API 키 등 민감정보는 .env 파일에서 관리합니다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# LLM 프로바이더 설정
# ──────────────────────────────────────────────

# 사용할 LLM 프로바이더: "ollama" 또는 "anthropic"
LLM_PROVIDER = "anthropic"

# ──────────────────────────────────────────────
# Anthropic API 설정 (LLM_PROVIDER = "anthropic" 일 때)
# ──────────────────────────────────────────────

# API 키 (.env 파일에서 로드)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# 사용할 Anthropic 모델 이름
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# ──────────────────────────────────────────────
# Ollama 설정 (LLM_PROVIDER = "ollama" 일 때, 임베딩에도 사용)
# ──────────────────────────────────────────────

# Ollama 서버 주소 (기본: 로컬)
OLLAMA_HOST = "http://localhost:11434"

# 사용할 Ollama 모델 이름
OLLAMA_MODEL = "qwen2.5:14b"

# ──────────────────────────────────────────────
# 공통 모델 설정
# ──────────────────────────────────────────────

# 모델 응답 온도 (0.0 = 결정적, 1.0 = 창의적)
# tool calling 시에는 낮은 값 권장
TEMPERATURE = 0.7

# 최대 응답 토큰 수
# 너무 크면 느려지고, 너무 작으면 답변이 잘림
MAX_TOKENS = 4096

# ReAct 루프 최대 반복 횟수
# 무한 루프 방지. tool을 이만큼 연속 호출하면 강제 종료
MAX_REACT_ITERATIONS = 10

# Extended Thinking 설정 (Ollama 전용)
# deepseek-r1, qwq 등 thinking 모델 사용 시 True로 변경
# 모델이 think를 지원하지 않으면 이 설정은 무시됨
ENABLE_THINKING = False

# Thinking 과정(추론 과정)을 콘솔에 실시간 표시할지 여부
# False이면 thinking을 수집만 하고 표시하지 않음
SHOW_THINKING = True

# ──────────────────────────────────────────────
# Claude Code 에스컬레이션 설정
# ──────────────────────────────────────────────

# Claude CLI 실행 경로
CLAUDE_CLI_PATH = "claude"

# Claude 호출 타임아웃 (초)
# 복잡한 질문은 오래 걸릴 수 있으므로 넉넉히
CLAUDE_TIMEOUT = 120

# Claude Deep Think 타임아웃 (초)
# opus + effort high는 시간이 더 걸리므로 넉넉히
CLAUDE_THINK_TIMEOUT = 300

# Claude 응답 최대 길이 (문자 수)
# subprocess 출력이 너무 길면 잘라냄
CLAUDE_MAX_OUTPUT_LENGTH = 10000

# ──────────────────────────────────────────────
# 파일/경로 보안 설정
# ──────────────────────────────────────────────

# 파일 접근이 허용되는 디렉토리 목록
# 이 경로 하위만 read_file, list_files로 접근 가능
# ~ 는 자동으로 홈 디렉토리로 확장됨
PATH_WHITELIST = [
    "~/Projects",
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
]

# 파일 읽기 시 최대 크기 (바이트)
# 너무 큰 파일을 읽으면 토큰 낭비 + 느려짐
MAX_FILE_READ_SIZE = 100_000  # 100KB

# ──────────────────────────────────────────────
# Shell 보안 설정
# ──────────────────────────────────────────────

# 허용되는 쉘 명령어 목록 (읽기 전용만)
# 이 목록에 없는 명령어는 실행 차단
SHELL_COMMAND_WHITELIST = [
    "ls", "cat", "grep", "find", "wc",
    "head", "tail", "file", "du", "df",
    "pwd", "whoami", "date", "echo",
    "tree", "stat", "which", "env",
]

# 쉘 명령어에서 차단할 위험 문자/패턴
# 명령어 체이닝, 리다이렉션 등을 방지
SHELL_DANGEROUS_PATTERNS = [
    ";", "&&", "||",       # 명령어 체이닝
    "|",                    # 파이프 (데이터 유출 가능)
    ">", ">>",             # 파일 쓰기/추가
    "<",                    # 파일 입력 리다이렉션
    "`",                    # 백틱 명령어 치환
    "$(", "${",            # 변수/명령어 치환
    "\n",                   # 줄바꿈 (명령어 삽입)
    "rm", "mv", "cp",     # 파일 변경 명령어 (인자로 들어올 수 있으므로)
    "sudo", "su",          # 권한 상승
    "chmod", "chown",      # 권한 변경
    "kill", "pkill",       # 프로세스 제어
    "curl", "wget",        # 네트워크 요청 (search_tool 사용할 것)
]

# Shell 출력 최대 길이 (문자 수)
# 긴 출력은 잘라서 토큰 절약
MAX_OUTPUT_LENGTH = 10_000

# Shell 명령어 타임아웃 (초)
SHELL_TIMEOUT = 30

# ──────────────────────────────────────────────
# 웹 검색 설정
# ──────────────────────────────────────────────

# 검색 결과 최대 개수
SEARCH_MAX_RESULTS = 5

# 네이버 Open API 설정 (.env 파일에서 로드)
# 발급: https://developers.naver.com > 애플리케이션 등록 > 검색 API 선택
# 무료 (일 25,000회 제한)
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

# ──────────────────────────────────────────────
# 브라우저 설정
# ──────────────────────────────────────────────

# 브라우저 접근 차단 URL 패턴
# 로컬 서비스 보호를 위해 내부 주소 차단
BROWSER_URL_BLACKLIST = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "192.168.",     # 사설 네트워크
    "10.",          # 사설 네트워크
    "172.16.",      # 사설 네트워크
]

# 브라우저 페이지 로드 타임아웃 (밀리초)
BROWSER_TIMEOUT = 30_000

# 페이지 텍스트 최대 길이 (문자 수)
# 웹페이지 전체를 가져오면 토큰 폭발하므로 제한
BROWSER_MAX_TEXT_LENGTH = 10_000

# 스크린샷 저장 경로
BROWSER_SCREENSHOT_DIR = "~/.agenstin/screenshots"

# ──────────────────────────────────────────────
# 메모리 설정 (OpenClaw 방식 — 마크다운 파일 + 하이브리드 검색)
# ──────────────────────────────────────────────

# 메모리 파일 저장 디렉토리 (SOUL.md, MEMORY.md, memory/*.md)
WORKSPACE_DIR = Path("~/.agenstin/workspace").expanduser()

# SQLite 인덱스 저장 디렉토리
INDEX_DIR = Path("~/.agenstin/index").expanduser()
INDEX_DB_PATH = INDEX_DIR / "memory.sqlite"

# 임베딩 모델 (Ollama)
# 사전 설치 필요: ollama pull nomic-embed-text
# 모델이 없으면 BM25 키워드 검색만으로 동작 (graceful fallback)
EMBED_MODEL = "nomic-embed-text"

# 청크 설정
# 마크다운을 이 크기의 청크로 분할하여 검색 인덱스에 저장
CHUNK_SIZE = 400       # 청크당 토큰 수 (근사치)
CHUNK_OVERLAP = 80     # 청크 간 오버랩 토큰 수
CHARS_PER_TOKEN = 3    # 한영 혼용 시 토큰당 평균 문자 수

# 검색 설정
SEARCH_TOP_K = 5                    # 검색 결과 최대 개수
SEARCH_VECTOR_WEIGHT = 0.7          # 벡터 유사도 비중 (0.0 ~ 1.0)
SEARCH_BM25_WEIGHT = 0.3            # BM25 키워드 비중 (0.0 ~ 1.0)
SEARCH_DECAY_HALF_LIFE_DAYS = 30    # 시간 감쇠 반감기 (일). 30일 → 30일 전 기억은 50% 가중

# 시스템 프롬프트에 주입할 MEMORY.md 최대 길이 (문자)
MEMORY_EXCERPT_MAX_LENGTH = 2000

# 일별 로그 최대 크기 (바이트)
DAILY_LOG_MAX_SIZE = 50_000

# ──────────────────────────────────────────────
# MCP (Model Context Protocol) 설정
# ──────────────────────────────────────────────

# MCP 서버 목록
# 각 서버는 name, url, enabled 로 구성
# 서버가 제공하는 도구들이 자동으로 ReAct 루프에 등록됨
MCP_SERVERS = [
    {
        "name": "codex",
        "url": "https://codex.zigbang.io/mcp",
        "enabled": True,
    },
    # 추가 MCP 서버 예시:
    # {
    #     "name": "another-server",
    #     "url": "https://example.com/mcp",
    #     "enabled": False,
    # },
]

# MCP 서버 연결 타임아웃 (초)
MCP_CONNECT_TIMEOUT = 30

# MCP 도구 호출 타임아웃 (초)
MCP_CALL_TIMEOUT = 60

# MCP 도구 결과 최대 길이 (문자 수)
MCP_MAX_RESULT_LENGTH = 15_000

# ──────────────────────────────────────────────
# Slack 봇 설정
# ──────────────────────────────────────────────

# Slack 봇 토큰 (.env 파일에서 로드)
# 발급: Slack 앱 설정 > OAuth & Permissions > Bot User OAuth Token
# 필요 스코프: chat:write, reactions:write, reactions:read,
#              app_mentions:read, im:history, im:read, im:write
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Slack 앱 레벨 토큰 (.env 파일에서 로드)
# Socket Mode 사용 시 필요 (공인 IP 없이 로컬에서 실행 가능)
# 발급: Slack 앱 설정 > Basic Information > App-Level Tokens
# 스코프: connections:write
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

# Slack 메시지 최대 길이 (Slack API 제한: ~4000자)
# 초과 시 코드블록/단락 경계에서 자동 분할
SLACK_MAX_MESSAGE_LENGTH = 3900

# Slack 채널/DM별 최대 대화 턴 수
# 초과 시 오래된 메시지부터 자동 삭제 (system 메시지는 유지)
SLACK_MAX_TURNS_PER_SESSION = 50

# Slack 세션 만료 시간 (초)
# 마지막 메시지 이후 이 시간이 지나면 대화 컨텍스트 초기화
# 기본 3600 = 1시간
SLACK_SESSION_TIMEOUT = 3600

# ──────────────────────────────────────────────
# Slack 채널 프로액티브 리스너 설정
# ──────────────────────────────────────────────

# 채널 메시지 자동 감지 및 응답 기능 활성화
SLACK_CHANNEL_LISTENER_ENABLED = True

# 스크리닝 LLM 호출 시 최대 토큰 수 (빠른 응답을 위해 낮게)
SLACK_SCREENING_MAX_TOKENS = 64

# 스크리닝에 사용할 모델 (None이면 OLLAMA_MODEL 사용)
# 더 작은/빠른 모델이 있다면 여기에 지정 (예: "qwen2.5:7b")
SLACK_SCREENING_MODEL = None

# 메시지 최소 길이 (이보다 짧은 메시지는 스크리닝 없이 무시)
SLACK_CHANNEL_MIN_MESSAGE_LENGTH = 10

# 채널당 쿨다운 (초). 마지막 자동 응답 이후 이 시간 내에는 같은 채널에 다시 응답하지 않음.
SLACK_CHANNEL_COOLDOWN = 60  # 1분

# 스크리닝 프롬프트 (YES/NO 분류 + 이모지 선택)
SLACK_SCREENING_PROMPT = """You are a relevance classifier for an AI assistant bot in a Slack workspace.

Given a channel message, decide: should the AI bot proactively reply to this message?

Reply YES if ANY of these are true:
1. The message is a question, request for help, or describes a problem/error
2. The message shares information or an opinion where an AI assistant could add useful context
3. The topic is technical, knowledge-based, or factual
4. The message discusses a decision or trade-off where additional perspective would help

Reply NO if ANY of these are true:
- It's casual conversation, small talk, greetings, or purely social messages
- It's clearly part of an ongoing human-to-human conversation directed at a specific person
- It's a simple status update or announcement that doesn't invite discussion
- A bot jumping in would clearly feel intrusive

If YES, also pick the single most fitting emoji from this list:
- eyes: interesting, I'll look into this
- bulb: good idea, insight
- thinking_face: thought-provoking question
- rocket: exciting, ambitious
- dart: on point, precise
- star: excellent point
- fire: hot topic, impressive
- raised_hands: great achievement, celebration
- memo: noteworthy information
- white_check_mark: confirmed, correct

Response format (EXACTLY):
  YES emoji_name
  or
  NO"""

# ──────────────────────────────────────────────
# 인시던트 분석 설정
# ──────────────────────────────────────────────

# 인시던트 분석 기능 활성화
INCIDENT_ANALYSIS_ENABLED = True

# 인시던트 알림이 들어오는 Slack 채널 ID 목록
INCIDENT_CHANNEL_IDS: list[str] = [
    "C047Q9XDGAJ",
]

# 인시던트 분석 대상 워크스페이스 루트 경로 (.env 파일에서 로드)
INCIDENT_WORKSPACE = os.environ.get("INCIDENT_WORKSPACE", "")

# 서브프로젝트 매핑: 키워드 → 디렉토리명
# 인시던트 텍스트에서 키워드를 감지하여 해당 프로젝트 디렉토리에서 Claude를 실행
# (코드에서 긴 키워드부터 매칭하므로 순서 무관)
INCIDENT_PROJECT_MAP: dict[str, str] = {
    "hogangnono-batch": "hogangnono-batch",
    "hogangnono-api": "hogangnono-api",
    "hogangnono-bot": "hogangnono-bot",
    "hogangnono": "hogangnono",
    "product-codex": "product-codex",
}

# 인시던트 분석 Claude 타임아웃 (초)
# 코드베이스를 탐색하며 분석하므로 넉넉히
INCIDENT_CLAUDE_TIMEOUT = 600  # 10분

# 인시던트 분석 Claude 출력 최대 길이 (문자 수)
INCIDENT_CLAUDE_MAX_OUTPUT = 15000

# 인시던트 분석 시스템 프롬프트
INCIDENT_ANALYSIS_PROMPT = """\
You are a senior SRE/backend engineer analyzing a production incident.

## Your Task
Analyze the incident alert below, find the root cause, and **fix the code if possible**.

## Instructions
1. Parse the incident message to identify:
   - The error type/name
   - The affected service or component
   - Any error codes, HTTP status codes, or stack traces
   - Timestamps and frequency if available

2. Search through the codebase to find:
   - The relevant source code that could cause this error
   - Related error handling logic
   - Configuration that might be misconfigured
   - Recent patterns that could explain the failure

3. **If the root cause is clear and you can fix it:**
   - Create a fix branch: `git checkout -b fix/incident-<간단한설명>`
   - Edit the code to fix the issue
   - Commit: `git add <files> && git commit -m "fix: <설명>"`
   - Push: `git push -u origin fix/incident-<간단한설명>`
   - Create PR: `gh pr create --title "fix: <설명>" --body "<분석 내용 요약>"`
   - Return to the original branch: `git checkout -`

4. Provide your analysis in this format:

### 인시던트 요약
- 에러 유형과 영향 범위를 간결하게 설명

### 원인 분석
- 코드에서 찾은 근본 원인
- 관련 파일과 함수 명시 (파일 경로 포함)

### 관련 코드
- 핵심 코드 스니펫 인용 (간결하게)

### 수정 내용
- 변경한 파일과 수정 내용 (수정한 경우)
- PR URL (생성한 경우)
- 수정하지 않은 경우 그 이유

### 권장 조치
- 즉시 조치 사항 (핫픽스)
- 장기 개선 사항

### 추가 확인 필요
- 불확실한 부분이나 추가 조사가 필요한 항목

## Important
- Answer in Korean
- Be specific: include file paths, function names, line numbers when possible
- If you cannot determine the root cause with certainty, say so and list the most probable causes
- Only create a fix if you are confident in the root cause. When in doubt, provide analysis only.
- Focus on actionable information
"""

# 인시던트 ReactEngine 시스템 프롬프트 — 트리아지 + claude_escalate 위임
INCIDENT_REACTENGINE_PROMPT = """\
당신은 프로덕션 인시던트를 분석하는 시니어 SRE/백엔드 엔지니어입니다.

## 역할
인시던트 알림 메시지를 받아 **분류**하고, 필요 시 **코드베이스 분석**을 수행합니다.

## 판단 기준

### 단순 알림 (직접 응답)
아래에 해당하면 **claude_escalate 없이** 간결하게 요약만 합니다:
- 인시던트 해제/복구 알림 (resolved, recovered, cleared)
- 상태 변경 알림 (acknowledged, assigned, escalated)
- 단순 임계치 초과 후 자동 복구
- 정보성 알림 (스케줄 알림, 배포 완료 등)

### 코드 분석 필요 (claude_escalate 사용)
아래에 해당하면 **반드시** `claude_escalate` 도구를 `deep_think=true`로 호출하세요:
- 에러/예외 발생 (500 에러, Exception, stack trace 포함)
- 서비스 장애/다운 (timeout, connection refused, OOM 등)
- 비정상 패턴 (급격한 에러율 증가, 지연 시간 급등)
- 원인 파악이 필요한 모든 경우

## claude_escalate 사용법
코드 분석이 필요할 때:
```
claude_escalate(
    question="<인시던트 분석 프롬프트 + 알림 내용>",
    deep_think=true,
    cwd="<프로젝트 경로>",
    timeout=600
)
```

question에는 아래 내용을 포함하세요:
1. 인시던트 요약 (에러 유형, 영향 범위)
2. 코드베이스에서 찾아야 할 것 (관련 소스, 에러 핸들링, 설정)
3. 분석 결과 형식 지정 (인시던트 요약 / 원인 분석 / 관련 코드 / 수정 내용 / 권장 조치)
4. 근본 원인이 명확하면 fix 브랜치 생성, 코드 수정, commit, push, PR 생성까지 수행하라는 지시

## 응답 형식
- 한국어로 답변
- 파일 경로, 함수명, 라인 번호를 구체적으로 명시
- 불확실한 부분은 명시하고 가능한 원인을 나열
- PR이 생성되었으면 PR URL을 반드시 포함
"""

# ──────────────────────────────────────────────
# 시스템 프롬프트
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 Agenstin, 로컬에서 동작하는 AI 비서입니다.

## 역할
- 사용자의 파일 관리, 정보 검색, 시스템 조회를 돕습니다.
- 한국어로 답변하되, 기술 용어는 영어 그대로 사용합니다.
- 간결하고 실용적으로 답변합니다.

## 사내 코드베이스 (자동 조회)
- 직방/호갱노노 관련 질문은 시스템이 자동으로 사내 코드베이스를 먼저 조회합니다.
- 조회 결과가 system 메시지로 제공되면, 그 내용을 기반으로 정확하게 답변하세요.
- 조회 결과가 부족하면 그 사실을 알려주고, 추가 질문을 유도하세요.

## 도구 사용 원칙
- 질문에 답하기 위해 도구가 필요하면 적극적으로 사용하세요.
- 도구 없이 답할 수 있는 일반 대화는 그냥 답하세요.
- 도구 실행 결과를 사용자에게 읽기 쉽게 정리해서 전달하세요.
- 사내와 무관한 일반 정보가 필요하면 web_search를 사용하세요.

## 에스컬레이션
- 복잡한 코드 분석, 논리적 추론, 전문 지식이 필요하면 claude_escalate를 사용하세요.
- 단순한 파일 조회, 검색, 일상 대화는 직접 처리하세요.
"""
