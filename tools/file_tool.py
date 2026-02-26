"""파일 관련 도구 — read_file, list_files"""

import os
from pathlib import Path

import config
from tools.base import Tool


def _resolve_and_validate(path_str: str) -> Path:
    """경로를 절대경로로 변환하고 whitelist 검증"""
    path = Path(path_str).expanduser().resolve()

    allowed = [Path(p).expanduser().resolve() for p in config.PATH_WHITELIST]
    if not any(path == a or a in path.parents for a in allowed):
        raise PermissionError(
            f"접근 불가 경로: {path}\n"
            f"허용 경로: {', '.join(config.PATH_WHITELIST)}"
        )
    return path


class ListFilesTool(Tool):
    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return "디렉토리의 파일/폴더 목록을 반환합니다. 현재 디렉토리를 보려면 path에 '.'을 전달하세요."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "조회할 디렉토리 경로 (예: '.', '~/Projects')",
                },
            },
            "required": ["path"],
        }

    def execute(self, **kwargs) -> str:
        path_str = kwargs.get("path", ".")
        # '.' 은 현재 작업 디렉토리로 해석
        if path_str == ".":
            path = Path.cwd()
        else:
            path = _resolve_and_validate(path_str)

        if not path.exists():
            return f"경로가 존재하지 않습니다: {path}"
        if not path.is_dir():
            return f"디렉토리가 아닙니다: {path}"

        entries = sorted(path.iterdir())
        lines = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            prefix = "📁 " if entry.is_dir() else "📄 "
            size = ""
            if entry.is_file():
                s = entry.stat().st_size
                if s < 1024:
                    size = f" ({s}B)"
                elif s < 1024 * 1024:
                    size = f" ({s // 1024}KB)"
                else:
                    size = f" ({s // (1024 * 1024)}MB)"
            lines.append(f"{prefix}{entry.name}{size}")

        if not lines:
            return f"{path}: 빈 디렉토리"
        return f"{path}:\n" + "\n".join(lines)


class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "파일 내용을 읽어서 반환합니다. 텍스트 파일만 지원합니다."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "읽을 파일 경로",
                },
            },
            "required": ["path"],
        }

    def execute(self, **kwargs) -> str:
        path_str = kwargs.get("path", "")
        if not path_str:
            return "path가 필요합니다."

        path = _resolve_and_validate(path_str)

        if not path.exists():
            return f"파일이 존재하지 않습니다: {path}"
        if not path.is_file():
            return f"파일이 아닙니다: {path}"

        size = path.stat().st_size
        if size > config.MAX_FILE_READ_SIZE:
            return (
                f"파일이 너무 큽니다: {size:,}B "
                f"(최대 {config.MAX_FILE_READ_SIZE:,}B)"
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"텍스트 파일이 아닙니다 (바이너리): {path}"

        return f"=== {path} ===\n{content}"
