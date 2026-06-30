"""분류 기준 제안 모듈.

스크리닝된 디자인권의 도면, 디자인 트렌드, PEST 분석을 기반으로
에이전트가 분류 기준을 제안하고 사용자와 협의하여 확정합니다.
"""
from __future__ import annotations

import json

from src.models import DesignPatent, ClassificationCriteria, CriterionDimension, PESTFactor
from src.models.criteria import PESTCategory
from src.utils.ai import get_client, DEFAULT_MODEL
from src.utils.image_loader import load_image_as_base64


class CriteriaProposer:
    def __init__(self):
        self.client = get_client()

    async def propose_criteria(
        self,
        patents: list[DesignPatent],
        locarno_scope: list[str],
        domain_context: str | None = None,
    ) -> ClassificationCriteria:
        """스크리닝 통과한 디자인들을 분석하여 분류 기준 제안"""

        content: list[dict] = []

        sample = patents[:10]
        image_count = 0
        for p in sample:
            rep = p.representative_drawing
            source = (rep.file_path or rep.url) if rep else None
            if source and image_count < 5:
                try:
                    b64, mime = await load_image_as_base64(source)
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    })
                    content.append({
                        "type": "text",
                        "text": f"[{p.title} | {p.locarno_class} | {p.patent_office.value}]",
                    })
                    image_count += 1
                except Exception:
                    pass

        patent_summaries = []
        for p in patents[:50]:
            patent_summaries.append(
                f"- {p.title} ({p.locarno_class}, {p.patent_office.value}) "
                f"{'[도면있음]' if p.drawings else '[도면없음]'}"
            )

        content.append({
            "type": "text",
            "text": f"""당신은 디자인 로드맵 분석 전문가입니다.
아래 디자인권 데이터를 분석하여 디자인 트렌드 예측을 위한 분류 기준을 제안해주세요.

## 분석 대상
- 로카르노 분류 범위: {', '.join(locarno_scope)}
- 총 {len(patents)}건의 디자인권 (스크리닝 통과)
{chr(10).join(patent_summaries)}

{f'## 도메인 컨텍스트{chr(10)}{domain_context}' if domain_context else ''}

## 요청사항
다음을 포함하는 분류 기준을 JSON으로 제안해주세요:

1. **분류 차원(dimensions)**: 디자인 외관 특성에 따른 분류 축 (예: 형태, 소재감, 컬러 전략, 사용자 인터페이스 요소 등)
   - 각 차원에 대해 가능한 값(values)과 예시(examples) 포함
2. **디자인 트렌드 키워드(trend_keywords)**: 현재 관찰되는 디자인 트렌드
3. **PEST 요인(pest_factors)**: 디자인 트렌드에 영향을 미치는 정치/경제/사회/기술 요인

JSON 형식:
{{
  "name": "분류 기준 이름",
  "description": "분류 기준 설명",
  "dimensions": [
    {{
      "name": "차원명",
      "description": "차원 설명",
      "values": ["값1", "값2", ...],
      "examples": ["예시1", "예시2"],
      "weight": 1.0
    }}
  ],
  "pest_factors": [
    {{
      "category": "political|economic|social|technological",
      "factor": "요인",
      "relevance": "관련성 설명",
      "impact_level": "low|medium|high"
    }}
  ],
  "trend_keywords": ["키워드1", "키워드2", ...]
}}""",
        })

        response = self.client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": content}],
        )

        text = response.content[0].text
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])

        dimensions = [
            CriterionDimension(**d) for d in data.get("dimensions", [])
        ]
        pest_factors = [
            PESTFactor(
                category=PESTCategory(f["category"]),
                factor=f["factor"],
                relevance=f["relevance"],
                impact_level=f.get("impact_level", "medium"),
            )
            for f in data.get("pest_factors", [])
        ]

        return ClassificationCriteria(
            name=data.get("name", "Proposed Criteria"),
            description=data.get("description", ""),
            locarno_scope=locarno_scope,
            dimensions=dimensions,
            pest_factors=pest_factors,
            trend_keywords=data.get("trend_keywords", []),
            status="proposed",
        )

    def format_criteria_for_review(self, criteria: ClassificationCriteria) -> str:
        """사용자 검토를 위해 분류 기준을 읽기 좋게 포맷"""
        lines = [
            f"# 분류 기준 제안: {criteria.name}",
            f"상태: {criteria.status}",
            f"\n## 설명\n{criteria.description}",
            f"\n## 적용 범위 (로카르노): {', '.join(criteria.locarno_scope)}",
            "\n## 분류 차원",
        ]

        for i, dim in enumerate(criteria.dimensions, 1):
            lines.append(f"\n### {i}. {dim.name} (가중치: {dim.weight})")
            lines.append(f"   설명: {dim.description}")
            if dim.values:
                lines.append(f"   분류값: {', '.join(dim.values)}")
            if dim.examples:
                lines.append(f"   예시: {', '.join(dim.examples)}")

        if criteria.pest_factors:
            lines.append("\n## PEST 분석")
            for f in criteria.pest_factors:
                lines.append(f"  [{f.category.value.upper()}] {f.factor} ({f.impact_level})")
                lines.append(f"    → {f.relevance}")

        if criteria.trend_keywords:
            lines.append(f"\n## 트렌드 키워드\n  {', '.join(criteria.trend_keywords)}")

        return "\n".join(lines)
