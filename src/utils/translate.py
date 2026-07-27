"""물품명 영문 통일용 번역 유틸.

일본어(한자·가나)·중국어 등 CJK 문자가 포함된 물품명을
Claude API로 일괄 번역한다. 한 번의 호출로 여러 건을 묶어
처리해 비용을 최소화한다.
"""
from __future__ import annotations

import json
import re

from src.utils.ai import get_client

_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")  # 가나 + 한자


def needs_translation(text: str | None) -> bool:
    """CJK 문자가 포함되어 영문 번역이 필요한지 여부."""
    return bool(text and _CJK.search(text))


def translate_to_english(texts: list[str], batch_size: int = 60) -> dict[str, str]:
    """CJK 물품명들을 영문으로 일괄 번역. {원문: 영문} 매핑 반환.

    실패한 배치는 건너뛰고 원문을 유지한다 (오류로 전체가 멈추지 않게).
    """
    targets = [t for t in dict.fromkeys(texts) if needs_translation(t)]
    if not targets:
        return {}

    client = get_client()
    mapping: dict[str, str] = {}

    for i in range(0, len(targets), batch_size):
        batch = targets[i:i + batch_size]
        prompt = (
            "다음은 디자인 공보의 물품명(제품명)입니다. 각 항목을 간결한 영문 "
            "물품명으로 번역해주세요. 디자인/특허 분야의 통용 표현을 사용하세요.\n"
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
