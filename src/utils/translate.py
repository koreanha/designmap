"""물품명·출원인 영문 통일용 번역 유틸.

일본어(한자·가나)·중국어 등 CJK 문자가 포함된 값을
Claude API로 일괄 번역한다. 한 번의 호출로 여러 건을 묶어
처리해 비용을 최소화한다.
"""
from __future__ import annotations

import json
import re

from src.utils.ai import get_client

# 가나(U+3040-30FF) + 한자(U+3400-9FFF, U+F900-FAFF).
# 한글(U+AC00-D7A3)은 포함하지 않는다 — 코드포인트로 명시해 오인 방지.
_CJK = re.compile("[぀-ヿ㐀-鿿豈-﫿]")

# 일본 공보의 특수문자 표기: ST▲A▼UBLI → STAUBLI (ä 등을 ▲문자▼로 표기)
_JPO_SPECIAL_CHAR = re.compile(r"▲(.)▼")

_PROMPTS = {
    "title": (
        "다음은 디자인 공보의 물품명(제품명)입니다. 각 항목을 간결한 영문 "
        "물품명으로 통일해주세요. 디자인/특허 분야의 통용 표현을 사용하세요.\n"
        "- 스페인어·프랑스어·독일어·폴란드어·이탈리아어 등 어떤 언어든 영어로 옮기세요.\n"
        "  (예: Automóviles → Motor cars, Camiones → Trucks, "
        "Carrocerías de vehículos → Vehicle bodies)\n"
        "- '(parte de -)', '(część - )' 같은 부분 표시는 '(part of -)'로 통일하세요.\n"
        "- **이미 영어인 항목은 원문 그대로 반환**하세요 (바꾸지 마세요)."
    ),
    "applicant": (
        "다음은 디자인 공보의 출원인/권리자(기업·개인) 이름입니다. "
        "각 항목을 공식 영문 표기로 바꿔주세요.\n"
        "- 기업의 공식 영문 사명이 알려져 있으면 그것을 사용하세요 "
        "(예: 山田工業株式会社 → Yamada Kogyo Co., Ltd.)\n"
        "- 카타카나로 음차된 외국 기업명은 원래 영문명으로 복원하세요 "
        "(예: アプライド・エレクトリック・ビークルズ・リミテッド → Applied Electric Vehicles Limited)\n"
        "- 개인 이름은 로마자 표기로 바꾸세요.\n"
        "- 법인격(株式会社→Co., Ltd. / 有限公司→Co., Ltd.)도 영문으로 표기하세요."
    ),
}


def clean_special_chars(text: str | None) -> str | None:
    """일본 공보의 ▲문자▼ 표기를 일반 문자로 복원."""
    if not text:
        return text
    return _JPO_SPECIAL_CHAR.sub(r"\1", text)


def needs_translation(text: str | None) -> bool:
    """CJK 문자가 포함되어 영문 번역이 필요한지 여부 (출원인 등 고유명사용)."""
    return bool(text and _CJK.search(text))


def needs_english_normalization(text: str | None) -> bool:
    """물품명을 영문으로 통일할 필요가 있는지.

    악센트 없는 외국어(Camiones 등)도 있어 문자만으로는 판별할 수 없으므로,
    비어 있지 않은 값은 모두 후보로 보고 AI가 판단하게 한다.
    (이미 영어면 AI가 원문 그대로 돌려주므로 값이 바뀌지 않는다)
    """
    return bool(text and text.strip())


def translate_to_english(
    texts: list[str], kind: str = "title", batch_size: int = 60
) -> dict[str, str]:
    """CJK 값들을 영문으로 일괄 번역. {원문: 영문} 매핑 반환.

    kind: "title"(물품명) 또는 "applicant"(출원인/권리자)
    실패한 배치는 건너뛰고 원문을 유지한다 (오류로 전체가 멈추지 않게).
    """
    # 물품명은 모든 언어를 영문으로 통일, 출원인(고유명사)은 한자·가나만 변환
    check = needs_english_normalization if kind == "title" else needs_translation
    targets = [t for t in dict.fromkeys(texts) if check(t)]
    if not targets:
        return {}

    client = get_client()
    mapping: dict[str, str] = {}
    instruction = _PROMPTS.get(kind, _PROMPTS["title"])

    for i in range(0, len(targets), batch_size):
        batch = targets[i:i + batch_size]
        prompt = (
            f"{instruction}\n"
            "반드시 아래 JSON 형식으로만 응답하세요 (설명 금지):\n"
            '{"translations": [{"original": "원문", "english": "영문"}]}\n\n'
            + json.dumps(batch, ensure_ascii=False)
        )
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
            for item in data.get("translations", []):
                orig, eng = item.get("original"), item.get("english")
                if orig and eng and str(eng).strip():
                    mapping[orig] = str(eng).strip()
        except Exception:
            continue  # 이 배치는 원문 유지

    return mapping
