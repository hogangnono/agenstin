"""OpenClaw 방식 메모리 시스템

구성:
- SOUL.md: 에이전트 성격 (매 세션 로드, 사용자 편집 가능)
- MEMORY.md: 장기 기억 (에이전트가 기억할 것을 결정)
- memory/YYYY-MM-DD.md: 일별 세션 로그 (세션 종료 시 자동 저장)
- SQLite 인덱스: 임베딩 벡터 + BM25 하이브리드 검색
"""

from memory.manager import MemoryManager

__all__ = ["MemoryManager"]
