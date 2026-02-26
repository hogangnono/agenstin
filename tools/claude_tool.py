"""Claude Code 에스컬레이션 도구 — 복잡한 작업을 Claude에 위임"""

import subprocess

import config
from tools.base import Tool


class ClaudeEscalateTool(Tool):
    @property
    def name(self) -> str:
        return "claude_escalate"

    @property
    def description(self) -> str:
        return (
            "복잡한 코드 분석, 논리적 추론, 전문 지식이 필요한 질문을 "
            "Claude Code (고급 AI)에 위임합니다. "
            "단순한 파일 조회나 검색은 다른 도구를 사용하고, "
            "정말 어려운 질문일 때만 이 도구를 사용하세요. "
            "deep_think=true로 설정하면 최고 성능 모델(opus)이 "
            "깊이 사고하여 답변합니다. 수학, 논리 퍼즐, 복잡한 아키텍처 "
            "설계 등 고난도 추론에 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Claude에게 전달할 질문 (구체적이고 명확하게)",
                },
                "deep_think": {
                    "type": "boolean",
                    "description": (
                        "깊은 사고 모드 활성화. "
                        "고난도 추론, 복잡한 분석이 필요할 때 true. "
                        "일반 질문은 false (기본값)"
                    ),
                },
            },
            "required": ["question"],
        }

    def execute(self, **kwargs) -> str:
        question = kwargs.get("question", "")
        if not question:
            return "question이 필요합니다."

        deep_think = kwargs.get("deep_think", False)

        cmd = [config.CLAUDE_CLI_PATH, "-p", question, "--dangerously-skip-permissions"]
        if deep_think:
            cmd.extend(["--model", "opus", "--effort", "high"])

        timeout = config.CLAUDE_THINK_TIMEOUT if deep_think else config.CLAUDE_TIMEOUT

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return (
                f"Claude CLI를 찾을 수 없습니다: {config.CLAUDE_CLI_PATH}\n"
                "claude code가 설치되어 있는지 확인하세요."
            )
        except subprocess.TimeoutExpired:
            return f"Claude 응답 타임아웃 ({timeout}초 초과)"

        output = result.stdout
        if result.stderr:
            output += f"\n[참고] {result.stderr[:500]}"

        if len(output) > config.CLAUDE_MAX_OUTPUT_LENGTH:
            output = output[: config.CLAUDE_MAX_OUTPUT_LENGTH] + "\n... (출력 잘림)"

        if not output.strip():
            return "(Claude로부터 응답을 받지 못했습니다)"

        label = "Claude Deep Think" if deep_think else "Claude"
        return f"[{label} 응답]\n{output}"
