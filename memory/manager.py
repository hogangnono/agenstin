"""MemoryManager — 메모리 시스템 파사드

모든 메모리 작업을 이 클래스를 통해 수행합니다.
main.py와 tools에서 이 인스턴스를 공유합니다.
"""

import logging
from datetime import datetime
from typing import Any

import config
from memory.chunker import chunk_markdown
from memory.index import MemoryIndex
from memory.store import (
    append_to_daily_log,
    append_to_memory,
    list_daily_logs,
    load_daily_log,
    load_memory,
    load_soul,
)

logger = logging.getLogger("agenstin.memory.manager")


class MemoryManager:
    """메모리 시스템의 통합 인터페이스.

    Lifecycle:
        1. 생성 시 — SQLite 인덱스 초기화
        2. startup() — SOUL.md, MEMORY.md 로드 + 인덱스 동기화
        3. search() — 검색 (tool에서 호출)
        4. save() — 기억 저장 (tool에서 호출)
        5. end_session() — 세션 요약을 일별 로그에 저장
    """

    def __init__(self, client: Any | None = None):
        self.client = client
        self.index = MemoryIndex()
        self._soul_content: str = ""
        self._memory_content: str = ""

    def startup(self) -> dict:
        """세션 시작 시 호출. 파일 로드 + 인덱스 동기화.

        Returns:
            {"soul_chars": int, "memory_chars": int, "index_chunks": int}
        """
        # SOUL.md (시스템 프롬프트 전문 주입, 인덱스에는 넣지 않음)
        self._soul_content = load_soul()

        # MEMORY.md 인덱스 동기화
        self._memory_content = load_memory()
        memory_chunks = chunk_markdown(
            self._memory_content, source="MEMORY.md"
        )
        if memory_chunks:
            self.index.upsert_source("MEMORY.md", memory_chunks, self.client)

        # 최근 7일 일별 로그 인덱스 동기화
        for date_str in list_daily_logs()[:7]:
            source = f"{date_str}.md"
            if self.index.count(source) == 0:
                log_text = load_daily_log(date_str)
                if log_text:
                    log_chunks = chunk_markdown(log_text, source=source)
                    if log_chunks:
                        self.index.upsert_source(
                            source, log_chunks, self.client
                        )

        total_chunks = self.index.count()
        logger.info(
            "메모리 로드: SOUL %d자, MEMORY %d자, 인덱스 %d청크",
            len(self._soul_content),
            len(self._memory_content),
            total_chunks,
        )

        return {
            "soul_chars": len(self._soul_content),
            "memory_chars": len(self._memory_content),
            "index_chunks": total_chunks,
        }

    def get_soul(self) -> str:
        """SOUL.md 내용 반환."""
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

        # 뒤쪽(최근)을 우선
        return "...(이전 내용 생략)...\n\n" + content[-max_length:]

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """메모리 검색."""
        return self.index.search(query, top_k=top_k, client=self.client)

    def save(self, content: str, target: str = "memory") -> str:
        """기억 저장.

        Args:
            content: 저장할 내용
            target: "memory" (MEMORY.md) 또는 "daily" (오늘 일별 로그)
        """
        if target == "memory":
            append_to_memory(content)
            self._memory_content = load_memory()
            chunks = chunk_markdown(self._memory_content, source="MEMORY.md")
            self.index.upsert_source("MEMORY.md", chunks, self.client)
            return f"MEMORY.md에 저장됨 ({len(content)}자)"

        if target == "daily":
            append_to_daily_log(content)
            date_str = datetime.now().strftime("%Y-%m-%d")
            source = f"{date_str}.md"
            new_chunks = chunk_markdown(content, source=source)
            if new_chunks:
                self.index.append_chunks(new_chunks, self.client)
            return f"일별 로그({date_str})에 저장됨 ({len(content)}자)"

        return f"알 수 없는 대상: {target}. 'memory' 또는 'daily' 사용."

    def end_session(self, messages: list[dict]) -> None:
        """세션 종료 시 호출. 대화 요약을 일별 로그에 기록."""
        turns: list[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                preview = content[:200]
                if len(content) > 200:
                    preview += "..."
                turns.append(f"- **{role}**: {preview}")

        if not turns:
            return

        summary = f"### 세션 요약 ({len(turns)}턴)\n" + "\n".join(turns)
        append_to_daily_log(summary)

        date_str = datetime.now().strftime("%Y-%m-%d")
        source = f"{date_str}.md"
        new_chunks = chunk_markdown(summary, source=source)
        if new_chunks:
            self.index.append_chunks(new_chunks, self.client)

        logger.info("세션 요약 저장: %d턴", len(turns))

    def close(self) -> None:
        """리소스 정리."""
        self.index.close()
