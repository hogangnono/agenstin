"""인시던트 분석 — ReactEngine + claude_escalate 기반

AlertNow 등의 앱이 Slack에 보낸 인시던트 메시지를 감지하고,
ReactEngine이 트리아지한 뒤 코드 분석이 필요하면
claude_escalate(deep_think=True)를 통해 Opus 모델로 분석합니다.
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


def git_pull(cwd: str) -> None:
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


def build_incident_system_prompt(project_path: str | None = None) -> str:
    """인시던트 분석용 ReactEngine 시스템 프롬프트를 생성.

    Args:
        project_path: 식별된 프로젝트 디렉토리 경로.
                      None이면 워크스페이스 루트 사용.
    """
    cwd = project_path or config.INCIDENT_WORKSPACE
    prompt = config.INCIDENT_REACTENGINE_PROMPT

    if cwd:
        prompt += (
            f"\n## 프로젝트 정보\n"
            f"- 코드베이스 경로: `{cwd}`\n"
            f"- claude_escalate 호출 시 `cwd=\"{cwd}\"` 를 반드시 전달하세요.\n"
            f"- `timeout={config.INCIDENT_CLAUDE_TIMEOUT}` 을 전달하세요 "
            f"(코드 수정+PR 생성에 충분한 시간 확보).\n"
        )

    prompt += (
        "\n## 분석 프롬프트 템플릿\n"
        "claude_escalate의 question에 아래 프롬프트를 포함하세요:\n\n"
        f"```\n{config.INCIDENT_ANALYSIS_PROMPT}\n```\n"
    )

    return prompt
