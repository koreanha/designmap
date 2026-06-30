"""Claude AI 클라이언트 공용 헬퍼.

API 키가 없을 때 비전공자도 이해할 수 있는 안내 메시지를 제공합니다.
"""
from __future__ import annotations

import os

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"

_MISSING_KEY_MESSAGE = (
    "AI 열쇠(ANTHROPIC_API_KEY)가 설정되지 않았습니다.\n"
    "터미널에서 아래를 실행한 뒤 다시 시도하세요 (열쇠는 sk-ant-... 로 시작):\n"
    "  export ANTHROPIC_API_KEY=발급받은열쇠\n"
    "영구 저장하려면:  echo 'export ANTHROPIC_API_KEY=발급받은열쇠' >> ~/.zshrc && source ~/.zshrc"
)


class MissingAPIKeyError(RuntimeError):
    """ANTHROPIC_API_KEY가 없을 때 발생"""


def api_key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_client() -> anthropic.Anthropic:
    """Anthropic 클라이언트 반환. 키가 없으면 친절한 오류 발생."""
    if not api_key_available():
        raise MissingAPIKeyError(_MISSING_KEY_MESSAGE)
    return anthropic.Anthropic()
