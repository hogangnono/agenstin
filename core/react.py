"""ReAct 루프 엔진 — think → act → observe"""

import time
from collections.abc import Generator
from typing import Any

from rich.console import Console

import config
from core import llm
from core.mcp_prefetch import is_low_quality, run_prefetch, should_prefetch
from tools.base import Tool

console = Console()


class ReactEngine:
    """ReAct (Reasoning + Acting) 루프

    1. 사내 관련 질문이면 MCP 선조회 → 결과를 컨텍스트로 주입
    2. 사용자 메시지 + 도구 정의를 모델에 전달
    3. 모델이 tool_calls를 반환하면 실행 후 결과를 다시 전달
    4. 모델이 텍스트만 반환하면 최종 답변으로 스트리밍
    5. MAX_REACT_ITERATIONS 초과 시 강제 종료
    """

    def __init__(
        self,
        client: Any,
        local_tools: list[Tool],
        mcp_tools: list[Tool] | None = None,
    ):
        self.client = client
        # 로컬 도구만 모델에 노출
        self.tools = {t.name: t for t in local_tools}
        self.tool_definitions = llm.get_tool_definitions(local_tools)
        # MCP 도구는 선조회 전용
        self.mcp_tools = {t.name: t for t in (mcp_tools or [])}
        # 마지막 실행 정보 (타이밍 등)
        self.last_run_info: dict = {}

    def run(self, messages: list[dict]) -> str:
        """ReAct 루프 실행 (비스트리밍). 최종 텍스트 응답을 반환."""
        parts = []
        for tag, text in self.run_stream(messages):
            if tag == "content":
                parts.append(text)
        return "".join(parts) or "(응답 없음)"

    def run_stream(
        self, messages: list[dict]
    ) -> Generator[tuple[str, str], None, None]:
        """ReAct 루프 실행. (tag, text) 튜플을 yield.

        tag 종류:
          - "thinking": 모델의 추론 과정 (Extended Thinking 활성 시)
          - "content":  최종 텍스트 응답

        도구 실행 상태는 console.print로 직접 출력합니다.
        """
        total_start = time.time()
        self.last_run_info = {}

        # 마지막 user 메시지 추출
        user_input = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    user_input = content
                break

        # MCP 선조회 → 실패/저품질 시 Claude deep think fallback
        if user_input and self.mcp_tools and should_prefetch(user_input):
            prefetch_result = run_prefetch(user_input, self.mcp_tools)

            if is_low_quality(prefetch_result):
                console.print(
                    "  [yellow]MCP 결과 부족 → Claude deep think로 대체[/]"
                )
                claude_tool = self.tools.get("claude_escalate")
                if claude_tool:
                    claude_result = claude_tool.execute(
                        question=user_input, deep_think=True,
                    )
                    messages.append({
                        "role": "system",
                        "content": (
                            "아래는 Claude가 깊이 분석한 답변입니다. "
                            "이 정보를 참고하여 답변하세요:\n\n"
                            + claude_result
                        ),
                    })
            else:
                messages.append({
                    "role": "system",
                    "content": (
                        "아래는 사내 코드베이스에서 자동 조회한 참고 자료입니다. "
                        "이 정보를 기반으로 답변하세요:\n\n"
                        + prefetch_result
                    ),
                })

        use_thinking = config.ENABLE_THINKING and config.LLM_PROVIDER == "ollama"

        for i in range(config.MAX_REACT_ITERATIONS):
            step = i + 1

            console.print(
                f"  [dim]생각 중... (step {step}/{config.MAX_REACT_ITERATIONS})[/]"
            )

            think_start = time.time()

            # 스트리밍 청크 수집
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[dict] = []
            in_thinking = False

            for event_type, data in llm.chat_stream(
                self.client, messages,
                tools=self.tool_definitions,
                think=use_thinking,
            ):
                if event_type == "thinking":
                    thinking_parts.append(data)
                    if not in_thinking:
                        in_thinking = True
                        console.print("  [dim]🧠 추론 중...[/]")
                    if config.SHOW_THINKING:
                        yield ("thinking", data)

                elif event_type == "content":
                    if in_thinking:
                        in_thinking = False
                    content_parts.append(data)
                    # tool_calls가 아직 없으면 텍스트를 실시간 스트리밍
                    if not tool_calls:
                        yield ("content", data)

                elif event_type == "tool_call":
                    tool_calls.append(data)

            think_elapsed = time.time() - think_start
            full_content = "".join(content_parts)
            full_thinking = "".join(thinking_parts)

            # tool_calls가 없으면 최종 답변 (이미 yield 완료)
            if not tool_calls:
                self.last_run_info = {
                    "elapsed": time.time() - total_start,
                    "think_elapsed": think_elapsed,
                    "steps": step,
                }
                if full_thinking:
                    self.last_run_info["thinking_chars"] = len(full_thinking)
                return

            # ── 이하 tool_calls 처리 ──

            # 모델이 텍스트와 함께 tool_calls를 보낸 경우
            if full_content.strip():
                console.print(
                    f"  [dim italic]💭 {full_content.strip()[:200]}[/]"
                )

            # assistant 메시지 추가
            assistant_msg = llm.build_assistant_message(
                full_content, tool_calls, full_thinking
            )
            messages.append(assistant_msg)

            # 각 tool call 실행
            results: list[str] = []
            for call in tool_calls:
                tool_name = call["name"]
                tool_args = call["arguments"]

                console.print(
                    f"  [dim]step {step}[/] [blue]로컬[/] "
                    f"[bold]🔧 {tool_name}[/]"
                )
                if tool_args:
                    console.print(
                        f"         [dim]args: {_format_args(tool_args)}[/]"
                    )

                with console.status(
                    f"  [cyan]실행 중: {tool_name}...[/]", spinner="dots"
                ):
                    exec_start = time.time()
                    result = self._execute_tool(tool_name, tool_args)
                    exec_elapsed = time.time() - exec_start

                results.append(result)

                result_preview = _preview_result(result)
                is_error = result.startswith((
                    "⛔", "MCP 도구 호출 오류", "권한 오류",
                    "도구 실행 오류", "알 수 없는 도구",
                ))
                status_icon = "❌" if is_error else "✅"
                console.print(
                    f"         {status_icon} [dim]{exec_elapsed:.1f}s[/] "
                    f"[dim]{result_preview}[/]"
                )

            # tool result 메시지 추가
            result_messages = llm.build_tool_result_messages(
                tool_calls, results
            )
            messages.extend(result_messages)

        total_elapsed = time.time() - total_start
        console.print(f"  [red]⚠ 최대 반복 도달 ({total_elapsed:.1f}s)[/]")
        self.last_run_info = {
            "elapsed": total_elapsed,
            "steps": config.MAX_REACT_ITERATIONS,
        }
        yield ("content", "(최대 반복 횟수 초과 — 작업을 완료하지 못했습니다)")

    def _execute_tool(self, name: str, args: dict) -> str:
        """도구 실행 (에러 처리 + 교훈 기록)"""
        tool = self.tools.get(name)
        if not tool:
            return f"알 수 없는 도구: {name}"

        try:
            result = tool.execute(**args)
            return result
        except PermissionError as e:
            return f"권한 오류: {e}"
        except Exception as e:
            return f"도구 실행 오류 ({name}): {e}"


def _format_args(args: dict) -> str:
    """tool call 인자를 짧게 포매팅"""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def _preview_result(result: str) -> str:
    """결과를 한 줄 요약으로 축약"""
    lines = result.strip().splitlines()
    line_count = len(lines)
    char_count = len(result)

    first_line = lines[0].strip() if lines else ""
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."

    if line_count <= 1:
        return first_line
    return f"{first_line} (+{line_count - 1}줄, {char_count:,}자)"
