"""MCP (Model Context Protocol) 클라이언트

원격 MCP 서버에 연결하여 제공하는 도구들을 가져오고,
ReAct 루프에서 사용할 수 있는 Tool 객체로 변환합니다.

이벤트 루프를 백그라운드 스레드에서 실행하여
MCP 세션을 프로그램 수명 동안 유지합니다.
"""

import asyncio
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from rich.console import Console

import config
from tools.base import Tool

console = Console()


class _LoopThread:
    """백그라운드 이벤트 루프 스레드

    MCP 세션은 하나의 이벤트 루프에서 생성되고 사용되어야 합니다.
    이 클래스는 별도 스레드에서 루프를 실행하고,
    동기 코드에서 코루틴을 안전하게 실행할 수 있게 해줍니다.
    """

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_coroutine(self, coro, timeout: float | None = None):
        """코루틴을 백그라운드 루프에서 실행하고 결과 반환 (동기)"""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


class McpTool(Tool):
    """MCP 서버에서 가져온 도구를 Agenstin Tool로 래핑"""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        tool_parameters: dict,
        session: ClientSession,
        loop_thread: _LoopThread,
    ):
        self._name = f"{server_name}_{tool_name}"
        self._original_name = tool_name
        self._description = tool_description
        self._parameters = tool_parameters
        self._session = session
        self._loop_thread = loop_thread

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    def execute(self, **kwargs) -> str:
        """MCP 도구 호출 (동기 래퍼)"""
        try:
            result = self._loop_thread.run_coroutine(
                self._call_tool(kwargs),
                timeout=config.MCP_CALL_TIMEOUT,
            )
        except Exception as e:
            return f"MCP 도구 호출 오류 ({self._original_name}): {e}"

        if len(result) > config.MCP_MAX_RESULT_LENGTH:
            result = result[: config.MCP_MAX_RESULT_LENGTH] + "\n... (결과 잘림)"

        return result

    async def _call_tool(self, arguments: dict) -> str:
        """실제 MCP tool/call 요청"""
        result = await self._session.call_tool(
            self._original_name, arguments=arguments
        )

        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            elif hasattr(content, "data"):
                parts.append(str(content.data))
            else:
                parts.append(str(content))

        return "\n".join(parts) if parts else "(결과 없음)"


class McpManager:
    """MCP 서버 연결 관리자

    백그라운드 이벤트 루프에서 MCP 세션을 유지합니다.
    """

    def __init__(self):
        self._loop_thread = _LoopThread()
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[McpTool] = []

    def connect_all(self) -> list[McpTool]:
        """설정된 모든 MCP 서버에 연결하고 도구 목록 반환"""
        try:
            return self._loop_thread.run_coroutine(
                self._connect_all_async(),
                timeout=config.MCP_CONNECT_TIMEOUT,
            )
        except Exception as e:
            console.print(f"[yellow]MCP 연결 실패:[/] {e}")
            return []

    async def _connect_all_async(self) -> list[McpTool]:
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for server_config in config.MCP_SERVERS:
            if not server_config.get("enabled", True):
                continue

            name = server_config["name"]
            url = server_config["url"]

            try:
                tools = await self._connect_server(name, url)
                self._tools.extend(tools)
                console.print(
                    f"  [green]✓[/] {name}: {len(tools)}개 도구 로드"
                )
            except Exception as e:
                console.print(f"  [yellow]✗[/] {name}: 연결 실패 ({e})")

        return self._tools

    async def _connect_server(
        self, name: str, url: str
    ) -> list[McpTool]:
        """단일 MCP 서버에 연결"""
        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
            streamablehttp_client(url)
        )

        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # 서버에서 도구 목록 가져오기
        tools_result = await session.list_tools()

        mcp_tools = []
        for tool in tools_result.tools:
            params = tool.inputSchema if tool.inputSchema else {
                "type": "object", "properties": {}
            }

            mcp_tool = McpTool(
                server_name=name,
                tool_name=tool.name,
                tool_description=tool.description or f"MCP tool: {tool.name}",
                tool_parameters=params,
                session=session,
                loop_thread=self._loop_thread,
            )
            mcp_tools.append(mcp_tool)

        return mcp_tools

    def disconnect_all(self):
        """모든 MCP 서버 연결 해제"""
        if self._exit_stack:
            try:
                self._loop_thread.run_coroutine(
                    self._exit_stack.aclose(), timeout=10
                )
            except Exception:
                pass
        self._loop_thread.stop()
