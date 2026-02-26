"""Shell 도구 — 읽기 전용 명령어만 허용"""

import shlex
import subprocess

import config
from tools.base import Tool


def _validate_command(command: str) -> str | None:
    """명령어 검증. 문제가 있으면 에러 메시지 반환, 없으면 None."""
    # 위험 패턴 검사 (파싱 전에 먼저 체크)
    for pattern in config.SHELL_DANGEROUS_PATTERNS:
        if pattern in command:
            return f"차단된 패턴 포함: '{pattern}'"

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"명령어 파싱 오류: {e}"

    if not parts:
        return "빈 명령어"

    cmd = parts[0]
    if cmd not in config.SHELL_COMMAND_WHITELIST:
        allowed = ", ".join(config.SHELL_COMMAND_WHITELIST)
        return f"허용되지 않은 명령어: '{cmd}'\n허용 목록: {allowed}"

    return None


class ShellTool(Tool):
    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "읽기 전용 쉘 명령어를 실행합니다. "
            f"허용 명령어: {', '.join(config.SHELL_COMMAND_WHITELIST)}. "
            "파이프(|), 리다이렉션(>), 명령어 체이닝(&&, ;)은 사용할 수 없습니다."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "실행할 쉘 명령어 (예: 'ls -la', 'grep -r pattern .')",
                },
            },
            "required": ["command"],
        }

    def execute(self, **kwargs) -> str:
        command = kwargs.get("command", "")
        if not command:
            return "command가 필요합니다."

        error = _validate_command(command)
        if error:
            return f"⛔ {error}"

        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=config.SHELL_TIMEOUT,
                cwd=None,  # 현재 작업 디렉토리에서 실행
            )
        except subprocess.TimeoutExpired:
            return f"⏱️ 타임아웃 ({config.SHELL_TIMEOUT}초 초과)"
        except FileNotFoundError:
            return f"명령어를 찾을 수 없습니다: {shlex.split(command)[0]}"

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"

        if len(output) > config.MAX_OUTPUT_LENGTH:
            output = output[: config.MAX_OUTPUT_LENGTH] + "\n... (출력 잘림)"

        if not output.strip():
            return "(출력 없음)"

        return output
