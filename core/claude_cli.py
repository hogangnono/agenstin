"""Claude Code CLI 래퍼 — 복잡한 작업을 Claude Code에 위임

subprocess로 `claude` CLI를 호출하여 코드 분석, 파일 탐색,
MCP 연동 등 복잡한 작업을 처리합니다.
"""

import logging
import subprocess

import config

logger = logging.getLogger("agenstin.claude_cli")


def run(
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    timeout: int | None = None,
    max_output: int | None = None,
) -> str:
    """Claude Code CLI를 실행하고 결과를 반환.

    Args:
        prompt: Claude에게 전달할 프롬프트
        cwd: 실행 디렉토리 (코드베이스 분석 시 프로젝트 경로)
        model: 모델 지정 (기본: CLI 기본값, "opus" 등)
        effort: 추론 노력 ("high", "medium", "low")
        timeout: 타임아웃 (초). 기본값: config.CLAUDE_TIMEOUT
        max_output: 최대 출력 길이. 기본값: config.CLAUDE_MAX_OUTPUT_LENGTH
    """
    cmd = [config.CLAUDE_CLI_PATH, "-p", prompt, "--dangerously-skip-permissions"]

    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])

    timeout = timeout or config.CLAUDE_TIMEOUT
    max_output = max_output or config.CLAUDE_MAX_OUTPUT_LENGTH

    logger.info(
        "Claude CLI 실행: model=%s effort=%s timeout=%ds cwd=%s prompt=%s",
        model or "default", effort or "default", timeout,
        cwd or ".", prompt[:100],
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError:
        msg = (
            f"Claude CLI를 찾을 수 없습니다: {config.CLAUDE_CLI_PATH}\n"
            "Claude Code가 설치되어 있는지 확인하세요."
        )
        logger.error(msg)
        return msg
    except subprocess.TimeoutExpired:
        msg = f"Claude CLI 응답 타임아웃 ({timeout}초 초과)"
        logger.warning(msg)
        return msg

    output = result.stdout
    if result.stderr:
        output += f"\n[stderr] {result.stderr[:500]}"

    if not output.strip():
        return "(Claude로부터 응답을 받지 못했습니다)"

    if len(output) > max_output:
        output = output[:max_output] + "\n... (출력 잘림)"

    return output


def run_deep(
    prompt: str,
    cwd: str | None = None,
    timeout: int | None = None,
) -> str:
    """Opus + high effort로 깊이 분석. 인시던트 분석 등에 사용."""
    return run(
        prompt=prompt,
        cwd=cwd,
        model="opus",
        effort="high",
        timeout=timeout or config.CLAUDE_DEEP_TIMEOUT,
        max_output=config.CLAUDE_DEEP_MAX_OUTPUT,
    )
