"""Sonnet 라우터 — Claude CLI를 통한 스크리닝, 라우팅, 응답

채널 메시지 스크리닝과 DM/멘션 응답을 담당합니다.
Anthropic API 대신 Claude Code CLI (--model sonnet)를 사용합니다.
- 간단한 질문 → Sonnet이 직접 답변
- 복잡한 작업 (코드 분석, 파일 탐색 등) → Claude Code CLI에 위임
"""

import logging

from core import claude_cli
import config

logger = logging.getLogger("agenstin.router")


class Router:
    """Sonnet 기반 메시지 라우터 (Claude CLI 사용).

    1. screen()  — 채널 메시지가 봇 응답에 적합한지 판별 + 이모지 선택
    2. respond() — 메시지에 응답 (간단하면 직접, 복잡하면 [DELEGATE] 반환)
    3. summarize_session() — 세션 요약 생성
    """

    VALID_EMOJIS = frozenset({
        "eyes", "bulb", "thinking_face", "rocket", "dart",
        "star", "fire", "raised_hands", "memo", "white_check_mark",
    })

    def screen(self, text: str) -> str | None:
        """채널 메시지 스크리닝.

        Returns:
            응답할 가치가 있으면 emoji 이름, 아니면 None.
        """
        prompt = f"{config.SCREENING_PROMPT}\n\n---\n\n{text}"

        try:
            result = claude_cli.run(
                prompt=prompt,
                model=config.ROUTER_MODEL,
                timeout=config.ROUTER_TIMEOUT,
                max_output=100,
            )
            result = result.strip()
        except Exception as e:
            logger.warning("스크리닝 호출 실패: %s", e)
            return None

        parts = result.split()
        if not parts or parts[0].upper() != "YES":
            return None

        emoji = parts[1].lower() if len(parts) >= 2 else "eyes"
        if emoji not in self.VALID_EMOJIS:
            emoji = "eyes"
        return emoji

    def respond(
        self,
        user_input: str,
        system: str = "",
        conversation: list[dict] | None = None,
    ) -> tuple[str, bool]:
        """메시지에 응답. (response_text, delegated) 반환.

        Sonnet이 직접 답변할 수 있으면 (response, False).
        복잡한 작업이 필요하면 ("[DELEGATE] ...", True).
        """
        prompt_parts = []

        # 시스템 프롬프트
        sys_prompt = system or config.ROUTER_SYSTEM_PROMPT
        prompt_parts.append(f"<system>\n{sys_prompt}\n</system>")

        # 대화 이력
        if conversation:
            history = []
            for m in conversation[-20:]:
                history.append(f"{m['role']}: {m['content']}")
            prompt_parts.append(
                "<conversation_history>\n"
                + "\n".join(history)
                + "\n</conversation_history>"
            )

        prompt_parts.append(user_input)
        prompt = "\n\n".join(prompt_parts)

        try:
            text = claude_cli.run(
                prompt=prompt,
                model=config.ROUTER_MODEL,
                timeout=config.ROUTER_TIMEOUT,
            )
            text = text.strip()
        except Exception as e:
            logger.error("Sonnet 응답 실패: %s", e)
            return f"응답 생성 중 오류가 발생했습니다: {e}", False

        if text.startswith("[DELEGATE]"):
            return text, True

        return text, False

    def summarize_session(self, messages: list[dict]) -> str:
        """세션 대화를 요약."""
        turns = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                preview = content[:300]
                if len(content) > 300:
                    preview += "..."
                turns.append(f"{role}: {preview}")

        if not turns:
            return ""

        prompt = (
            "아래 대화를 3줄 이내로 핵심만 요약하세요. 한국어로 작성.\n\n"
            + "\n".join(turns)
        )

        try:
            result = claude_cli.run(
                prompt=prompt,
                model=config.ROUTER_MODEL,
                timeout=config.ROUTER_TIMEOUT,
                max_output=500,
            )
            return result.strip()
        except Exception:
            return f"세션 요약 ({len(turns)}턴)"
