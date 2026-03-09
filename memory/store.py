"""마크다운 파일 저장소 — SOUL.md, MEMORY.md, 일별 로그"""

from datetime import datetime
from pathlib import Path

import config

DEFAULT_SOUL = """\
# Agenstin

## 성격
- 간결하고 실용적인 한국어 응답
- 기술 용어는 영어 그대로 사용
- 사내(직방/호갱노노) 코드베이스에 대한 지식이 있음
- 도구를 적극적으로 활용하여 정확한 답변 제공

## 원칙
- 모르면 솔직하게 모른다고 말하기
- 추측보다는 도구를 사용해서 확인하기
- 복잡한 문제는 단계별로 분해하기

## 기억 원칙
- 사용자가 "기억해"라고 하면 memory_save를 사용
- 중요한 결정, 선호도, 반복적 실수는 자발적으로 기억
- 과거 대화를 참고해야 할 때 memory_search를 사용
- 사소한 일상 대화는 저장하지 않음

## 사용자 메모
(여기에 사용자가 직접 메모를 추가할 수 있습니다)
"""


def _workspace_dir() -> Path:
    d = config.WORKSPACE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _memory_log_dir() -> Path:
    d = _workspace_dir() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── SOUL.md ──


def load_soul() -> str:
    """SOUL.md 로드. 없으면 기본값으로 생성 후 반환."""
    path = _workspace_dir() / "SOUL.md"
    if not path.exists():
        path.write_text(DEFAULT_SOUL, encoding="utf-8")
    return path.read_text(encoding="utf-8")


# ── MEMORY.md ──


def load_memory() -> str:
    """MEMORY.md 로드. 없으면 빈 기본 구조 생성."""
    path = _workspace_dir() / "MEMORY.md"
    if not path.exists():
        default = "# 장기 기억\n\n(에이전트가 기억할 중요한 사실들)\n"
        path.write_text(default, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def append_to_memory(content: str) -> None:
    """MEMORY.md에 내용 추가."""
    path = _workspace_dir() / "MEMORY.md"
    existing = load_memory()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n## [{timestamp}]\n{content}\n"
    path.write_text(existing + entry, encoding="utf-8")


# ── Daily log ──


def _daily_log_path(date: str | None = None) -> Path:
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return _memory_log_dir() / f"{date}.md"


def load_daily_log(date: str | None = None) -> str:
    """일별 로그 로드. 없으면 빈 문자열."""
    path = _daily_log_path(date)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def append_to_daily_log(content: str, date: str | None = None) -> None:
    """일별 로그에 내용 추가."""
    path = _daily_log_path(date)
    timestamp = datetime.now().strftime("%H:%M")

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if len(existing.encode("utf-8")) > config.DAILY_LOG_MAX_SIZE:
            return
    else:
        date_str = date or datetime.now().strftime("%Y-%m-%d")
        existing = f"# {date_str} 세션 로그\n"

    entry = f"\n## {timestamp}\n{content}\n"
    path.write_text(existing + entry, encoding="utf-8")


def list_daily_logs() -> list[str]:
    """모든 일별 로그 파일의 날짜 목록 반환 (최신순)."""
    log_dir = _memory_log_dir()
    files = sorted(log_dir.glob("*.md"), reverse=True)
    return [f.stem for f in files]
