"""인시던트 분석 — Claude Code CLI 기반

인시던트 알림 메시지를 감지하고 Claude Code CLI로 코드베이스를 분석합니다.
"""

import logging
import os
import subprocess

import config
from core.claude_cli import run_deep

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
            logger.warning(
                "프로젝트 디렉토리 없음: %s (키워드: %s)",
                project_path, keyword,
            )

    return None, None


def git_pull(cwd: str) -> None:
    """프로젝트 디렉토리에서 git pull 실행."""
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


def analyze(incident_text: str, project_path: str | None = None) -> str:
    """인시던트를 분석하고 결과를 반환.

    Claude Code CLI (Opus, deep think)로 코드베이스를 탐색하며 근본 원인을 분석합니다.
    """
    cwd = project_path or config.INCIDENT_WORKSPACE or None

    prompt = (
        f"{config.INCIDENT_ANALYSIS_PROMPT}\n\n"
        f"## Incident Alert\n```\n{incident_text}\n```"
    )

    return run_deep(
        prompt=prompt,
        cwd=cwd,
        timeout=config.INCIDENT_CLAUDE_TIMEOUT,
    )
