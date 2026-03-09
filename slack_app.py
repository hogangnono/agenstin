"""Agenstin — Slack 봇 인터페이스

Socket Mode로 동작하는 Slack 봇.
Sonnet 라우터로 스크리닝/간단한 응답, Claude Code CLI로 복잡한 작업을 처리합니다.

사전 준비:
  1. https://api.slack.com/apps 에서 앱 생성
  2. Socket Mode 활성화 → App-Level Token 발급 (connections:write)
  3. OAuth & Permissions에서 Bot Token Scopes 추가:
     chat:write, reactions:write, reactions:read,
     app_mentions:read, im:history, im:read, im:write,
     channels:history
  4. Event Subscriptions에서 구독 이벤트 추가:
     message.im, app_mention, message.channels
  5. .env에 SLACK_BOT_TOKEN, SLACK_APP_TOKEN 설정
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
from core import claude_cli
from core.incident import (
    analyze as analyze_incident,
    git_pull,
    is_incident_channel,
    resolve_project,
)
from core.router import Router
from memory.manager import MemoryManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("agenstin.slack")

# ──────────────────────────────────────────────
# 채널/DM별 세션 관리
# ──────────────────────────────────────────────

_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

_channel_last_reply: dict[str, float] = {}
_channel_last_reply_lock = threading.Lock()


def _get_session(channel_id: str) -> list[dict]:
    """채널/DM별 메시지 목록을 반환. 만료 시 초기화."""
    with _sessions_lock:
        now = time.time()
        session = _sessions.get(channel_id)

        if (
            session is None
            or (now - session["last_active"]) > config.SLACK_SESSION_TIMEOUT
        ):
            _sessions[channel_id] = {"messages": [], "last_active": now}
            return []

        session["last_active"] = now
        return session["messages"]


def _append_to_session(channel_id: str, role: str, content: str) -> None:
    """세션에 메시지 추가 + 트리밍."""
    with _sessions_lock:
        session = _sessions.get(channel_id)
        if session is None:
            session = {"messages": [], "last_active": time.time()}
            _sessions[channel_id] = session

        session["messages"].append({"role": role, "content": content})
        session["last_active"] = time.time()

        # 최대 턴 수 제한
        max_msgs = config.SLACK_MAX_TURNS_PER_SESSION * 2
        if len(session["messages"]) > max_msgs:
            session["messages"] = session["messages"][-max_msgs:]


# ──────────────────────────────────────────────
# 메시지 분할 (Slack 4000자 제한)
# ──────────────────────────────────────────────


def _split_message(text: str) -> list[str]:
    """긴 메시지를 Slack 제한에 맞게 분할."""
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
    segment = text[:max_len]

    code_end = segment.rfind("```\n")
    if code_end > max_len // 2:
        return code_end + 4

    double_nl = segment.rfind("\n\n")
    if double_nl > max_len // 2:
        return double_nl + 2

    single_nl = segment.rfind("\n")
    if single_nl > max_len // 3:
        return single_nl + 1

    return max_len


# ──────────────────────────────────────────────
# 메시지 전처리
# ──────────────────────────────────────────────

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def _extract_full_text(msg: dict) -> str:
    """Slack 메시지에서 text + attachments + blocks 내용을 모두 추출."""
    parts: list[str] = []

    text = msg.get("text", "").strip()
    if text:
        parts.append(text)

    for att in msg.get("attachments") or []:
        for field_name in ("pretext", "text", "fallback"):
            val = att.get(field_name, "").strip()
            if val and val not in parts:
                parts.append(val)
        for field in att.get("fields") or []:
            title = field.get("title", "").strip()
            value = field.get("value", "").strip()
            entry = f"{title}: {value}" if title else value
            if entry and entry not in parts:
                parts.append(entry)

    for block in msg.get("blocks") or []:
        _extract_block_text(block, parts)

    return "\n".join(parts)


def _extract_block_text(block: dict, parts: list[str]) -> None:
    btype = block.get("type", "")

    if btype in ("section", "header"):
        t = block.get("text", {})
        val = t.get("text", "").strip() if isinstance(t, dict) else ""
        if val and val not in parts:
            parts.append(val)
        for field in block.get("fields") or []:
            fval = field.get("text", "").strip() if isinstance(field, dict) else ""
            if fval and fval not in parts:
                parts.append(fval)

    elif btype == "rich_text":
        for elem in block.get("elements") or []:
            _extract_rich_text_element(elem, parts)

    elif btype == "context":
        for elem in block.get("elements") or []:
            val = elem.get("text", "").strip() if isinstance(elem, dict) else ""
            if val and val not in parts:
                parts.append(val)


def _extract_rich_text_element(elem: dict, parts: list[str]) -> None:
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
    return _MENTION_RE.sub("", text).strip()


def _fetch_thread_context(
    slack_client, channel_id: str, thread_ts: str, current_ts: str
) -> str:
    """스레드의 이전 메시지들을 컨텍스트 문자열로 반환."""
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
# 채널 프로액티브 리스너 — 사전 필터 / 쿨다운
# ──────────────────────────────────────────────

_SKIP_SUBTYPES = frozenset({
    "bot_message", "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive",
    "channel_unarchive", "group_join", "group_leave",
    "pinned_item", "unpinned_item", "file_share",
    "me_message", "thread_broadcast",
})


def _should_skip_channel_message(event: dict, bot_user_id: str | None) -> bool:
    if not config.SLACK_CHANNEL_LISTENER_ENABLED:
        return True
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return True
    if event.get("subtype") in _SKIP_SUBTYPES:
        return True
    if event.get("thread_ts"):
        return True
    if bot_user_id and event.get("user") == bot_user_id:
        return True

    text = _extract_full_text(event)
    if len(text) < config.SLACK_CHANNEL_MIN_MESSAGE_LENGTH:
        return True
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return True

    return False


def _check_channel_cooldown(channel_id: str) -> bool:
    with _channel_last_reply_lock:
        last = _channel_last_reply.get(channel_id, 0)
        return (time.time() - last) >= config.SLACK_CHANNEL_COOLDOWN


def _record_channel_reply(channel_id: str) -> None:
    with _channel_last_reply_lock:
        _channel_last_reply[channel_id] = time.time()


# ──────────────────────────────────────────────
# 응답 생성 헬퍼
# ──────────────────────────────────────────────


def _build_system_prompt(memory_manager: MemoryManager) -> str:
    """시스템 프롬프트: 기본 + SOUL.md + MEMORY.md 발췌"""
    parts = [config.ROUTER_SYSTEM_PROMPT]

    soul = memory_manager.get_soul()
    if soul:
        parts.append(f"## 에이전트 성격\n{soul}")

    excerpt = memory_manager.get_memory_excerpt()
    if excerpt:
        parts.append(f"## 기억된 정보\n{excerpt}")

    return "\n\n".join(parts)


def _build_claude_prompt(
    user_text: str,
    conversation: list[dict] | None = None,
    memory_context: str = "",
) -> str:
    """Claude CLI에 전달할 프롬프트를 구성."""
    parts = []

    if memory_context:
        parts.append(f"<memory>\n{memory_context}\n</memory>")

    if conversation:
        history_lines = []
        for m in conversation[-20:]:  # 최근 20개만
            history_lines.append(f"{m['role']}: {m['content']}")
        if history_lines:
            parts.append(
                "<conversation_history>\n"
                + "\n".join(history_lines)
                + "\n</conversation_history>"
            )

    parts.append(user_text)
    return "\n\n".join(parts)


def _generate_response(
    router: Router,
    user_text: str,
    system_prompt: str,
    conversation: list[dict],
    memory_context: str = "",
) -> str:
    """Sonnet 라우터로 응답 생성. 필요 시 Claude CLI에 위임."""
    # Sonnet으로 먼저 시도
    response, delegated = router.respond(
        user_text,
        system=system_prompt,
        conversation=conversation[-20:] if conversation else None,
    )

    if not delegated:
        return response

    # Claude CLI에 위임
    logger.info("Claude CLI에 위임: %s", user_text[:80])
    prompt = _build_claude_prompt(user_text, conversation, memory_context)
    return claude_cli.run(prompt)


# ──────────────────────────────────────────────
# 이벤트 핸들러
# ──────────────────────────────────────────────


def _handle_message(
    body: dict,
    say,
    slack_client,
    router: Router,
    system_prompt: str,
    memory_context: str,
):
    """DM 또는 app_mention 메시지 처리"""
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    user_text = _clean_mention(_extract_full_text(event))

    if not user_text:
        return
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # 스레드 컨텍스트 조회
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

    # ⏳ 처리 중 리액션
    msg_ts = event.get("ts")
    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="hourglass_flowing_sand",
            timestamp=msg_ts,
        )
    except Exception:
        pass

    # 세션 컨텍스트
    conversation = _get_session(channel_id)
    _append_to_session(channel_id, "user", user_text)

    # 응답 생성
    try:
        reply = _generate_response(
            router, user_text, system_prompt, conversation, memory_context
        )
        _append_to_session(channel_id, "assistant", reply)
    except Exception as e:
        logger.error("응답 생성 오류: %s", e, exc_info=True)
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

    # 응답 전송
    for chunk in _split_message(reply):
        say(text=chunk, thread_ts=thread_ts)


def _handle_channel_message(
    body: dict,
    say,
    slack_client,
    router: Router,
    system_prompt: str,
    memory_context: str,
    bot_user_id: str | None,
):
    """채널 메시지 프로액티브 처리 — 스크리닝 후 스레드로 응답"""
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    msg_ts = event.get("ts", "")

    if _should_skip_channel_message(event, bot_user_id):
        return
    if not _check_channel_cooldown(channel_id):
        logger.debug("채널 %s 쿨다운 중", channel_id)
        return

    clean_text = _clean_mention(_extract_full_text(event))

    # Sonnet 스크리닝
    emoji = router.screen(clean_text)
    if not emoji:
        logger.debug("스크리닝 통과 실패: %s", clean_text[:80])
        return

    logger.info("채널 %s 프로액티브 응답 (:%s:): %s", channel_id, emoji, clean_text[:80])

    # 이모지 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id, name=emoji, timestamp=msg_ts,
        )
    except Exception:
        pass

    # ⏳ 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id, name="hourglass_flowing_sand", timestamp=msg_ts,
        )
    except Exception:
        pass

    # 응답 생성 (일회성, 세션 없음)
    try:
        reply = _generate_response(
            router, clean_text, system_prompt, [], memory_context
        )
    except Exception as e:
        logger.error("프로액티브 응답 오류: %s", e, exc_info=True)
        reply = None

    # ⏳ 리액션 제거
    try:
        slack_client.reactions_remove(
            channel=channel_id, name="hourglass_flowing_sand", timestamp=msg_ts,
        )
    except Exception:
        pass

    if reply:
        _record_channel_reply(channel_id)
        for chunk in _split_message(reply):
            say(text=chunk, thread_ts=msg_ts)


def _handle_incident_message(body: dict, say, slack_client):
    """인시던트 채널의 봇 메시지 분석 — Claude Code CLI 기반"""
    event = body.get("event", {})
    channel_id = event.get("channel", "")
    msg_ts = event.get("ts", "")

    incident_text = _extract_full_text(event)
    if not incident_text or len(incident_text) < 10:
        return

    logger.info("인시던트 감지: channel=%s text=%s", channel_id, incident_text[:200])

    # 프로젝트 식별 + git pull
    project_name, project_path = resolve_project(incident_text)
    cwd = project_path or config.INCIDENT_WORKSPACE
    if cwd:
        git_pull(cwd)

    # 분석 시작 알림
    project_info = f"`{project_name}`" if project_name else "전체 워크스페이스"
    try:
        say(
            text=(
                f":mag: *인시던트 분석 시작*\n"
                f"대상 프로젝트: {project_info}\n"
                f"Claude Opus로 코드베이스를 분석합니다..."
            ),
            thread_ts=msg_ts,
        )
    except Exception as e:
        logger.warning("분석 시작 알림 실패: %s", e)

    # 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id, name="mag", timestamp=msg_ts,
        )
    except Exception:
        pass

    # Claude CLI로 분석
    try:
        analysis = analyze_incident(incident_text, project_path)
    except Exception as e:
        logger.error("인시던트 분석 오류: %s", e, exc_info=True)
        analysis = f"인시던트 분석 중 오류가 발생했습니다: {e}"

    # 완료 리액션
    try:
        slack_client.reactions_add(
            channel=channel_id, name="white_check_mark", timestamp=msg_ts,
        )
    except Exception:
        pass

    # 결과 전송
    header = ":rotating_light: *인시던트 분석 결과*"
    if project_name:
        header += f" ({project_name})"
    header += "\n\n"

    for chunk in _split_message(header + analysis):
        try:
            say(text=chunk, thread_ts=msg_ts)
        except Exception as e:
            logger.error("분석 결과 전송 실패: %s", e)


# ──────────────────────────────────────────────
# 엔트리포인트
# ──────────────────────────────────────────────


def main():
    if not config.SLACK_BOT_TOKEN or not config.SLACK_APP_TOKEN:
        print(
            "Slack 토큰이 설정되지 않았습니다.\n"
            ".env 파일에서 SLACK_BOT_TOKEN, SLACK_APP_TOKEN을 설정하세요.\n"
            "설정 방법은 이 파일 상단 docstring을 참고하세요."
        )
        sys.exit(1)

    # 라우터 초기화
    router = Router()
    logger.info("Sonnet 라우터 초기화: %s", config.ROUTER_MODEL)

    # 메모리 초기화
    memory_manager = MemoryManager()
    mem_info = memory_manager.startup()
    logger.info(
        "메모리: SOUL %d자, MEMORY %d자",
        mem_info["soul_chars"],
        mem_info["memory_chars"],
    )

    system_prompt = _build_system_prompt(memory_manager)
    memory_context = memory_manager.get_memory_excerpt()

    if config.SLACK_CHANNEL_LISTENER_ENABLED:
        logger.info(
            "채널 프로액티브 리스너: 활성 (쿨다운 %ds)",
            config.SLACK_CHANNEL_COOLDOWN,
        )
    if config.INCIDENT_ANALYSIS_ENABLED and config.INCIDENT_CHANNEL_IDS:
        logger.info(
            "인시던트 분석: 활성 (채널 %d개)",
            len(config.INCIDENT_CHANNEL_IDS),
        )

    # Slack 앱 생성
    app = App(token=config.SLACK_BOT_TOKEN)

    bot_user_id = None
    try:
        auth_result = app.client.auth_test()
        bot_user_id = auth_result.get("user_id")
        logger.info("봇 User ID: %s", bot_user_id)
    except Exception as e:
        logger.warning("봇 User ID 조회 실패: %s", e)

    @app.event("message")
    def on_message(body, say, client):
        event = body.get("event", {})
        channel_type = event.get("channel_type")
        channel_id = event.get("channel", "")
        subtype = event.get("subtype", "")

        logger.info(
            "[수신] type=%s channel=%s subtype=%s text=%s",
            channel_type, channel_id, subtype,
            _extract_full_text(event)[:200],
        )

        # 인시던트 채널 봇 메시지 → Claude Opus 분석
        if is_incident_channel(channel_id) and (
            event.get("bot_id") or subtype == "bot_message"
        ):
            if event.get("thread_ts"):
                return
            threading.Thread(
                target=_handle_incident_message,
                args=(body, say, client),
                daemon=True,
            ).start()
            return

        if channel_type == "im":
            _handle_message(
                body, say, client, router,
                system_prompt, memory_context,
            )
        elif channel_type == "channel":
            _handle_channel_message(
                body, say, client, router,
                system_prompt, memory_context, bot_user_id,
            )

    @app.event("app_mention")
    def on_mention(body, say, client):
        _handle_message(
            body, say, client, router,
            system_prompt, memory_context,
        )

    # Socket Mode 시작
    logger.info("Agenstin Slack 봇 시작 (Sonnet 라우터 + Claude Code CLI)")
    handler = SocketModeHandler(app, config.SLACK_APP_TOKEN)

    try:
        handler.start()
    except KeyboardInterrupt:
        logger.info("종료 신호 수신 (Ctrl+C)")
    finally:
        logger.info("Agenstin Slack 봇 종료")
        handler.close()


if __name__ == "__main__":
    main()
