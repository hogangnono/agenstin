"""Agenstin — Slack 봇 인터페이스

Socket Mode로 동작하는 Slack 봇.
DM과 @멘션 이벤트를 처리하여 ReactEngine으로 응답합니다.

사전 준비:
  1. https://api.slack.com/apps 에서 앱 생성
  2. Socket Mode 활성화 → App-Level Token 발급 (connections:write)
  3. OAuth & Permissions에서 Bot Token Scopes 추가:
     chat:write, reactions:write, reactions:read,
     app_mentions:read, im:history, im:read, im:write,
     channels:history
  4. Event Subscriptions에서 구독 이벤트 추가:
     message.im, app_mention, message.channels
  5. config.py에 SLACK_BOT_TOKEN, SLACK_APP_TOKEN 설정
  6. 봇을 채널에 초대: /invite @Agenstin

실행:
  uv run python slack_app.py
"""

import logging
import re
import sys
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import config
from core import llm
from core.incident import analyze_incident, is_incident_channel, resolve_project
from core.mcp_client import McpManager
from core.react import ReactEngine
from memory.manager import MemoryManager
from tools.browser_tool import BrowseWebTool, ScreenshotTool
from tools.claude_tool import ClaudeEscalateTool
from tools.file_tool import ListFilesTool, ReadFileTool
from tools.memory_tool import MemorySearchTool, MemorySaveTool
from tools.search_tool import GoogleSearchTool, NaverSearchTool
from tools.shell_tool import ShellTool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("agenstin.slack")

# ──────────────────────────────────────────────
# 채널/DM별 세션 관리
# ──────────────────────────────────────────────

# {channel_id: {"messages": [...], "last_active": float}}
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

# 채널별 마지막 자동 응답 시각 (쿨다운 관리)
_channel_last_reply: dict[str, float] = {}
_channel_last_reply_lock = threading.Lock()


def _get_session(channel_id: str, system_prompt: str) -> list[dict]:
    """채널/DM별 메시지 목록을 반환. 만료 시 초기화."""
    with _sessions_lock:
        now = time.time()
        session = _sessions.get(channel_id)

        if (
            session is None
            or (now - session["last_active"]) > config.SLACK_SESSION_TIMEOUT
        ):
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            _sessions[channel_id] = {"messages": messages, "last_active": now}
            return messages

        session["last_active"] = now
        return session["messages"]


def _trim_session(messages: list[dict]) -> None:
    """세션의 대화 턴 수를 제한. system 메시지는 유지."""
    max_non_system = config.SLACK_MAX_TURNS_PER_SESSION * 2  # user+assistant 쌍
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) > max_non_system:
        system_msgs = [m for m in messages if m.get("role") == "system"]
        trimmed = non_system[-max_non_system:]
        messages.clear()
        messages.extend(system_msgs + trimmed)


# ──────────────────────────────────────────────
# 초기화 (main.py 패턴 재사용)
# ──────────────────────────────────────────────


def _build_local_tools(memory_manager: MemoryManager):
    """로컬 도구 목록 (모델에 직접 노출)"""
    return [
        ListFilesTool(),
        ReadFileTool(),
        ShellTool(),
        GoogleSearchTool(),
        NaverSearchTool(),
        ClaudeEscalateTool(),
        BrowseWebTool(),
        ScreenshotTool(),
        MemorySearchTool(memory_manager),
        MemorySaveTool(memory_manager),
    ]


def _build_system_prompt(memory_manager: MemoryManager) -> str:
    """시스템 프롬프트: SOUL.md + MEMORY.md 발췌 + 도구 안내"""
    parts = [config.SYSTEM_PROMPT]

    soul = memory_manager.get_soul()
    if soul:
        parts.append(f"## 에이전트 성격\n{soul}")

    memory_excerpt = memory_manager.get_memory_excerpt()
    if memory_excerpt:
        parts.append(f"## 기억된 정보\n{memory_excerpt}")

    parts.append(
        "## 메모리 사용 안내\n"
        "- 과거 대화나 사용자 선호를 알아야 하면 memory_search를 사용하세요.\n"
        "- 중요한 사실(사용자 선호, 프로젝트 정보 등)을 발견하면 memory_save로 기억하세요.\n"
        "- 사용자가 '기억해', 'remember this' 등을 말하면 반드시 memory_save를 사용하세요.\n"
        "- 사소한 대화는 저장하지 마세요. 반복적으로 유용할 정보만 저장하세요."
    )

    return "\n\n".join(parts)


# ──────────────────────────────────────────────
# 메시지 분할 (Slack 4000자 제한 대응)
# ──────────────────────────────────────────────


def _split_message(text: str) -> list[str]:
    """긴 메시지를 Slack 제한에 맞게 분할.

    분할 우선순위:
    1. 코드블록(```) 경계
    2. 빈 줄 (단락 경계)
    3. 줄바꿈
    4. 강제 절단
    """
    max_len = config.SLACK_MAX_MESSAGE_LENGTH

    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        cut = _find_split_point(remaining, max_len)
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")

    return chunks


def _find_split_point(text: str, max_len: int) -> int:
    """최적 분할 지점 탐색"""
    segment = text[:max_len]

    # 1순위: 코드블록 닫힘 직후
    code_end = segment.rfind("```\n")
    if code_end > max_len // 2:
        return code_end + 4

    # 2순위: 빈 줄 (단락 경계)
    double_nl = segment.rfind("\n\n")
    if double_nl > max_len // 2:
        return double_nl + 2

    # 3순위: 줄바꿈
    single_nl = segment.rfind("\n")
    if single_nl > max_len // 3:
        return single_nl + 1

    # 4순위: 강제 절단
    return max_len


# ──────────────────────────────────────────────
# 메시지 전처리
# ──────────────────────────────────────────────

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def _extract_full_text(msg: dict) -> str:
    """Slack 메시지에서 text + attachments + blocks 내용을 모두 추출.

    Slack 앱(AlertNow 등)이 보낸 메시지는 본문 text 외에
    attachments나 blocks에 상세 내용이 담겨 있으므로 모두 합친다.
    """
    parts: list[str] = []

    # 1. 기본 text 필드
    text = msg.get("text", "").strip()
    if text:
        parts.append(text)

    # 2. attachments (legacy 형식 — AlertNow 등 많은 앱이 사용)
    for att in msg.get("attachments") or []:
        for field_name in ("pretext", "text", "fallback"):
            val = att.get(field_name, "").strip()
            if val and val not in parts:
                parts.append(val)
        # attachment fields (title/value 쌍)
        for field in att.get("fields") or []:
            title = field.get("title", "").strip()
            value = field.get("value", "").strip()
            entry = f"{title}: {value}" if title else value
            if entry and entry not in parts:
                parts.append(entry)

    # 3. blocks (Block Kit 형식)
    for block in msg.get("blocks") or []:
        _extract_block_text(block, parts)

    return "\n".join(parts)


def _extract_block_text(block: dict, parts: list[str]) -> None:
    """Block Kit 블록에서 텍스트를 재귀적으로 추출."""
    btype = block.get("type", "")

    # section / header 블록
    if btype in ("section", "header"):
        t = block.get("text", {})
        val = t.get("text", "").strip() if isinstance(t, dict) else ""
        if val and val not in parts:
            parts.append(val)
        for field in block.get("fields") or []:
            fval = field.get("text", "").strip() if isinstance(field, dict) else ""
            if fval and fval not in parts:
                parts.append(fval)

    # rich_text 블록
    elif btype == "rich_text":
        for elem in block.get("elements") or []:
            _extract_rich_text_element(elem, parts)

    # context 블록
    elif btype == "context":
        for elem in block.get("elements") or []:
            val = elem.get("text", "").strip() if isinstance(elem, dict) else ""
            if val and val not in parts:
                parts.append(val)


def _extract_rich_text_element(elem: dict, parts: list[str]) -> None:
    """rich_text 내부 element에서 텍스트 추출."""
    etype = elem.get("type", "")

    if etype in ("rich_text_section", "rich_text_preformatted", "rich_text_quote"):
        texts = []
        for sub in elem.get("elements") or []:
            t = sub.get("text", "")
            if t:
                texts.append(t)
        combined = "".join(texts).strip()
        if combined and combined not in parts:
            parts.append(combined)

    elif etype == "rich_text_list":
        for item in elem.get("elements") or []:
            _extract_rich_text_element(item, parts)


def _clean_mention(text: str) -> str:
    """Slack 멘션 태그 (<@U...>) 제거"""
    return _MENTION_RE.sub("", text).strip()


def _fetch_thread_context(
    slack_client, channel_id: str, thread_ts: str, current_ts: str
) -> str:
    """스레드의 이전 메시지들을 가져와서 컨텍스트 문자열로 반환."""
    try:
        result = slack_client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=50,
        )
        thread_msgs = result.get("messages", [])

        parts = []
        for msg in thread_msgs:
            if msg.get("ts") == current_ts:
                continue
            user_id = msg.get("user", "unknown")
            text = _extract_full_text(msg)
            if text:
                parts.append(f"<@{user_id}>: {text}")

        return "\n".join(parts)
    except Exception as e:
        logger.warning("스레드 조회 실패: %s", e)
        return ""


# ──────────────────────────────────────────────
# 채널 프로액티브 리스너 — 사전 필터 / 쿨다운 / 스크리닝
# ──────────────────────────────────────────────

# 자동 응답을 건너뛸 메시지 subtype 목록
_SKIP_SUBTYPES = frozenset({
    "bot_message", "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive",
    "channel_unarchive", "group_join", "group_leave",
    "pinned_item", "unpinned_item", "file_share",
    "me_message", "thread_broadcast",
})


def _should_skip_channel_message(event: dict, bot_user_id: str | None) -> bool:
    """채널 메시지에 대해 LLM 스크리닝 없이 빠르게 건너뛸지 판단."""
    # 기능 비활성화
    if not config.SLACK_CHANNEL_LISTENER_ENABLED:
        return True

    # 봇 메시지
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return True

    # 시스템/특수 메시지
    if event.get("subtype") in _SKIP_SUBTYPES:
        return True

    # 스레드 답글 (진행 중인 대화에 끼어들지 않음)
    if event.get("thread_ts"):
        return True

    # 자기 자신의 메시지
    if bot_user_id and event.get("user") == bot_user_id:
        return True

    # 텍스트가 없거나 너무 짧음 (attachments/blocks 포함하여 판단)
    text = _extract_full_text(event)
    if len(text) < config.SLACK_CHANNEL_MIN_MESSAGE_LENGTH:
        return True

    # @멘션은 on_mention 핸들러가 처리하므로 중복 방지
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return True

    return False


def _check_channel_cooldown(channel_id: str) -> bool:
    """채널 쿨다운 확인. True면 응답 가능, False면 쿨다운 중."""
    with _channel_last_reply_lock:
        last = _channel_last_reply.get(channel_id, 0)
        return (time.time() - last) >= config.SLACK_CHANNEL_COOLDOWN


def _record_channel_reply(channel_id: str) -> None:
    """채널에 자동 응답한 시각을 기록."""
    with _channel_last_reply_lock:
        _channel_last_reply[channel_id] = time.time()


_VALID_EMOJIS = frozenset({
    "eyes", "bulb", "thinking_face", "rocket", "dart",
    "star", "fire", "raised_hands", "memo", "white_check_mark",
})


def _screen_message(llm_client, text: str) -> tuple[bool, str]:
    """LLM으로 메시지가 봇 응답에 적합한지 판별.

    Returns:
        (should_respond, emoji_name) — 응답 여부와 적합한 이모지.
        NO일 경우 emoji_name은 빈 문자열.
    """
    messages = [
        {"role": "system", "content": config.SLACK_SCREENING_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        result = llm.screening_chat(llm_client, messages)
        parts = result.strip().split()
        if not parts or parts[0].upper() != "YES":
            return False, ""
        emoji = parts[1].lower() if len(parts) >= 2 else "eyes"
        if emoji not in _VALID_EMOJIS:
            emoji = "eyes"
        return True, emoji
    except Exception as e:
        logger.warning("스크리닝 LLM 호출 실패: %s", e)
        return False, ""


# ──────────────────────────────────────────────
# 이벤트 핸들러
# ──────────────────────────────────────────────


def _handle_message(
    body: dict,
    say,
    slack_client,
    engine: ReactEngine,
    system_prompt: str,
):
    """DM 또는 app_mention 메시지 처리"""
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    user_text = _clean_mention(_extract_full_text(event))

    if not user_text:
        return

    # 봇 자신의 메시지 무시
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # 스레드 컨텍스트 조회 (스레드 내 답글인 경우)
    event_ts = event.get("ts")
    event_thread_ts = event.get("thread_ts")
    if event_thread_ts and event_thread_ts != event_ts:
        thread_context = _fetch_thread_context(
            slack_client, channel_id, event_thread_ts, event_ts
        )
        if thread_context:
            user_text = (
                f"[아래는 이 스레드의 이전 대화입니다]\n{thread_context}\n\n"
                f"[현재 메시지]\n{user_text}"
            )

    # ⏳ 처리 중 리액션 추가
    msg_ts = event.get("ts")
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="hourglass_flowing_sand",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 세션에서 메시지 목록 가져오기
    messages = _get_session(channel_id, system_prompt)
    messages.append({"role": "user", "content": user_text})

    # ReactEngine으로 응답 생성 (비스트리밍)
    try:
        reply = engine.run(messages)
        messages.append({"role": "assistant", "content": reply})
        _trim_session(messages)
    except Exception as e:
        logger.error("ReactEngine 오류: %s", e, exc_info=True)
        reply = f"처리 중 오류가 발생했습니다: {e}"

    # ⏳ 리액션 제거
    try:
        slack_client.reactions_remove(
            channel=channel_id,
            name="hourglass_flowing_sand",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 응답 전송 (길면 분할)
    for chunk in _split_message(reply):
        say(text=chunk, thread_ts=thread_ts)


def _handle_channel_message(
    body: dict,
    say,
    slack_client,
    llm_client,
    engine: ReactEngine,
    system_prompt: str,
    bot_user_id: str | None,
):
    """채널 메시지 프로액티브 처리 — 스크리닝 후 스레드로 응답"""
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    msg_ts = event.get("ts", "")
    user_text = _extract_full_text(event)

    # 1단계: 사전 필터 (LLM 호출 없이)
    if _should_skip_channel_message(event, bot_user_id):
        return

    # 2단계: 쿨다운 확인
    if not _check_channel_cooldown(channel_id):
        logger.debug("채널 %s 쿨다운 중 — 스킵", channel_id)
        return

    # 3단계: LLM 스크리닝
    clean_text = _clean_mention(user_text)
    should_respond, emoji = _screen_message(llm_client, clean_text)
    if not should_respond:
        logger.debug("스크리닝 통과 실패: %s", clean_text[:80])
        return

    logger.info("채널 %s에서 프로액티브 응답 시작 (:%s:): %s", channel_id, emoji, clean_text[:80])

    # 4단계: 스크리닝 통과 — 의미에 맞는 이모지 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name=emoji,
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 5단계: ⏳ 리액션 추가
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="hourglass_flowing_sand",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 5단계: ReactEngine으로 응답 생성 (일회성 세션)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": clean_text},
    ]

    try:
        reply = engine.run(messages)
    except Exception as e:
        logger.error("프로액티브 응답 ReactEngine 오류: %s", e, exc_info=True)
        reply = None

    # 6단계: ⏳ 리액션 제거
    try:
        slack_client.reactions_remove(
            channel=channel_id,
            name="hourglass_flowing_sand",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 7단계: 스레드로 응답 전송
    if reply:
        _record_channel_reply(channel_id)
        for chunk in _split_message(reply):
            say(text=chunk, thread_ts=msg_ts)


def _handle_incident_message(
    body: dict,
    say,
    slack_client,
):
    """인시던트 채널의 봇 메시지 분석 — Claude Opus deep think 직접 호출.

    ReactEngine을 거치지 않고 Claude CLI를 직접 실행합니다.
    별도 스레드에서 실행되므로 Slack 이벤트 루프를 블로킹하지 않습니다.
    """
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    msg_ts = event.get("ts", "")

    # 인시던트 메시지 전체 텍스트 추출 (attachments, blocks 포함)
    incident_text = _extract_full_text(event)
    if not incident_text or len(incident_text) < 10:
        logger.debug("인시던트 메시지 텍스트 부족, 건너뜀")
        return

    logger.info(
        "인시던트 감지: channel=%s text=%s",
        channel_id, incident_text[:200],
    )

    # 1단계: 관련 프로젝트 식별
    project_name, project_path = resolve_project(incident_text)
    if project_name:
        logger.info("인시던트 관련 프로젝트: %s (%s)", project_name, project_path)
    else:
        logger.info("인시던트 관련 프로젝트를 특정하지 못함, 워크스페이스 루트 사용")

    # 2단계: 분석 시작 알림 (스레드에 메시지)
    project_info = f"`{project_name}`" if project_name else "전체 워크스페이스"
    try:
        say(
            text=(
                f":mag: *인시던트 분석 시작*\n"
                f"대상 프로젝트: {project_info}\n"
                f"Claude Opus (deep think) 분석 중... "
                f"최대 {config.INCIDENT_CLAUDE_TIMEOUT // 60}분 소요될 수 있습니다."
            ),
            thread_ts=msg_ts,
        )
    except Exception as e:
        logger.warning("분석 시작 알림 전송 실패: %s", e)

    # 3단계: 리액션 추가
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="mag",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 4단계: Claude Opus로 분석 실행
    try:
        analysis = analyze_incident(incident_text, project_path)
    except Exception as e:
        logger.error("인시던트 분석 오류: %s", e, exc_info=True)
        analysis = f"인시던트 분석 중 오류가 발생했습니다: {e}"

    # 5단계: 분석 완료 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="white_check_mark",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 6단계: 분석 결과를 스레드에 전송
    header = ":rotating_light: *인시던트 분석 결과*"
    if project_name:
        header += f" ({project_name})"
    header += "\n\n"

    full_response = header + analysis
    for chunk in _split_message(full_response):
        try:
            say(text=chunk, thread_ts=msg_ts)
        except Exception as e:
            logger.error("분석 결과 전송 실패: %s", e)


# ──────────────────────────────────────────────
# 엔트리포인트
# ──────────────────────────────────────────────


def main():
    # 토큰 검증
    if not config.SLACK_BOT_TOKEN or not config.SLACK_APP_TOKEN:
        print(
            "Slack 토큰이 설정되지 않았습니다.\n"
            "config.py에서 아래 값을 설정하세요:\n\n"
            "  SLACK_BOT_TOKEN = \"xoxb-...\"  # OAuth & Permissions에서 발급\n"
            "  SLACK_APP_TOKEN = \"xapp-...\"  # Basic Information > App-Level Tokens\n\n"
            "Slack 앱 설정 방법은 slack_app.py 상단 docstring을 참고하세요."
        )
        sys.exit(1)

    # LLM 클라이언트 연결
    llm_client = llm.create_client()
    try:
        llm.check_connection(llm_client)
    except Exception as e:
        logger.error("LLM 연결 실패: %s", e)
        if config.LLM_PROVIDER == "ollama":
            print("ollama가 실행 중인지 확인하세요: ollama serve")
        else:
            print("API 키를 확인하세요: config.py 또는 ANTHROPIC_API_KEY 환경변수")
        sys.exit(1)

    # 임베딩용 Ollama 클라이언트 (메모리 시스템)
    embed_client = None
    try:
        embed_client = llm.create_embed_client()
        embed_client.list()
    except Exception:
        logger.warning("Ollama 연결 실패 — 벡터 검색 비활성화 (BM25 전용)")
        embed_client = None

    # 메모리 시스템 초기화
    memory_manager = MemoryManager(client=embed_client)
    mem_info = memory_manager.startup()
    logger.info(
        "메모리: SOUL %d자, MEMORY %d자, 인덱스 %d청크",
        mem_info["soul_chars"],
        mem_info["memory_chars"],
        mem_info["index_chunks"],
    )

    # 도구 + MCP 초기화
    local_tools = _build_local_tools(memory_manager)

    mcp_manager = McpManager()
    mcp_tools = []
    if config.MCP_SERVERS:
        logger.info("MCP 서버 연결 중...")
        mcp_tools = mcp_manager.connect_all()

    engine = ReactEngine(llm_client, local_tools, mcp_tools=mcp_tools)
    system_prompt = _build_system_prompt(memory_manager)

    logger.info(
        "모델: %s (%s) / 도구: %d개 로컬 + %d개 MCP",
        llm.get_model_name(),
        config.LLM_PROVIDER,
        len(local_tools),
        len(mcp_tools),
    )
    if config.SLACK_CHANNEL_LISTENER_ENABLED:
        logger.info(
            "채널 프로액티브 리스너: 활성 (쿨다운 %ds, 최소길이 %d자)",
            config.SLACK_CHANNEL_COOLDOWN,
            config.SLACK_CHANNEL_MIN_MESSAGE_LENGTH,
        )
    if config.INCIDENT_ANALYSIS_ENABLED and config.INCIDENT_CHANNEL_IDS:
        logger.info(
            "인시던트 분석: 활성 (채널 %d개, 타임아웃 %ds)",
            len(config.INCIDENT_CHANNEL_IDS),
            config.INCIDENT_CLAUDE_TIMEOUT,
        )

    # Slack 앱 생성
    app = App(token=config.SLACK_BOT_TOKEN)

    # 봇 자신의 user ID 조회 (자기 메시지 필터링용)
    bot_user_id = None
    try:
        auth_result = app.client.auth_test()
        bot_user_id = auth_result.get("user_id")
        logger.info("봇 User ID: %s", bot_user_id)
    except Exception as e:
        logger.warning("봇 User ID 조회 실패: %s", e)

    @app.event("message")
    def on_message(body, say, client):
        """DM 또는 채널 메시지 처리"""
        event = body.get("event", {})
        channel_type = event.get("channel_type")
        user = event.get("user", "unknown")
        full_text = _extract_full_text(event)
        channel_id = event.get("channel", "")
        subtype = event.get("subtype", "")

        logger.info(
            "[수신] type=%s channel=%s user=%s subtype=%s text=%s",
            channel_type, channel_id, user, subtype, full_text[:200],
        )

        # ★ 인시던트 채널 봇 메시지 → Claude Opus 분석 (최우선 처리)
        if is_incident_channel(channel_id) and (
            event.get("bot_id") or subtype == "bot_message"
        ):
            # 스레드 답글은 무시 (분석 결과에 재반응 방지)
            if event.get("thread_ts"):
                return
            threading.Thread(
                target=_handle_incident_message,
                args=(body, say, client),
                daemon=True,
            ).start()
            return

        if channel_type == "im":
            # DM: 기존 동작 그대로 (항상 응답)
            _handle_message(body, say, client, engine, system_prompt)
        elif channel_type == "channel":
            # 공개 채널: 프로액티브 리스너 (스크리닝 후 스레드 응답)
            _handle_channel_message(
                body, say, client, llm_client,
                engine, system_prompt, bot_user_id,
            )

    @app.event("app_mention")
    def on_mention(body, say, client):
        """채널에서 @멘션 처리 — 항상 응답"""
        _handle_message(body, say, client, engine, system_prompt)

    # Socket Mode 시작
    logger.info("Agenstin Slack 봇 시작 (Socket Mode)")
    handler = SocketModeHandler(app, config.SLACK_APP_TOKEN)

    try:
        handler.start()
    except KeyboardInterrupt:
        logger.info("종료 신호 수신 (Ctrl+C)")
    finally:
        logger.info("리소스 정리 중...")
        handler.close()
        memory_manager.close()
        mcp_manager.disconnect_all()
        logger.info("Agenstin Slack 봇 종료 완료")


if __name__ == "__main__":
    main()
