"""디자인 로드맵 분석 및 트렌드 예측 모듈."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

import anthropic

from src.models import ClassificationResult, DesignPatent, ClassificationCriteria


class DesignRoadmapAnalyzer:
    def __init__(self):
        self.client = anthropic.Anthropic()

    def compute_statistics(
        self,
        patents: list[DesignPatent],
        results: list[ClassificationResult],
    ) -> dict:
        """분류 결과 기반 통계 산출"""
        result_map = {r.patent_id: r for r in results}

        category_counts = Counter()
        trend_counts = Counter()
        feature_counts = Counter()
        yearly_categories: dict[int, Counter] = defaultdict(Counter)
        office_categories: dict[str, Counter] = defaultdict(Counter)

        for p in patents:
            r = result_map.get(p.id or p.application_number)
            if not r:
                continue

            category_counts[r.primary_category] += 1
            trend_counts.update(r.trend_tags)
            feature_counts.update(r.design_features)
            office_categories[p.patent_office.value][r.primary_category] += 1

            year = None
            for d in [p.filing_date, p.publication_date, p.registration_date]:
                if d:
                    year = d.year
                    break
            if year:
                yearly_categories[year][r.primary_category] += 1

        return {
            "total_patents": len(patents),
            "classified": len(results),
            "category_distribution": dict(category_counts.most_common()),
            "top_trends": dict(trend_counts.most_common(20)),
            "top_features": dict(feature_counts.most_common(20)),
            "yearly_trends": {
                y: dict(c.most_common()) for y, c in sorted(yearly_categories.items())
            },
            "by_office": {
                o: dict(c.most_common()) for o, c in office_categories.items()
            },
        }

    async def generate_trend_report(
        self,
        statistics: dict,
        criteria: ClassificationCriteria,
        domain_context: str | None = None,
    ) -> str:
        """AI 기반 디자인 트렌드 예측 리포트 생성"""
        prompt = f"""디자인 로드맵 분석 전문가로서 아래 분류 통계를 기반으로 디자인 트렌드 예측 리포트를 작성해주세요.

## 분류 기준
{criteria.name}: {criteria.description}

## 통계 데이터
{json.dumps(statistics, ensure_ascii=False, indent=2)}

## PEST 요인
{json.dumps([f.model_dump() for f in criteria.pest_factors], ensure_ascii=False, indent=2) if criteria.pest_factors else '없음'}

{f'## 도메인 컨텍스트{chr(10)}{domain_context}' if domain_context else ''}

## 리포트 구성
1. **현황 요약**: 전체 디자인 분포 및 주요 카테고리 분석
2. **연도별 트렌드**: 시간에 따른 디자인 변화 흐름
3. **지역별 특성**: 국가/지역별 디자인 특성 차이
4. **주요 디자인 특징**: 빈도 높은 디자인 요소 분석
5. **미래 트렌드 예측**: PEST 분석 기반 향후 3-5년 디자인 방향 예측
6. **전략적 시사점**: 디자인 개발 방향 제안

한국어로 작성해주세요."""

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text
