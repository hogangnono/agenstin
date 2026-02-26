"""Agenstin — 로컬 AI 비서 CLI"""

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

import config
from core import llm
from core.mcp_client import McpManager
from core.react import ReactEngine
from memory.manager import MemoryManager
from tools.file_tool import ListFilesTool, ReadFileTool
from tools.shell_tool import ShellTool
from tools.search_tool import GoogleSearchTool, NaverSearchTool
from tools.claude_tool import ClaudeEscalateTool
from tools.browser_tool import BrowseWebTool, ScreenshotTool
from tools.memory_tool import MemorySearchTool, MemorySaveTool

console = Console()


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

    # SOUL.md 주입
    soul = memory_manager.get_soul()
    if soul:
        parts.append(f"## 에이전트 성격\n{soul}")

    # MEMORY.md 발췌 주입
    memory_excerpt = memory_manager.get_memory_excerpt()
    if memory_excerpt:
        parts.append(f"## 기억된 정보\n{memory_excerpt}")

    # 메모리 도구 사용 안내
    parts.append(
        "## 메모리 사용 안내\n"
        "- 과거 대화나 사용자 선호를 알아야 하면 memory_search를 사용하세요.\n"
        "- 중요한 사실(사용자 선호, 프로젝트 정보 등)을 발견하면 memory_save로 기억하세요.\n"
        "- 사용자가 '기억해', 'remember this' 등을 말하면 반드시 memory_save를 사용하세요.\n"
        "- 사소한 대화는 저장하지 마세요. 반복적으로 유용할 정보만 저장하세요."
    )

    return "\n\n".join(parts)


def main():
    console.print("[bold cyan]Agenstin[/] — AI 비서 (Ctrl+C로 종료)\n")

    client = llm.create_client()

    # LLM 연결 확인
    try:
        llm.check_connection(client)
    except Exception as e:
        console.print(f"[red]LLM 연결 실패:[/] {e}")
        if config.LLM_PROVIDER == "ollama":
            console.print("ollama가 실행 중인지 확인하세요: [dim]ollama serve[/]")
        else:
            console.print("API 키를 확인하세요: [dim]config.py 또는 ANTHROPIC_API_KEY 환경변수[/]")
        sys.exit(1)

    # 임베딩용 Ollama 클라이언트 (메모리 시스템)
    embed_client = None
    try:
        embed_client = llm.create_embed_client()
        embed_client.list()
    except Exception:
        console.print("[yellow]Ollama 연결 실패 — 벡터 검색 비활성화 (BM25 전용)[/]")
        embed_client = None

    # 메모리 시스템 초기화
    memory_manager = MemoryManager(client=embed_client)
    mem_info = memory_manager.startup()
    console.print(
        f"[dim]메모리: SOUL {mem_info['soul_chars']}자, "
        f"MEMORY {mem_info['memory_chars']}자, "
        f"인덱스 {mem_info['index_chunks']}청크[/]"
    )

    # 로컬 도구 (메모리 도구 포함)
    local_tools = _build_local_tools(memory_manager)

    # MCP 서버 연결 (선조회 전용, 모델에 직접 노출하지 않음)
    mcp_manager = McpManager()
    mcp_tools = []
    if config.MCP_SERVERS:
        console.print("[dim]MCP 서버 연결 중...[/]")
        mcp_tools = mcp_manager.connect_all()

    engine = ReactEngine(client, local_tools, mcp_tools=mcp_tools)

    console.print(f"모델: [green]{llm.get_model_name()}[/] ({config.LLM_PROVIDER})")
    if config.ENABLE_THINKING and config.LLM_PROVIDER == "ollama":
        console.print("[dim]Extended Thinking: 활성[/]")
    console.print(
        f"도구: [blue]{len(local_tools)}개 로컬[/] + "
        f"[magenta]{len(mcp_tools)}개 MCP 선조회[/]\n"
    )

    # 세션 초기화
    messages = [{"role": "system", "content": _build_system_prompt(memory_manager)}]

    try:
        _run_loop(engine, messages)
    finally:
        # 세션 종료: 대화 요약을 일별 로그에 저장
        memory_manager.end_session(messages)
        memory_manager.close()
        mcp_manager.disconnect_all()


def _run_loop(engine: ReactEngine, messages: list[dict]):
    """대화 루프"""
    # Enter = 줄바꿈, Meta+Enter(Esc→Enter) = 제출
    # 빈 상태에서 Enter = 제출 (빈 입력 방지)
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
            user_input = session.prompt(HTML("<b><yellow>You&gt;</yellow></b> ")).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]종료합니다.[/]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]종료합니다.[/]")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            reply = _stream_response(engine, messages)
            messages.append({"role": "assistant", "content": reply})
        except Exception as e:
            console.print(f"\n[red]오류:[/] {e}\n")


def _stream_response(engine: ReactEngine, messages: list[dict]) -> str:
    """스트리밍 응답을 Rich Live + Markdown으로 실시간 표시.

    Extended Thinking 활성 시:
      - ("thinking", text) → dim italic으로 실시간 표시
      - ("content", text)  → Markdown Live로 렌더링
    """
    full_text = ""
    thinking_text = ""
    live: Live | None = None
    thinking_live: Live | None = None

    try:
        for tag, chunk in engine.run_stream(messages):
            if tag == "thinking":
                thinking_text += chunk
                if thinking_live is None:
                    console.print()
                    thinking_live = Live(
                        Text(thinking_text, style="dim italic"),
                        console=console,
                        refresh_per_second=8,
                        vertical_overflow="visible",
                    )
                    thinking_live.start()
                else:
                    thinking_live.update(
                        Text(thinking_text, style="dim italic")
                    )

            elif tag == "content":
                # thinking → content 전환 시 thinking Live 종료
                if thinking_live:
                    thinking_live.stop()
                    thinking_live = None
                    lines = thinking_text.strip().count("\n") + 1
                    console.print(
                        f"  [dim]🧠 추론 완료 ({lines}줄, "
                        f"{len(thinking_text):,}자)[/]"
                    )

                full_text += chunk
                if live is None:
                    console.print()
                    live = Live(
                        Markdown(full_text),
                        console=console,
                        refresh_per_second=10,
                        vertical_overflow="visible",
                    )
                    live.start()
                else:
                    live.update(Markdown(full_text))
    finally:
        if thinking_live:
            thinking_live.stop()
        if live:
            live.stop()

    if not full_text:
        full_text = "(응답 없음)"
        console.print(f"\n{full_text}")

    # 타이밍 정보 표시
    info = engine.last_run_info
    parts = []
    if info.get("elapsed"):
        parts.append(f"{info['elapsed']:.1f}s")
    if info.get("steps", 1) > 1:
        parts.append(f"{info['steps']}단계")
    if info.get("thinking_chars"):
        parts.append(f"추론 {info['thinking_chars']:,}자")

    if parts and (info.get("steps", 1) > 1 or info.get("think_elapsed", 0) > 2
                  or info.get("thinking_chars")):
        console.print(f"  [dim]완료 ({', '.join(parts)})[/]")

    console.print()
    return full_text


if __name__ == "__main__":
    main()
