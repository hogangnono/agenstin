"""Sonnet 라우터 — 스크리닝, 라우팅, 간단한 응답 처리

채널 메시지 스크리닝과 DM/멘션 응답을 담당합니다.
- 간단한 질문 → Sonnet이 직접 답변
- 복잡한 작업 (코드 분석, 파일 탐색 등) → Claude Code CLI에 위임
"""

import logging

import anthropic

import config

logger = logging.getLogger("agenstin.router")


class Router:
    """Sonnet 기반 메시지 라우터.

    1. screen()  — 채널 메시지가 봇 응답에 적합한지 판별 + 이모지 선택
    2. respond() — 메시지에 응답 (간단하면 직접, 복잡하면 [DELEGATE] 반환)
    3. summarize_session() — 세션 요약 생성
    """

    VALID_EMOJIS = frozenset({
        "eyes", "bulb", "thinking_face", "rocket", "dart",
        "star", "fire", "raised_hands", "memo", "white_check_mark",
    })

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def screen(self, text: str) -> str | None:
        """채널 메시지 스크리닝.

        Returns:
            응답할 가치가 있으면 emoji 이름, 아니면 None.
        """
        try:
            resp = self.client.messages.create(
                model=config.ROUTER_MODEL,
                max_tokens=20,
                temperature=0.1,
                system=config.SCREENING_PROMPT,
                messages=[{"role": "user", "content": text}],
            )
            result = resp.content[0].text.strip()
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
        messages = list(conversation or [])
        messages.append({"role": "user", "content": user_input})

        try:
            resp = self.client.messages.create(
                model=config.ROUTER_MODEL,
                max_tokens=config.ROUTER_MAX_TOKENS,
                system=system or config.ROUTER_SYSTEM_PROMPT,
                messages=messages,
            )
            text = resp.content[0].text.strip()
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
            resp = self.client.messages.create(
                model=config.ROUTER_MODEL,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            # 실패 시 간단한 기계적 요약
            return f"세션 요약 ({len(turns)}턴)"
