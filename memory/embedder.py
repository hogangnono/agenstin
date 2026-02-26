"""Ollama 임베딩 API 래퍼 — graceful fallback 포함"""

import logging
import math

import ollama

import config

logger = logging.getLogger("agenstin.memory.embedder")

# 모듈 레벨 캐시: 모델 사용 가능 여부
_model_available: bool | None = None


def is_available(client: ollama.Client | None = None) -> bool:
    """임베딩 모델이 사용 가능한지 확인 (첫 호출 시 캐시)."""
    global _model_available
    if _model_available is not None:
        return _model_available

    if client is None:
        client = ollama.Client(host=config.OLLAMA_HOST)

    try:
        client.embed(model=config.EMBED_MODEL, input="test")
        _model_available = True
    except Exception as e:
        logger.warning(
            "임베딩 모델 '%s' 사용 불가: %s — BM25 전용 모드로 동작합니다. "
            "'ollama pull %s' 로 설치하세요.",
            config.EMBED_MODEL, e, config.EMBED_MODEL,
        )
        _model_available = False

    return _model_available


def embed_texts(
    texts: list[str],
    client: ollama.Client | None = None,
) -> list[list[float]] | None:
    """텍스트 리스트를 임베딩 벡터로 변환.

    Returns:
        각 텍스트의 임베딩 벡터 리스트. 모델 불가 시 None.
    """
    if not texts:
        return []

    if client is None:
        client = ollama.Client(host=config.OLLAMA_HOST)

    if not is_available(client):
        return None

    try:
        response = client.embed(model=config.EMBED_MODEL, input=texts)
        return [list(e) for e in response.embeddings]
    except Exception as e:
        logger.error("임베딩 실패: %s", e)
        return None


def embed_text(
    text: str,
    client: ollama.Client | None = None,
) -> list[float] | None:
    """단일 텍스트 임베딩."""
    results = embed_texts([text], client)
    if results is None or not results:
        return None
    return results[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """코사인 유사도 계산 (pure Python)."""
    if len(a) != len(b) or not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
