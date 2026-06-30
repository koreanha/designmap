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


def friendly_api_error(exc: Exception) -> str | None:
    """Anthropic API 오류를 비전공자용 한글 안내로 변환. 해당 없으면 None."""
    msg = str(exc).lower()
    if "credit balance is too low" in msg or "plans & billing" in msg or "billing" in msg:
        return (
            "Claude AI 사용 크레딧(잔액)이 부족합니다.\n"
            "AI를 쓰는 단계(propose/classify/report)는 Claude 유료 API를 사용합니다.\n"
            "해결: https://console.anthropic.com 접속 → 왼쪽 'Plans & Billing'(또는 Billing) →\n"
            "      결제수단 등록 후 크레딧 구매(보통 소액으로 충분) → 다시 실행하세요."
        )
    if "invalid x-api-key" in msg or "authentication" in msg or "401" in msg:
        return (
            "AI 열쇠(ANTHROPIC_API_KEY)가 올바르지 않습니다.\n"
            "console.anthropic.com 에서 키를 다시 발급받아 등록하세요 (sk-ant-... 로 시작)."
        )
    if "rate limit" in msg or "429" in msg:
        return "Claude API 요청이 일시적으로 많습니다(rate limit). 잠시 후 다시 시도하세요."
    return None
