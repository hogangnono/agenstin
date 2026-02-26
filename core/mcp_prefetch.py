"""MCP 선조회 — 사내 관련 질문 감지 시 Codex를 자동으로 먼저 조회

모델이 33개 도구에서 올바른 MCP 도구를 선택하기 어려우므로,
코드 레벨에서 키워드를 감지하여 적절한 MCP 도구를 자동 호출하고
그 결과를 컨텍스트로 주입합니다.

전략:
- askCodebase 를 주력으로 사용 (자연어 질문 → 관련 코드 반환)
- 특수 케이스(API, 레포 구조 등)만 전용 도구 호출
- 결과는 핵심만 추출하여 토큰 낭비 방지
"""

import json
import re
import time

from rich.console import Console

import config
from tools.base import Tool

console = Console()

# ──────────────────────────────────────────────
# 키워드 매칭 규칙
# ──────────────────────────────────────────────

_COMPANY_KEYWORDS = [
    "직방", "zigbang", "호갱노노", "hogangnono",
    "apt", "io-api", "io-push", "partners-api", "account",
    "ceo-client", "zigbang-client",
    "우리 코드", "우리 서비스", "우리 API", "우리 레포",
    "사내", "회사", "내부 API", "내부 서비스",
]

_API_KEYWORDS = ["api", "엔드포인트", "endpoint", "라우트", "route"]
_REPO_KEYWORDS = ["레포", "repo", "리포지토리", "repository", "프로젝트 구조"]
_DOMAIN_KEYWORDS = ["도메인", "domain", "비즈니스", "기능 목록", "서비스 구조"]

_KNOWN_REPOS = [
    "apt", "io-api", "io-push", "account",
    "ceo-client", "zigbang-client", "partners-apis",
    "hogangnono", "hogangnono-api", "hogangnono-batch", "hogangnono-bot",
]


def _contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _extract_repo_name(text: str) -> str | None:
    text_lower = text.lower()
    for repo in _KNOWN_REPOS:
        if repo in text_lower:
            return repo
    return None


def _extract_topic_keyword(text: str) -> str | None:
    """질문에서 핵심 주제어 추출 (API path 생성 등에 사용)"""
    # 한국어 주제어 → 영어 매핑
    topic_map = {
        "결제": "payment", "페이먼트": "payment",
        "로그인": "login", "인증": "auth", "회원": "user",
        "푸시": "push", "알림": "notification",
        "채팅": "chat", "메시지": "message",
        "쿠폰": "coupon", "할인": "discount",
        "매물": "item", "단지": "complex", "아파트": "apt",
        "계약": "contract", "중개": "agent",
        "검색": "search", "필터": "filter",
        "포인트": "point", "광고": "ads",
        "배치": "batch", "스케줄": "schedule",
    }
    text_lower = text.lower()
    for ko, en in topic_map.items():
        if ko in text_lower or en in text_lower:
            return en
    return None


def should_prefetch(user_input: str) -> bool:
    """이 질문에 MCP 선조회가 필요한지 판단"""
    return _contains_any(user_input, _COMPANY_KEYWORDS)


def run_prefetch(user_input: str, mcp_tools: dict[str, Tool]) -> str | None:
    """사내 관련 질문에 대해 MCP 자동 조회 → 정제된 컨텍스트 반환"""
    if not mcp_tools:
        return None

    results = []
    repo = _extract_repo_name(user_input)
    topic = _extract_topic_keyword(user_input)

    # 1. API 관련 + 주제어 있음 → findApi (path 패턴 포함)
    if _contains_any(user_input, _API_KEYWORDS) and "codex_findApi" in mcp_tools:
        kwargs = {}
        if repo:
            kwargs["repo"] = repo
        if topic:
            kwargs["path"] = f"*{topic}*"
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            if method.lower() in user_input.lower():
                kwargs["method"] = method
                break

        console.print(
            f"  [magenta]🔎 MCP 선조회:[/] API 검색"
            + (f" (path=*{topic}*)" if topic else "")
        )
        result = _call_tool(mcp_tools["codex_findApi"], kwargs)
        if result:
            summary = _summarize_api_result(result)
            results.append(f"[API 검색 결과]\n{summary}")

    # 2. 레포 구조 질문
    elif _contains_any(user_input, _REPO_KEYWORDS) and repo and "codex_getRepoOverview" in mcp_tools:
        console.print(f"  [magenta]🔎 MCP 선조회:[/] 레포 개요 ({repo})")
        result = _call_tool(mcp_tools["codex_getRepoOverview"], {"repo": repo})
        if result:
            summary = _summarize_json(result, max_length=3000)
            results.append(f"[레포 개요: {repo}]\n{summary}")

    # 3. 도메인 질문
    elif _contains_any(user_input, _DOMAIN_KEYWORDS) and "codex_listDomains" in mcp_tools:
        console.print("  [magenta]🔎 MCP 선조회:[/] 도메인 목록")
        result = _call_tool(mcp_tools["codex_listDomains"], {})
        if result:
            results.append(f"[도메인 목록]\n{result}")

    # 4. 항상 askCodebase로 자연어 질의 (핵심)
    if "codex_askCodebase" in mcp_tools:
        console.print("  [magenta]🔎 MCP 선조회:[/] 코드베이스 질문")
        kwargs = {"question": user_input}
        if repo:
            kwargs["repositoryIds"] = [repo]
        result = _call_tool(mcp_tools["codex_askCodebase"], kwargs)
        if result:
            summary = _summarize_codebase_result(result)
            results.append(f"[코드베이스 조회]\n{summary}")

    if not results:
        return None

    return "\n\n---\n\n".join(results)


def _call_tool(tool: Tool, kwargs: dict) -> str | None:
    """도구 호출 + 타이밍 표시"""
    start = time.time()
    try:
        with console.status(
            f"  [cyan]조회 중: {tool.name}...[/]", spinner="dots"
        ):
            result = tool.execute(**kwargs)
        elapsed = time.time() - start

        if not result or result == "(결과 없음)":
            console.print(f"         [dim]결과 없음 ({elapsed:.1f}s)[/]")
            return None

        char_count = len(result)
        console.print(
            f"         [green]✅[/] [dim]{elapsed:.1f}s — {char_count:,}자 수신[/]"
        )
        return result

    except Exception as e:
        elapsed = time.time() - start
        console.print(f"         [red]❌[/] [dim]{elapsed:.1f}s — {e}[/]")
        return None


# ──────────────────────────────────────────────
# 결과 정제 함수들
# ──────────────────────────────────────────────

def _summarize_api_result(raw: str) -> str:
    """findApi 결과에서 핵심 API 정보만 추출"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _truncate(raw, 3000)

    endpoints = data.get("endpoints", [])
    if not endpoints:
        return "관련 API를 찾지 못했습니다."

    lines = []
    for ep in endpoints[:15]:  # 최대 15개
        method = ep.get("method", "?")
        path = ep.get("path", "?")
        name = ep.get("qualifiedName", "")
        # qualifiedName에서 레포:브랜치: 부분 제거
        short_name = name.split(":")[-1] if ":" in name else name
        lines.append(f"- {method} {path}  ({short_name})")

    total = len(endpoints)
    header = f"총 {total}개 API 발견"
    if total > 15:
        header += f" (상위 15개만 표시)"

    return header + "\n" + "\n".join(lines)


def _summarize_codebase_result(raw: str) -> str:
    """askCodebase 결과에서 관련 심볼/코드 정보 추출"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _truncate(raw, 3000)

    sources = data.get("sources", [])
    if not sources:
        return _truncate(raw, 3000)

    lines = []
    for src in sources[:10]:  # 최대 10개
        symbol = src.get("symbolName", "?")
        qname = src.get("qualifiedName", "")
        kind = src.get("kind", "")
        file_path = src.get("filePath", "")

        # 간결한 위치 정보
        location = file_path.split("/")[-1] if file_path else qname
        lines.append(f"- [{kind}] {symbol}  ({location})")

    return "\n".join(lines)


def _summarize_json(raw: str, max_length: int = 3000) -> str:
    """JSON 결과를 읽기 좋게 정리"""
    try:
        data = json.loads(raw)
        formatted = json.dumps(data, ensure_ascii=False, indent=2)
        return _truncate(formatted, max_length)
    except json.JSONDecodeError:
        return _truncate(raw, max_length)


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n... (잘림)"


# ──────────────────────────────────────────────
# 결과 품질 판단
# ──────────────────────────────────────────────

_LOW_QUALITY_SIGNALS = [
    "찾지 못했습니다", "결과 없음", "관련 API를 찾지 못",
    "검색 결과가 없", "(결과 없음)", "에러", "오류",
]


def is_low_quality(result: str | None) -> bool:
    """MCP 선조회 결과가 실패이거나 품질이 낮은지 판단"""
    if not result:
        return True
    if len(result.strip()) < 50:
        return True
    result_lower = result.lower()
    return any(sig in result_lower for sig in _LOW_QUALITY_SIGNALS)
