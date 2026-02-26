"""Tool 기본 인터페이스"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """모든 도구의 기본 클래스

    새 도구를 만들려면:
    1. 이 클래스를 상속
    2. name, description, parameters 정의
    3. execute() 구현
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """도구 이름 (Ollama tool calling에서 사용)"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """도구 설명 (모델이 언제 사용할지 판단하는 근거)"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema 형식의 파라미터 정의"""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """도구 실행. 항상 문자열 결과를 반환."""
        ...

    def to_ollama_tool(self) -> dict:
        """Ollama tool calling API 형식으로 변환"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool(self) -> dict:
        """Anthropic tool calling API 형식으로 변환"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
