"""디자인 분류 에이전트.

확정된 분류 기준을 기반으로 각 디자인권의 도면과 정보를 분석하여 분류합니다.
"""
from __future__ import annotations

from src.models import DesignPatent, ClassificationResult, ClassificationCriteria
from src.utils.ai import get_client, DEFAULT_MODEL, parse_json_response
from src.utils.image_loader import load_image_as_base64


_TOOL_NAME = "record_classification"


class DesignClassifier:
    def __init__(self, criteria: ClassificationCriteria):
        self.criteria = criteria
        self.client = get_client()

    def _result_tool(self) -> dict:
        """분류 결과를 규격대로 받기 위한 도구 정의 (구조화 출력)."""
        primary: dict = {
            "type": "string",
            "description": "주 분류 (첫 번째 분류 차원의 값 중 하나)",
        }
        # 첫 번째 차원의 값들을 선택지로 고정해 표기 흔들림을 방지
        if self.criteria.dimensions and self.criteria.dimensions[0].values:
            primary["enum"] = list(self.criteria.dimensions[0].values)

        return {
            "name": _TOOL_NAME,
            "description": "디자인권 분류 결과를 기록합니다.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "primary_category": primary,
                    "secondary_categories": {
                        "type": "array", "items": {"type": "string"},
                        "description": "다른 차원에서의 분류 값들",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "분류 신뢰도 (0.0~1.0)",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "분류 근거 (2문장 이내)",
                    },
                    "design_features": {
                        "type": "array", "items": {"type": "string"},
                        "description": "도면에서 관찰된 디자인 특징",
                    },
                    "trend_tags": {
                        "type": "array", "items": {"type": "string"},
                        "description": "해당하는 트렌드 키워드",
                    },
                },
                "required": ["primary_category", "confidence", "reasoning"],
            },
        }

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

## 응답 규칙
- 설명 문장 없이 **JSON만** 출력하세요.
- reasoning은 2문장 이내로 간결하게 작성하세요.

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

        pid = patent.id or patent.application_number

        # 구조화 출력(도구 호출)으로 규격에 맞는 결과만 받는다.
        # → 설명문 혼입·코드펜스·JSON 문법 오류로 인한 파싱 실패가 원천 차단됨.
        try:
            response = self.client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=2000,
                tools=[self._result_tool()],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as e:  # API 오류는 해당 건만 실패로 기록 (배치는 계속)
            return ClassificationResult(
                patent_id=pid,
                primary_category="unclassified",
                confidence=0.0,
                reasoning=f"AI 호출 실패: {type(e).__name__}: {str(e)[:300]}",
            )

        data = None
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                data = block.input
                break

        if data is None:
            # 예비 경로: 도구 호출이 없으면 본문에서 JSON 추출 시도
            raw = "".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            )
            truncated = getattr(response, "stop_reason", None) == "max_tokens"
            try:
                data = parse_json_response(raw)
            except Exception:
                reason = "응답이 중간에 잘렸습니다(내용 과다). " if truncated else ""
                return ClassificationResult(
                    patent_id=pid,
                    primary_category="unclassified",
                    confidence=0.0,
                    reasoning=f"{reason}응답 파싱 실패 · 원문 일부: {raw[:300]}",
                )

        category = data.get("primary_category") or data.get("category")
        if not category:
            return ClassificationResult(
                patent_id=pid,
                primary_category="unclassified",
                confidence=0.0,
                reasoning=f"분류값(primary_category) 누락 · 원문 일부: {raw[:300]}",
            )

        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        def _as_list(v):
            if isinstance(v, list):
                return [str(x) for x in v]
            return [str(v)] if v else []

        return ClassificationResult(
            patent_id=pid,
            primary_category=str(category),
            secondary_categories=_as_list(data.get("secondary_categories")),
            confidence=max(0.0, min(1.0, confidence)),
            reasoning=str(data.get("reasoning", "")),
            design_features=_as_list(data.get("design_features")),
            trend_tags=_as_list(data.get("trend_tags")),
        )

    async def classify_batch(self, patents, progress_callback=None) -> list[ClassificationResult]:
        results = []
        total = len(patents)
        for i, patent in enumerate(patents, 1):
            result = await self.classify(patent)
            results.append(result)
            if progress_callback:
                progress_callback(i, total, result)
        return results
