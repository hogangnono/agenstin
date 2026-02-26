"""마크다운 텍스트를 오버랩 청크로 분할

OpenClaw 방식: ~400 토큰, 80 토큰 오버랩.
토큰 수는 근사치 (문자 수 / CHARS_PER_TOKEN)로 추정.
"""

import re

import config


def chunk_markdown(
    text: str,
    source: str = "",
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[dict]:
    """마크다운 텍스트를 청크 리스트로 분할.

    Args:
        text: 분할할 마크다운 텍스트
        source: 출처 식별자 (예: "MEMORY.md", "2026-02-24.md")
        chunk_size: 청크 크기 (토큰 수 근사치). None이면 config 기본값
        overlap: 오버랩 크기 (토큰 수 근사치). None이면 config 기본값

    Returns:
        [{"text": str, "source": str, "index": int, "heading": str}, ...]
    """
    if not text.strip():
        return []

    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    cpt = config.CHARS_PER_TOKEN

    chunk_chars = chunk_size * cpt
    overlap_chars = overlap * cpt

    # 1단계: 마크다운 헤딩 기준으로 섹션 분리
    sections = _split_by_headings(text)

    # 2단계: 각 섹션을 슬라이딩 윈도우로 청크 분할
    chunks: list[dict] = []
    for heading, section_text in sections:
        section_chunks = _sliding_window(
            section_text, chunk_chars, overlap_chars
        )
        for chunk_text in section_chunks:
            chunks.append({
                "text": chunk_text.strip(),
                "source": source,
                "index": len(chunks),
                "heading": heading,
            })

    return [c for c in chunks if c["text"]]


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """마크다운 헤딩(##) 기준으로 섹션 분리."""
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []

    # 첫 헤딩 이전 텍스트
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        sections.append((heading, section_text))

    return sections


def _sliding_window(
    text: str, chunk_chars: int, overlap_chars: int
) -> list[str]:
    """슬라이딩 윈도우로 텍스트를 오버랩 청크로 분할."""
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        if end >= len(text):
            chunks.append(text[start:])
            break

        # 줄바꿈 경계에서 분할 시도
        newline_pos = text.rfind("\n", start + chunk_chars // 2, end)
        if newline_pos > start:
            end = newline_pos + 1

        chunks.append(text[start:end])
        start = end - overlap_chars

    return chunks
