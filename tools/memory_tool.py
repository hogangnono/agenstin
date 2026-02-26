"""메모리 도구 — memory_search, memory_save

에이전트가 직접 호출하여 기억을 검색하고 저장하는 도구.
MemoryManager 인스턴스를 생성 시 주입받습니다.
"""

from memory.manager import MemoryManager
from tools.base import Tool


class MemorySearchTool(Tool):
    """메모리 검색 도구 — 벡터 + BM25 하이브리드 검색"""

    def __init__(self, memory_manager: MemoryManager):
        self._mm = memory_manager

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "과거 대화, 기억, 사용자 선호 등을 검색합니다. "
            "이전에 무엇을 이야기했는지, 사용자가 어떤 것을 좋아하는지, "
            "이전 실패 경험 등을 찾을 때 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리 (예: '사용자가 선호하는 언어', '어제 작업 내용')",
                },
                "top_k": {
                    "type": "integer",
                    "description": "반환할 최대 결과 수 (기본: 5)",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        if not query:
            return "query가 필요합니다."

        top_k = kwargs.get("top_k", 5)
        if not isinstance(top_k, int) or top_k < 1:
            top_k = 5

        results = self._mm.search(query, top_k=top_k)

        if not results:
            return f"'{query}'에 대한 기억을 찾지 못했습니다."

        lines = [f"'{query}' 검색 결과 ({len(results)}건):\n"]
        for i, r in enumerate(results, 1):
            source = r["source"]
            heading = r.get("heading", "")
            text = r["text"]
            if len(text) > 300:
                text = text[:297] + "..."

            header = f"{i}. [{source}]"
            if heading:
                header += f" {heading}"
            header += f" (관련도: {r['score']:.2f})"

            lines.append(header)
            lines.append(f"   {text}")
            lines.append("")

        return "\n".join(lines)


class MemorySaveTool(Tool):
    """기억 저장 도구 — MEMORY.md 또는 일별 로그에 저장"""

    def __init__(self, memory_manager: MemoryManager):
        self._mm = memory_manager

    @property
    def name(self) -> str:
        return "memory_save"

    @property
    def description(self) -> str:
        return (
            "중요한 정보를 장기 기억에 저장합니다. "
            "사용자의 선호도, 프로젝트 정보, 중요한 결정사항 등을 "
            "나중에 참고할 수 있도록 기록할 때 사용하세요. "
            "사용자가 '기억해', 'remember this' 등을 말하면 반드시 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "저장할 내용 (마크다운 형식 권장)",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "daily"],
                    "description": "저장 대상: 'memory'=장기 기억(MEMORY.md), 'daily'=일별 로그 (기본: memory)",
                },
            },
            "required": ["content"],
        }

    def execute(self, **kwargs) -> str:
        content = kwargs.get("content", "")
        if not content:
            return "content가 필요합니다."

        target = kwargs.get("target", "memory")
        return self._mm.save(content, target=target)
