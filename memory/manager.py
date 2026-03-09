"""MemoryManager — 간소화된 메모리 시스템

마크다운 파일 기반의 장기 기억 관리.
인덱싱/검색 없이 SOUL.md, MEMORY.md, 일별 로그만 관리합니다.
"""

import logging
from datetime import datetime

import config
from memory.store import (
    append_to_daily_log,
    append_to_memory,
    load_memory,
    load_soul,
)

logger = logging.getLogger("agenstin.memory")


class MemoryManager:
    """메모리 시스템 파사드.

    Lifecycle:
        1. startup() — SOUL.md, MEMORY.md 로드
        2. get_soul() / get_memory_excerpt() — 프롬프트 주입용
        3. save() — 기억 저장
        4. end_session() — 세션 요약을 일별 로그에 기록
    """

    def __init__(self):
        self._soul_content: str = ""
        self._memory_content: str = ""

    def startup(self) -> dict:
        """세션 시작 시 호출. 파일 로드."""
        self._soul_content = load_soul()
        self._memory_content = load_memory()

        logger.info(
            "메모리 로드: SOUL %d자, MEMORY %d자",
            len(self._soul_content),
            len(self._memory_content),
        )

        return {
            "soul_chars": len(self._soul_content),
            "memory_chars": len(self._memory_content),
        }

    def get_soul(self) -> str:
        if not self._soul_content:
            self._soul_content = load_soul()
        return self._soul_content

    def get_memory_excerpt(self, max_length: int | None = None) -> str:
        """MEMORY.md에서 시스템 프롬프트에 넣을 발췌문 반환."""
        max_length = max_length or config.MEMORY_EXCERPT_MAX_LENGTH
        if not self._memory_content:
            self._memory_content = load_memory()

        content = self._memory_content
        if len(content) <= max_length:
            return content

        return "...(이전 내용 생략)...\n\n" + content[-max_length:]

    def save(self, content: str, target: str = "memory") -> str:
        """기억 저장."""
        if target == "memory":
            append_to_memory(content)
            self._memory_content = load_memory()
            return f"MEMORY.md에 저장됨 ({len(content)}자)"

        if target == "daily":
            append_to_daily_log(content)
            date_str = datetime.now().strftime("%Y-%m-%d")
            return f"일별 로그({date_str})에 저장됨 ({len(content)}자)"

        return f"알 수 없는 대상: {target}. 'memory' 또는 'daily' 사용."

    def end_session(self, messages: list[dict], summary: str = "") -> None:
        """세션 종료 시 호출. 요약을 일별 로그에 기록."""
        if summary:
            append_to_daily_log(summary)
            logger.info("세션 요약 저장 완료")
            return

        # summary가 없으면 간단한 기계적 요약
        turns = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                preview = content[:200]
                if len(content) > 200:
                    preview += "..."
                turns.append(f"- **{role}**: {preview}")

        if turns:
            fallback = f"### 세션 요약 ({len(turns)}턴)\n" + "\n".join(turns)
            append_to_daily_log(fallback)
            logger.info("세션 요약 저장: %d턴", len(turns))
