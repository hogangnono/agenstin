"""브라우저 도구 — Playwright 기반 읽기 전용 웹 브라우징"""

from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import config
from tools.base import Tool


def _is_blocked_url(url: str) -> bool:
    """URL blacklist 검사"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        return True

    for pattern in config.BROWSER_URL_BLACKLIST:
        if pattern in host:
            return True
    return False


def _ensure_screenshot_dir() -> Path:
    d = Path(config.BROWSER_SCREENSHOT_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


class BrowseWebTool(Tool):
    @property
    def name(self) -> str:
        return "browse_web"

    @property
    def description(self) -> str:
        return (
            "웹페이지에 접속하여 텍스트 내용을 가져옵니다. "
            "검색 결과의 URL을 직접 방문하여 상세 내용을 확인할 때 사용하세요."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "방문할 웹페이지 URL (예: 'https://example.com')",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs) -> str:
        url = kwargs.get("url", "")
        if not url:
            return "url이 필요합니다."

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if _is_blocked_url(url):
            return f"⛔ 차단된 URL: {url} (내부 네트워크 접근 불가)"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=config.BROWSER_TIMEOUT)
                page.wait_for_load_state("domcontentloaded")

                text = page.inner_text("body")
                title = page.title()

                browser.close()
        except Exception as e:
            return f"브라우저 오류: {e}"

        if len(text) > config.BROWSER_MAX_TEXT_LENGTH:
            text = text[: config.BROWSER_MAX_TEXT_LENGTH] + "\n... (내용 잘림)"

        return f"🌐 {title}\n📍 {url}\n\n{text}"


class ScreenshotTool(Tool):
    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return "웹페이지의 스크린샷을 캡처하여 파일로 저장합니다."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "캡처할 웹페이지 URL",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs) -> str:
        url = kwargs.get("url", "")
        if not url:
            return "url이 필요합니다."

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if _is_blocked_url(url):
            return f"⛔ 차단된 URL: {url}"

        screenshot_dir = _ensure_screenshot_dir()
        # URL에서 파일명 생성
        parsed = urlparse(url)
        safe_name = (parsed.hostname or "page").replace(".", "_")

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name}_{timestamp}.png"
        filepath = screenshot_dir / filename

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=config.BROWSER_TIMEOUT)
                page.wait_for_load_state("domcontentloaded")
                page.screenshot(path=str(filepath), full_page=True)

                title = page.title()
                browser.close()
        except Exception as e:
            return f"스크린샷 오류: {e}"

        return f"📸 스크린샷 저장: {filepath}\n🌐 {title}\n📍 {url}"
