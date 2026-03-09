"""마크다운 파일 기반 메모리 시스템

- SOUL.md: 에이전트 성격 (사용자 편집 가능)
- MEMORY.md: 장기 기억
- memory/YYYY-MM-DD.md: 일별 세션 로그
"""

from memory.manager import MemoryManager

__all__ = ["MemoryManager"]
