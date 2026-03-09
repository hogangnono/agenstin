"""Agenstin — CLI 인터페이스

Sonnet 라우터로 간단한 질문에 직접 답변하고,
복잡한 작업은 Claude Code CLI에 위임합니다.
"""

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown

import config
from core import claude_cli
from core.router import Router
from memory.manager import MemoryManager

console = Console()


def _build_system_prompt(memory_manager: MemoryManager) -> str:
    parts = [config.ROUTER_SYSTEM_PROMPT]

    soul = memory_manager.get_soul()
    if soul:
        parts.append(f"## 에이전트 성격\n{soul}")

    excerpt = memory_manager.get_memory_excerpt()
    if excerpt:
        parts.append(f"## 기억된 정보\n{excerpt}")

    return "\n\n".join(parts)


def main():
    console.print("[bold cyan]Agenstin[/] — AI 비서 (Ctrl+C로 종료)\n")

    # 초기화
    router = Router()
    memory_manager = MemoryManager()
    mem_info = memory_manager.startup()
    console.print(
        f"[dim]메모리: SOUL {mem_info['soul_chars']}자, "
        f"MEMORY {mem_info['memory_chars']}자[/]"
    )
    console.print(f"라우터: [green]{config.ROUTER_MODEL}[/] → Claude Code CLI\n")

    system_prompt = _build_system_prompt(memory_manager)
    memory_context = memory_manager.get_memory_excerpt()
    conversation: list[dict] = []

    try:
        _run_loop(router, system_prompt, memory_context, conversation)
    finally:
        # 세션 요약 저장
        if conversation:
            summary = router.summarize_session(conversation)
            memory_manager.end_session(conversation, summary=summary)


def _run_loop(
    router: Router,
    system_prompt: str,
    memory_context: str,
    conversation: list[dict],
):
    """대화 루프"""
    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        buf = event.current_buffer
        if buf.text.strip():
            buf.insert_text("\n")
        else:
            buf.validate_and_handle()

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    session = PromptSession(key_bindings=kb, multiline=True)

    while True:
        try:
            user_input = session.prompt(
                HTML("<b><yellow>You&gt;</yellow></b> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]종료합니다.[/]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]종료합니다.[/]")
            break

        conversation.append({"role": "user", "content": user_input})

        # Sonnet 라우터로 응답 시도
        with console.status("[cyan]생각 중...[/]"):
            response, delegated = router.respond(
                user_input,
                system=system_prompt,
                conversation=conversation[-20:],
            )

        if delegated:
            # Claude CLI에 위임
            console.print("[dim]Claude Code CLI에 위임합니다...[/]")
            with console.status("[cyan]Claude Code 실행 중...[/]"):
                prompt = _build_claude_prompt(
                    user_input, conversation[:-1], memory_context
                )
                response = claude_cli.run(prompt)

        conversation.append({"role": "assistant", "content": response})

        console.print()
        console.print(Markdown(response))
        console.print()


def _build_claude_prompt(
    user_text: str,
    conversation: list[dict],
    memory_context: str,
) -> str:
    """Claude CLI에 전달할 프롬프트 구성."""
    parts = []

    if memory_context:
        parts.append(f"<memory>\n{memory_context}\n</memory>")

    if conversation:
        history = []
        for m in conversation[-20:]:
            history.append(f"{m['role']}: {m['content']}")
        if history:
            parts.append(
                "<conversation_history>\n"
                + "\n".join(history)
                + "\n</conversation_history>"
            )

    parts.append(user_text)
    return "\n\n".join(parts)


if __name__ == "__main__":
    main()
