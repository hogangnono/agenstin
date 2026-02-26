"""인시던트 분석 엔진 — 프로덕션 알림을 Claude Opus로 분석

AlertNow 등의 앱이 Slack에 보낸 인시던트 메시지를 감지하고,
관련 서브프로젝트에서 Claude CLI(Opus deep think)를 실행하여
근본 원인을 분석합니다.

이 모듈은 ReactEngine을 거치지 않고, Claude CLI를 직접 호출합니다.
"""

import logging
import os
import subprocess

import config

logger = logging.getLogger("agenstin.incident")


def is_incident_channel(channel_id: str) -> bool:
    """채널이 인시던트 알림 채널인지 확인."""
    return (
        config.INCIDENT_ANALYSIS_ENABLED
        and channel_id in config.INCIDENT_CHANNEL_IDS
    )


def resolve_project(incident_text: str) -> tuple[str | None, str | None]:
    """인시던트 텍스트에서 관련 서브프로젝트를 식별.

    Returns:
        (project_name, project_path) 또는 (None, None)
    """
    text_lower = incident_text.lower()
    workspace = config.INCIDENT_WORKSPACE

    # 긴 키워드부터 매칭하여 더 구체적인 프로젝트가 먼저 선택되도록
    # 예: "hogangnono-batch" 가 "hogangnono" 보다 먼저
    sorted_keywords = sorted(
        config.INCIDENT_PROJECT_MAP.keys(),
        key=len,
        reverse=True,
    )

    for keyword in sorted_keywords:
        if keyword.lower() in text_lower:
            dirname = config.INCIDENT_PROJECT_MAP[keyword]
            project_path = os.path.join(workspace, dirname)
            if os.path.isdir(project_path):
                return keyword, project_path
            else:
                logger.warning(
                    "프로젝트 디렉토리 없음: %s (키워드: %s)",
                    project_path, keyword,
                )

    return None, None


def _git_pull(cwd: str) -> None:
    """프로젝트 디렉토리에서 git pull 실행하여 최신 소스 확보."""
    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        if result.returncode == 0:
            logger.info("git pull 성공: %s — %s", cwd, result.stdout.strip())
        else:
            logger.warning("git pull 실패: %s — %s", cwd, result.stderr.strip())
    except Exception as e:
        logger.warning("git pull 오류: %s — %s", cwd, e)


def analyze_incident(incident_text: str, project_path: str | None = None) -> str:
    """Claude CLI(Opus deep think)로 인시던트를 분석.

    Args:
        incident_text: 인시던트 메시지 전체 텍스트
        project_path: Claude CLI의 cwd로 설정할 프로젝트 경로.
                      None이면 워크스페이스 루트 사용.

    Returns:
        분석 결과 문자열
    """
    cwd = project_path or config.INCIDENT_WORKSPACE

    # 최신 소스 코드로 갱신
    _git_pull(cwd)

    prompt = (
        f"{config.INCIDENT_ANALYSIS_PROMPT}\n\n"
        f"## Incident Alert\n"
        f"```\n{incident_text}\n```"
    )

    cmd = [
        config.CLAUDE_CLI_PATH,
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--effort", "high",
    ]

    timeout = config.INCIDENT_CLAUDE_TIMEOUT

    logger.info(
        "인시던트 분석 시작: cwd=%s, timeout=%ds",
        cwd, timeout,
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
        return (
            f"Claude CLI를 찾을 수 없습니다: {config.CLAUDE_CLI_PATH}\n"
            "claude code가 설치되어 있는지 확인하세요."
        )
    except subprocess.TimeoutExpired:
        return (
            f"인시던트 분석 타임아웃 ({timeout}초 초과)\n"
            "인시던트가 너무 복잡하거나 코드베이스가 매우 큰 경우 발생할 수 있습니다.\n"
            "수동 분석을 권장합니다."
        )

    output = result.stdout
    if result.stderr:
        stderr_lines = [
            line for line in result.stderr.strip().splitlines()
            if not line.startswith(("\r", "╭", "│", "╰", "⠋", "⠙", "⠹"))
        ]
        if stderr_lines:
            output += f"\n[참고] {chr(10).join(stderr_lines[:5])}"

    max_output = config.INCIDENT_CLAUDE_MAX_OUTPUT
    if len(output) > max_output:
        output = output[:max_output] + "\n... (분석 출력이 너무 길어 잘렸습니다)"

    if not output.strip():
        return "(Claude로부터 분석 결과를 받지 못했습니다)"

    return output
