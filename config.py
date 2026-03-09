"""
Agenstin — 설정

Sonnet 라우터 + Claude Code CLI 아키텍처.
API 키 등 민감정보는 .env 파일에서 관리합니다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Anthropic API (Sonnet 라우터용)
# ──────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# 라우터 모델 — 스크리닝, 라우팅, 간단한 응답에 사용
ROUTER_MODEL = "claude-sonnet-4-6"

# 라우터 최대 응답 토큰
ROUTER_MAX_TOKENS = 4096

# ──────────────────────────────────────────────
# Claude Code CLI 설정
# ──────────────────────────────────────────────

# Claude CLI 실행 경로
CLAUDE_CLI_PATH = "claude"

# 일반 호출 타임아웃 (초)
CLAUDE_TIMEOUT = 120

# Deep Think (Opus) 타임아웃 (초)
CLAUDE_DEEP_TIMEOUT = 300

# 일반 호출 최대 출력 길이 (문자 수)
CLAUDE_MAX_OUTPUT_LENGTH = 10_000

# Deep Think 최대 출력 길이 (문자 수)
CLAUDE_DEEP_MAX_OUTPUT = 15_000

# ──────────────────────────────────────────────
# 메모리 설정 (마크다운 파일 기반)
# ──────────────────────────────────────────────

# 메모리 파일 저장 디렉토리 (SOUL.md, MEMORY.md, memory/*.md)
WORKSPACE_DIR = Path("~/.agenstin/workspace").expanduser()

# 시스템 프롬프트에 주입할 MEMORY.md 최대 길이 (문자)
MEMORY_EXCERPT_MAX_LENGTH = 2000

# 일별 로그 최대 크기 (바이트)
DAILY_LOG_MAX_SIZE = 50_000

# ──────────────────────────────────────────────
# Slack 봇 설정
# ──────────────────────────────────────────────

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

# Slack 메시지 최대 길이 (Slack API 제한: ~4000자)
SLACK_MAX_MESSAGE_LENGTH = 3900

# 세션 관리
SLACK_MAX_TURNS_PER_SESSION = 50
SLACK_SESSION_TIMEOUT = 3600  # 1시간

# ──────────────────────────────────────────────
# Slack 채널 프로액티브 리스너 설정
# ──────────────────────────────────────────────

SLACK_CHANNEL_LISTENER_ENABLED = True
SLACK_CHANNEL_MIN_MESSAGE_LENGTH = 10
SLACK_CHANNEL_COOLDOWN = 60  # 초

# ──────────────────────────────────────────────
# 인시던트 분석 설정
# ──────────────────────────────────────────────

INCIDENT_ANALYSIS_ENABLED = True

INCIDENT_CHANNEL_IDS: list[str] = [
    "C047Q9XDGAJ",
]

INCIDENT_WORKSPACE = os.environ.get("INCIDENT_WORKSPACE", "")

INCIDENT_PROJECT_MAP: dict[str, str] = {
    "hogangnono-batch": "hogangnono-batch",
    "hogangnono-api": "hogangnono-api",
    "hogangnono-bot": "hogangnono-bot",
    "hogangnono": "hogangnono",
    "product-codex": "product-codex",
}

# 인시던트 분석 Claude 타임아웃 (초)
INCIDENT_CLAUDE_TIMEOUT = 600  # 10분

# ──────────────────────────────────────────────
# 프롬프트
# ──────────────────────────────────────────────

# 채널 메시지 스크리닝 프롬프트 (YES/NO + 이모지)
SCREENING_PROMPT = """You are a relevance classifier for an AI assistant bot in a Slack workspace.

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

# Sonnet 라우터 시스템 프롬프트
ROUTER_SYSTEM_PROMPT = """\
당신은 Agenstin, 로컬에서 동작하는 AI 비서입니다.
한국어로 답변하되, 기술 용어는 영어 그대로 사용합니다.

## 응답 방식
- 직접 답변할 수 있는 질문 (인사, 일반 지식, 간단한 설명, 의견 등)에는 **바로 답변**하세요.
- 아래에 해당하는 복잡한 작업은 반드시 **첫 줄에 `[DELEGATE]`만** 출력하세요:
  - 코드 분석, 코드베이스 탐색
  - 파일 읽기/쓰기, 쉘 명령 실행
  - 사내(직방/호갱노노) 코드베이스 관련 질문
  - 복잡한 추론, 아키텍처 설계
  - 웹 검색, 브라우징이 필요한 질문
  - PR 생성, 코드 수정 등 개발 작업

## 주의
- [DELEGATE] 출력 시 다른 텍스트를 추가하지 마세요.
- 간결하고 실용적으로 답변하세요.
"""

# 인시던트 분석 프롬프트 (Claude CLI에 전달)
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

# 시스템 프롬프트 (메모리 컨텍스트와 합쳐서 사용)
SYSTEM_PROMPT = """\
당신은 Agenstin, 로컬에서 동작하는 AI 비서입니다.

## 역할
- 사용자의 질문에 간결하고 실용적으로 답변합니다.
- 한국어로 답변하되, 기술 용어는 영어 그대로 사용합니다.
- 사내(직방/호갱노노) 코드베이스에 대한 지식이 있습니다.
"""
