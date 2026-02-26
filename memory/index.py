"""SQLite 기반 메모리 인덱스 — 벡터 + BM25 하이브리드 검색"""

import logging
import math
import re
import sqlite3
import struct
from collections import Counter
from datetime import datetime
from pathlib import Path

import config
from memory import embedder

logger = logging.getLogger("agenstin.memory.index")


def _pack_vector(vec: list[float]) -> bytes:
    """float 리스트를 바이너리 BLOB으로 변환."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> list[float]:
    """바이너리 BLOB을 float 리스트로 복원."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


class MemoryIndex:
    """SQLite 기반 메모리 청크 인덱스.

    검색: 벡터 코사인 유사도 + BM25 키워드 + 시간 감쇠
    """

    def __init__(self, db_path: Path | None = None):
        config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or config.INDEX_DB_PATH
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                heading TEXT DEFAULT '',
                chunk_index INTEGER DEFAULT 0,
                text TEXT NOT NULL,
                embedding BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source
                ON chunks(source);
            CREATE INDEX IF NOT EXISTS idx_chunks_created
                ON chunks(created_at);
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 청크 저장 ──

    def upsert_source(
        self,
        source: str,
        chunks: list[dict],
        client=None,
    ) -> int:
        """특정 소스의 청크를 갱신 (기존 삭제 후 재삽입)."""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        conn.execute("DELETE FROM chunks WHERE source = ?", (source,))

        texts = [c["text"] for c in chunks]
        vectors = embedder.embed_texts(texts, client)

        for i, chunk in enumerate(chunks):
            vec_blob = None
            if vectors and i < len(vectors) and vectors[i]:
                vec_blob = _pack_vector(vectors[i])

            conn.execute(
                """INSERT INTO chunks
                   (source, heading, chunk_index, text, embedding,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk["source"],
                    chunk.get("heading", ""),
                    chunk.get("index", i),
                    chunk["text"],
                    vec_blob,
                    now,
                    now,
                ),
            )

        conn.commit()
        return len(chunks)

    def append_chunks(
        self,
        chunks: list[dict],
        client=None,
    ) -> int:
        """청크를 추가 (삭제 없이). 일별 로그 추가 시 사용."""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        texts = [c["text"] for c in chunks]
        vectors = embedder.embed_texts(texts, client)

        for i, chunk in enumerate(chunks):
            vec_blob = None
            if vectors and i < len(vectors) and vectors[i]:
                vec_blob = _pack_vector(vectors[i])

            conn.execute(
                """INSERT INTO chunks
                   (source, heading, chunk_index, text, embedding,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk["source"],
                    chunk.get("heading", ""),
                    chunk.get("index", i),
                    chunk["text"],
                    vec_blob,
                    now,
                    now,
                ),
            )

        conn.commit()
        return len(chunks)

    def count(self, source: str | None = None) -> int:
        """청크 수 조회."""
        conn = self._get_conn()
        if source:
            row = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return row[0]

    # ── 검색 ──

    def search(
        self,
        query: str,
        top_k: int | None = None,
        vector_weight: float | None = None,
        bm25_weight: float | None = None,
        client=None,
    ) -> list[dict]:
        """하이브리드 검색: 벡터 + BM25 + 시간 감쇠."""
        top_k = top_k or config.SEARCH_TOP_K
        vector_weight = vector_weight if vector_weight is not None else config.SEARCH_VECTOR_WEIGHT
        bm25_weight = bm25_weight if bm25_weight is not None else config.SEARCH_BM25_WEIGHT

        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, source, heading, text, embedding, created_at "
            "FROM chunks"
        ).fetchall()

        if not rows:
            return []

        # 쿼리 임베딩
        query_vec = embedder.embed_text(query, client)

        # BM25 준비
        query_tokens = _tokenize(query)
        doc_count = len(rows)
        doc_freq = _compute_doc_freq(rows)
        avg_dl = sum(len(_tokenize(r["text"])) for r in rows) / doc_count

        scored: list[dict] = []
        for row in rows:
            # 벡터 유사도
            vec_score = 0.0
            if query_vec and row["embedding"]:
                doc_vec = _unpack_vector(row["embedding"])
                vec_score = max(0.0, embedder.cosine_similarity(query_vec, doc_vec))

            # BM25
            bm25_score = _bm25_score(
                query_tokens, row["text"], doc_freq, doc_count, avg_dl
            )

            # 시간 감쇠
            decay = _temporal_decay(row["created_at"])

            # 가중 합산
            raw_score = vector_weight * vec_score + bm25_weight * bm25_score
            final_score = raw_score * decay

            scored.append({
                "text": row["text"],
                "source": row["source"],
                "heading": row["heading"],
                "score": final_score,
                "created_at": row["created_at"],
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


# ── BM25 구현 ──

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """간단한 토크나이저: 단어 + 한글."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _compute_doc_freq(rows) -> dict[str, int]:
    """각 토큰의 문서 빈도(DF) 계산."""
    df: dict[str, int] = {}
    for row in rows:
        for token in set(_tokenize(row["text"])):
            df[token] = df.get(token, 0) + 1
    return df


def _bm25_score(
    query_tokens: list[str],
    doc_text: str,
    doc_freq: dict[str, int],
    doc_count: int,
    avg_dl: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """단일 문서에 대한 BM25 스코어 계산."""
    doc_tokens = _tokenize(doc_text)
    dl = len(doc_tokens)
    if dl == 0:
        return 0.0

    tf = Counter(doc_tokens)
    score = 0.0

    for token in query_tokens:
        if token not in tf:
            continue
        n = doc_freq.get(token, 0)
        idf = math.log((doc_count - n + 0.5) / (n + 0.5) + 1)
        tf_val = tf[token]
        tf_norm = (tf_val * (k1 + 1)) / (
            tf_val + k1 * (1 - b + b * dl / avg_dl)
        )
        score += idf * tf_norm

    # 0~1 정규화
    if score > 0:
        max_possible = len(query_tokens) * math.log(doc_count + 1) * (k1 + 1)
        score = min(score / max(max_possible, 1), 1.0)

    return score


# ── 시간 감쇠 ──


def _temporal_decay(created_at: str) -> float:
    """시간 감쇠: 0.5^(age_days / half_life)"""
    try:
        created = datetime.fromisoformat(created_at)
        age_days = (datetime.now() - created).total_seconds() / 86400
    except (ValueError, TypeError):
        age_days = 0

    half_life = config.SEARCH_DECAY_HALF_LIFE_DAYS
    return 0.5 ** (age_days / half_life)
