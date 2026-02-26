"""LLM 클라이언트 — Ollama / Anthropic 프로바이더 추상화

config.LLM_PROVIDER 에 따라 적절한 백엔드를 사용합니다.
임베딩은 항상 Ollama를 사용합니다 (Anthropic은 임베딩 미지원).
"""

import json
import logging
from collections.abc import Generator
from typing import Any

import config

logger = logging.getLogger("agenstin.llm")


# ──────────────────────────────────────────────
# 클라이언트 생성
# ──────────────────────────────────────────────


def create_client() -> Any:
    """설정에 따라 LLM 클라이언트 생성"""
    if config.LLM_PROVIDER == "anthropic":
        import anthropic

        kwargs = {}
        if config.ANTHROPIC_API_KEY:
            kwargs["api_key"] = config.ANTHROPIC_API_KEY
        return anthropic.Anthropic(**kwargs)

    import ollama
    return ollama.Client(host=config.OLLAMA_HOST)


def create_embed_client() -> Any:
    """임베딩용 Ollama 클라이언트 생성 (LLM 프로바이더와 무관)"""
    import ollama
    return ollama.Client(host=config.OLLAMA_HOST)


def get_model_name() -> str:
    """현재 설정된 모델 이름 반환"""
    if config.LLM_PROVIDER == "anthropic":
        return config.ANTHROPIC_MODEL
    return config.OLLAMA_MODEL


def get_tool_definitions(tools: list) -> list[dict]:
    """현재 프로바이더에 맞는 도구 정의 목록 반환"""
    if config.LLM_PROVIDER == "anthropic":
        return [t.to_anthropic_tool() for t in tools]
    return [t.to_ollama_tool() for t in tools]


def check_connection(client: Any) -> None:
    """LLM 연결/인증 확인. 실패 시 예외 발생."""
    if config.LLM_PROVIDER == "anthropic":
        if not getattr(client, "api_key", None):
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                "config.py 또는 환경변수로 설정하세요."
            )
    else:
        client.list()


# ──────────────────────────────────────────────
# 통합 채팅 인터페이스
# ──────────────────────────────────────────────


def chat_stream(
    client: Any,
    messages: list[dict],
    tools: list[dict] | None = None,
    think: bool = False,
) -> Generator[tuple[str, Any], None, None]:
    """통합 스트리밍 채팅. (event_type, data) 튜플을 yield.

    event_type:
        "content"   — data: str (텍스트 청크)
        "thinking"  — data: str (추론 텍스트, Ollama thinking 전용)
        "tool_call" — data: dict {"id": str, "name": str, "arguments": dict}
    """
    if config.LLM_PROVIDER == "anthropic":
        yield from _stream_anthropic(client, messages, tools)
    else:
        yield from _stream_ollama(client, messages, tools, think)


def simple_chat(client: Any, messages: list[dict]) -> str:
    """도구 없이 단순 대화 — 텍스트 응답만 반환"""
    if config.LLM_PROVIDER == "anthropic":
        return _simple_chat_anthropic(client, messages)
    return _simple_chat_ollama(client, messages)


def screening_chat(client: Any, messages: list[dict]) -> str:
    """스크리닝용 경량 LLM 호출 — 짧은 응답, 빠른 실행"""
    if config.LLM_PROVIDER == "anthropic":
        return _screening_chat_anthropic(client, messages)
    return _screening_chat_ollama(client, messages)


# ──────────────────────────────────────────────
# 메시지 구성 헬퍼
# ──────────────────────────────────────────────


def build_assistant_message(
    content: str,
    tool_calls: list[dict],
    thinking: str = "",
) -> dict:
    """프로바이더에 맞는 assistant 메시지 구성"""
    if config.LLM_PROVIDER == "anthropic":
        return _build_assistant_msg_anthropic(content, tool_calls)
    return _build_assistant_msg_ollama(content, tool_calls, thinking)


def build_tool_result_messages(
    tool_calls: list[dict],
    results: list[str],
) -> list[dict]:
    """프로바이더에 맞는 tool result 메시지 구성"""
    if config.LLM_PROVIDER == "anthropic":
        return _build_tool_results_anthropic(tool_calls, results)
    return _build_tool_results_ollama(results)


# ══════════════════════════════════════════════
# Ollama 구현
# ══════════════════════════════════════════════


def _stream_ollama(client, messages, tools=None, think=False):
    kwargs = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "options": {
            "temperature": config.TEMPERATURE,
            "num_predict": config.MAX_TOKENS,
        },
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    if think:
        kwargs["think"] = True

    for chunk in client.chat(**kwargs):
        if chunk.message.tool_calls:
            for tc in chunk.message.tool_calls:
                yield ("tool_call", {
                    "id": "",
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })

        think_text = getattr(chunk.message, "thinking", None) or ""
        if think_text:
            yield ("thinking", think_text)

        content = chunk.message.content or ""
        if content:
            yield ("content", content)


def _simple_chat_ollama(client, messages):
    response = client.chat(
        model=config.OLLAMA_MODEL,
        messages=messages,
        options={
            "temperature": config.TEMPERATURE,
            "num_predict": config.MAX_TOKENS,
        },
    )
    return response.message.content or ""


def _screening_chat_ollama(client, messages):
    model = config.SLACK_SCREENING_MODEL or config.OLLAMA_MODEL
    response = client.chat(
        model=model,
        messages=messages,
        options={
            "temperature": 0.1,
            "num_predict": config.SLACK_SCREENING_MAX_TOKENS,
        },
    )
    return response.message.content or ""


def _build_assistant_msg_ollama(content, tool_calls, thinking=""):
    msg: dict = {"role": "assistant", "content": content}
    if thinking:
        msg["thinking"] = thinking
    msg["tool_calls"] = [
        {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
        for tc in tool_calls
    ]
    return msg


def _build_tool_results_ollama(results):
    return [{"role": "tool", "content": r} for r in results]


# ══════════════════════════════════════════════
# Anthropic 구현
# ══════════════════════════════════════════════


def _extract_system_and_messages(
    messages: list[dict],
) -> tuple[str, list[dict]]:
    """메시지 리스트에서 system 메시지를 분리하고 Anthropic 형식으로 변환.

    Anthropic API 제약:
      - system은 별도 파라미터
      - 첫 메시지는 반드시 user
      - 같은 role의 연속 메시지 불가
    """
    system_parts: list[str] = []
    api_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
        elif role in ("user", "assistant"):
            api_messages.append({"role": role, "content": content})
        # "tool" role → Ollama 전용이므로 무시 (Anthropic은 build_tool_result_messages 사용)

    # 첫 메시지가 user가 아니면 빈 user 메시지 삽입
    if api_messages and api_messages[0]["role"] != "user":
        api_messages.insert(0, {"role": "user", "content": "(대화 시작)"})

    # 같은 role 연속 → 병합
    merged: list[dict] = []
    for msg in api_messages:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            curr = msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n\n" + curr
            else:
                # list content (tool_result 등) 병합
                if isinstance(prev, str):
                    merged[-1]["content"] = [{"type": "text", "text": prev}]
                if isinstance(curr, str):
                    curr = [{"type": "text", "text": curr}]
                merged[-1]["content"].extend(curr)
        else:
            merged.append(msg)

    return "\n\n".join(system_parts), merged


def _stream_anthropic(client, messages, tools=None):
    system, api_messages = _extract_system_and_messages(messages)

    kwargs: dict = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": config.MAX_TOKENS,
        "messages": api_messages,
        "stream": True,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if config.TEMPERATURE is not None:
        kwargs["temperature"] = config.TEMPERATURE

    stream = client.messages.create(**kwargs)

    current_tool_id: str | None = None
    current_tool_name: str | None = None
    tool_input_json = ""

    for event in stream:
        if event.type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                current_tool_id = block.id
                current_tool_name = block.name
                tool_input_json = ""

        elif event.type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                yield ("content", delta.text)
            elif delta.type == "input_json_delta":
                tool_input_json += delta.partial_json

        elif event.type == "content_block_stop":
            if current_tool_id:
                args = json.loads(tool_input_json) if tool_input_json else {}
                yield ("tool_call", {
                    "id": current_tool_id,
                    "name": current_tool_name,
                    "arguments": args,
                })
                current_tool_id = None
                current_tool_name = None
                tool_input_json = ""


def _simple_chat_anthropic(client, messages):
    system, api_messages = _extract_system_and_messages(messages)

    kwargs: dict = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": config.MAX_TOKENS,
        "messages": api_messages,
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)

    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def _screening_chat_anthropic(client, messages):
    system, api_messages = _extract_system_and_messages(messages)

    kwargs: dict = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": config.SLACK_SCREENING_MAX_TOKENS,
        "messages": api_messages,
        "temperature": 0.1,
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)

    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def _build_assistant_msg_anthropic(content, tool_calls):
    """Anthropic 형식의 assistant 메시지 구성.

    content block 목록: TextBlock + ToolUseBlock
    """
    blocks: list[dict] = []
    if content.strip():
        blocks.append({"type": "text", "text": content})
    for tc in tool_calls:
        blocks.append({
            "type": "tool_use",
            "id": tc["id"],
            "name": tc["name"],
            "input": tc["arguments"],
        })
    return {"role": "assistant", "content": blocks}


def _build_tool_results_anthropic(tool_calls, results):
    """Anthropic 형식의 tool result 메시지 구성.

    모든 tool result를 하나의 user 메시지에 담습니다.
    """
    tool_results: list[dict] = []
    for tc, result in zip(tool_calls, results):
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tc["id"],
            "content": result,
        })
    return [{"role": "user", "content": tool_results}]
