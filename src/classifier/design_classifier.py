"""디자인 분류 에이전트.

확정된 분류 기준을 기반으로 각 디자인권의 도면과 정보를 분석하여 분류합니다.
"""
from __future__ import annotations

import json

from src.models import DesignPatent, ClassificationResult, ClassificationCriteria
from src.utils.ai import get_client, DEFAULT_MODEL
from src.utils.image_loader import load_image_as_base64


class DesignClassifier:
    def __init__(self, criteria: ClassificationCriteria):
        self.criteria = criteria
        self.client = get_client()

    async def classify(self, patent: DesignPatent) -> ClassificationResult:
        content: list[dict] = []

        for drawing in patent.drawings[:6]:
            source = drawing.file_path or drawing.url
            if not source:
                continue
            try:
                b64, mime = await load_image_as_base64(source)
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                })
                content.append({
                    "type": "text",
                    "text": f"[{drawing.drawing_type.value}]",
                })
            except Exception:
                continue

        dim_desc = []
        for d in self.criteria.dimensions:
            dim_desc.append(f"- **{d.name}**: {d.description}\n  가능한 값: {', '.join(d.values)}")

        content.append({
            "type": "text",
            "text": f"""다음 디자인권을 아래 분류 기준에 따라 분류해주세요.

## 디자인권 정보
- 물품명: {patent.title}
- 로카르노 분류: {patent.locarno_class}
- 출원청: {patent.patent_office.value}
- 디자인 설명: {patent.design_description or '없음'}

## 분류 기준: {self.criteria.name}
{self.criteria.description}

### 분류 차원
{chr(10).join(dim_desc)}

### 트렌드 키워드 참조
{', '.join(self.criteria.trend_keywords)}

## 응답 형식 (JSON)
{{
  "primary_category": "주 분류 (첫 번째 차원의 값)",
  "secondary_categories": ["보조 분류들"],
  "confidence": 0.0-1.0,
  "reasoning": "분류 근거 설명",
  "design_features": ["관찰된 디자인 특징들"],
  "trend_tags": ["해당하는 트렌드 태그들"]
}}""",
        })

        response = self.client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )

        text = response.content[0].text
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            return ClassificationResult(
                patent_id=patent.id or patent.application_number,
                primary_category=data["primary_category"],
                secondary_categories=data.get("secondary_categories", []),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", ""),
                design_features=data.get("design_features", []),
                trend_tags=data.get("trend_tags", []),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return ClassificationResult(
                patent_id=patent.id or patent.application_number,
                primary_category="unclassified",
                confidence=0.0,
                reasoning="분류 응답 파싱 실패",
            )

    async def classify_batch(
        self, patents: list[DesignPatent]
    ) -> list[ClassificationResult]:
        results = []
        for patent in patents:
            result = await self.classify(patent)
            results.append(result)
        return results
