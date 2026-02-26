"""웹 검색 도구 — Google + Naver

Google: googlesearch-python (API 키 불필요)
Naver: 네이버 Open API (client_id/secret 필요, developers.naver.com에서 발급)
"""

import requests
from googlesearch import search as google_search

import config
from tools.base import Tool


class GoogleSearchTool(Tool):
    @property
    def name(self) -> str:
        return "google_search"

    @property
    def description(self) -> str:
        return (
            "Google로 웹 검색을 수행합니다. "
            "영어/글로벌 정보, 기술 문서, 오픈소스 등을 검색할 때 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        if not query:
            return "query가 필요합니다."

        try:
            results = list(
                google_search(
                    query,
                    num_results=config.SEARCH_MAX_RESULTS,
                    lang="ko",
                    advanced=True,
                )
            )
        except Exception as e:
            return f"Google 검색 오류: {e}"

        if not results:
            return f"'{query}'에 대한 Google 검색 결과가 없습니다."

        lines = [f"🔍 Google '{query}' 검색 결과:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            if r.description:
                lines.append(f"   {r.description[:200]}")
            lines.append(f"   🔗 {r.url}")
            lines.append("")

        return "\n".join(lines)


class NaverSearchTool(Tool):
    @property
    def name(self) -> str:
        return "naver_search"

    @property
    def description(self) -> str:
        return (
            "네이버로 웹 검색을 수행합니다. "
            "한국어 정보, 국내 뉴스, 블로그, 카페 등을 검색할 때 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["webkr", "blog", "news"],
                    "description": "검색 유형: webkr=웹, blog=블로그, news=뉴스 (기본: webkr)",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        if not query:
            return "query가 필요합니다."

        if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
            return (
                "네이버 API 키가 설정되지 않았습니다.\n"
                "config.py에서 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 설정하세요.\n"
                "발급: https://developers.naver.com > 애플리케이션 등록 > 검색 API"
            )

        search_type = kwargs.get("search_type", "webkr")
        if search_type not in ("webkr", "blog", "news"):
            search_type = "webkr"

        try:
            resp = requests.get(
                f"https://openapi.naver.com/v1/search/{search_type}.json",
                params={
                    "query": query,
                    "display": config.SEARCH_MAX_RESULTS,
                },
                headers={
                    "X-Naver-Client-Id": config.NAVER_CLIENT_ID,
                    "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"네이버 검색 오류: {e}"

        items = data.get("items", [])
        if not items:
            return f"'{query}'에 대한 네이버 검색 결과가 없습니다."

        type_label = {"webkr": "웹", "blog": "블로그", "news": "뉴스"}
        lines = [
            f"🔍 네이버 {type_label.get(search_type, '웹')} "
            f"'{query}' 검색 결과:\n"
        ]

        for i, item in enumerate(items, 1):
            title = _strip_html(item.get("title", "제목 없음"))
            desc = _strip_html(item.get("description", ""))
            link = item.get("link", "")

            lines.append(f"{i}. **{title}**")
            if desc:
                lines.append(f"   {desc[:200]}")
            if link:
                lines.append(f"   🔗 {link}")
            lines.append("")

        return "\n".join(lines)


def _strip_html(text: str) -> str:
    """네이버 API 응답의 <b>, </b> 등 HTML 태그 제거"""
    import re
    return re.sub(r"<[^>]+>", "", text)
