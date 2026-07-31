"""Claude AI 클라이언트 공용 헬퍼.

API 키가 없을 때 비전공자도 이해할 수 있는 안내 메시지를 제공합니다.
"""
from __future__ import annotations

import os
import re

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"

_MISSING_KEY_MESSAGE = (
    "AI 열쇠(ANTHROPIC_API_KEY)가 설정되지 않았습니다. (열쇠는 sk-ant-... 로 시작)\n"
    "• 맥(macOS): 터미널에서\n"
    "    export ANTHROPIC_API_KEY=발급받은열쇠\n"
    "  영구 저장:  echo 'export ANTHROPIC_API_KEY=발급받은열쇠' >> ~/.zshrc && source ~/.zshrc\n"
    "• 윈도우(Windows): 폴더 안의 'AI열쇠_설정.bat'을 더블클릭해 열쇠를 붙여넣거나,\n"
    "  명령 프롬프트에서  setx ANTHROPIC_API_KEY 발급받은열쇠  실행 후 프로그램을 새로 켜세요."
)


class MissingAPIKeyError(RuntimeError):
    """ANTHROPIC_API_KEY가 없을 때 발생"""


def api_key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_client() -> anthropic.Anthropic:
    """Anthropic 클라이언트 반환. 키가 없으면 친절한 오류 발생.

    느린/불안정한 네트워크를 고려해 타임아웃을 넉넉히 주고, 일시적 실패 시
    자동 재시도하도록 설정한다.
    """
    if not api_key_available():
        raise MissingAPIKeyError(_MISSING_KEY_MESSAGE)
    return anthropic.Anthropic(timeout=600.0, max_retries=4)


# 모든 AI 산출물(리포트·분류 근거·기준 등)의 언어 규칙.
# 입력 데이터에 일본어·중국어 공보가 섞여 있어 출력이 그쪽 언어로 끌려가는 것을 방지한다.
KOREAN_OUTPUT_RULE = """
## 출력 언어 규칙 (반드시 지킬 것)
- 모든 서술은 **한국어**로 작성합니다.
- 한자(漢字)·일본어(かな)·중국어 간체자를 **절대 사용하지 마세요**.
  예: '為美'(X) → '기반으로'(O), '據鎳'(X) → '핵심'(O), '334氟'(X) → '334건'(O)
- 영어는 다음 경우에만 허용합니다: 고유명사(회사명·브랜드), 원문 물품명,
  널리 쓰이는 기술 용어. 이때도 가능하면 '한글(영어)' 형태로 씁니다.
  예: 시저 리프트(Scissor Lift), 자율주행 모바일 로봇(AMR)
- 입력 데이터에 일본어·중국어가 있어도, 출력은 한국어로 옮겨 적습니다.
"""

# 한자·가나(한국어 텍스트에 섞이면 안 되는 문자). 한글·영문·숫자는 제외.
_NON_KOREAN_CJK = re.compile("[぀-ヿ㐀-鿿豈-﫿]")


def contains_foreign_cjk(text: str | None) -> bool:
    """한국어 산출물에 한자·가나가 섞였는지 검사 (품질 점검용)."""
    return bool(text and _NON_KOREAN_CJK.search(text))


def parse_json_response(text: str) -> dict:
    """AI 응답 문자열에서 JSON을 최대한 견고하게 추출.

    - ```json ... ``` 코드펜스 제거
    - 첫 '{' ~ 마지막 '}' 구간만 사용
    - 흔한 오류(맨 끝 trailing comma) 보정 시도
    실패 시 json.JSONDecodeError 발생.
    """
    import json
    import re

    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    if "{" in t and "}" in t:
        t = t[t.index("{"): t.rindex("}") + 1]

    candidates = [t, re.sub(r",(\s*[}\]])", r"\1", t)]
    last_err: Exception | None = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
    raise last_err  # type: ignore[misc]


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
    if "timed out" in msg or "timeout" in msg or "connection" in msg or "dropped" in msg:
        return (
            "네트워크가 느리거나 불안정해 요청이 시간 초과됐습니다.\n"
            "- 인터넷 연결 상태를 확인한 뒤 잠시 후 다시 실행해 주세요.\n"
            "- 도면 이미지가 많거나 클수록 업로드가 오래 걸립니다. 가능하면 유선/안정적인 와이파이를 사용하세요.\n"
            "- 프로그램이 자동으로 여러 번 재시도하도록 설정돼 있으니, 한 번 더 실행하면 성공할 수 있습니다."
        )
    return None
