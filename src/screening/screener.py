"""1차 스크리닝 모듈.

로카르노 분류, 대상물품명, 디자인의 설명, 각국 세부 디자인분류기호를 기반으로
분석 대상이 되는 디자인권을 선별하여 노이즈를 제거합니다.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.models import DesignPatent, ScreeningResult
from src.utils.ai import get_client, DEFAULT_MODEL
from src.utils.image_loader import load_image_as_base64


class DesignScreener:
    def __init__(
        self,
        target_locarno: list[str],
        target_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        min_confidence: float = 0.7,
        use_ai: bool = True,
    ):
        self.target_locarno = target_locarno
        self.target_keywords = target_keywords or []
        self.exclude_keywords = exclude_keywords or []
        self.min_confidence = min_confidence
        self.use_ai = use_ai
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_client()
        return self._client

    def rule_based_screen(self, patent: DesignPatent) -> ScreeningResult | None:
        """규칙 기반 빠른 스크리닝 (API 호출 없이)"""
        matched = []

        locarno_match = any(
            patent.locarno_class.startswith(lc) for lc in self.target_locarno
        )
        if not locarno_match:
            return ScreeningResult(
                patent_id=patent.id or patent.application_number,
                passed=False,
                confidence=0.95,
                reason=f"로카르노 분류 불일치: {patent.locarno_class}",
            )
        matched.append("locarno_match")

        title_lower = patent.title.lower()
        for kw in self.exclude_keywords:
            if kw.lower() in title_lower:
                return ScreeningResult(
                    patent_id=patent.id or patent.application_number,
                    passed=False,
                    confidence=0.9,
                    reason=f"제외 키워드 매칭: '{kw}' in '{patent.title}'",
                )

        if self.target_keywords:
            kw_match = any(kw.lower() in title_lower for kw in self.target_keywords)
            desc = (patent.design_description or "").lower()
            desc_match = any(kw.lower() in desc for kw in self.target_keywords)
            if kw_match or desc_match:
                matched.append("keyword_match")

        if len(matched) >= 2:
            return ScreeningResult(
                patent_id=patent.id or patent.application_number,
                passed=True,
                confidence=0.85,
                reason="규칙 기반 스크리닝 통과",
                matched_criteria=matched,
            )

        return None

    async def ai_screen(self, patent: DesignPatent) -> ScreeningResult:
        """Claude Vision을 활용한 AI 기반 정밀 스크리닝"""
        content: list[dict] = []

        image_source = None
        rep = patent.representative_drawing
        if rep:
            image_source = rep.file_path or rep.url
        if image_source:
            try:
                b64, mime = await load_image_as_base64(image_source)
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                })
            except Exception:
                pass

        content.append({
            "type": "text",
            "text": f"""다음 디자인권이 분석 대상으로 적합한지 스크리닝해주세요.

## 디자인권 정보
- 물품명: {patent.title}
- 로카르노 분류: {patent.locarno_class}
- 출원청: {patent.patent_office.value}
- 디자인 설명: {patent.design_description or '없음'}
- 세부 분류기호: {', '.join(patent.local_class_codes) or '없음'}

## 분석 대상 기준
- 대상 로카르노: {', '.join(self.target_locarno)}
- 관련 키워드: {', '.join(self.target_keywords) if self.target_keywords else '미지정'}
- 제외 키워드: {', '.join(self.exclude_keywords) if self.exclude_keywords else '미지정'}

## 판단 기준
1. 로카르노 분류가 대상 범위에 해당하는지
2. 물품명과 디자인 설명이 분석 주제와 관련있는지
3. 도면이 제공된 경우, 외관 디자인이 분석 대상 유형에 부합하는지
4. 제외 키워드에 해당하지 않는지

JSON으로 응답해주세요:
{{"passed": true/false, "confidence": 0.0-1.0, "reason": "판단 이유", "matched_criteria": ["매칭된 기준들"]}}""",
        })

        response = self.client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": content}],
        )

        try:
            text = response.content[0].text
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            return ScreeningResult(
                patent_id=patent.id or patent.application_number,
                passed=data["passed"],
                confidence=data.get("confidence", 0.5),
                reason=data.get("reason", ""),
                matched_criteria=data.get("matched_criteria", []),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return ScreeningResult(
                patent_id=patent.id or patent.application_number,
                passed=False,
                confidence=0.3,
                reason="AI 스크리닝 응답 파싱 실패",
            )

    def _rule_only_decision(self, patent: DesignPatent) -> ScreeningResult:
        """AI를 쓰지 않을 때의 최종 판정.

        로카르노가 일치하고 제외 키워드에 걸리지 않으면 통과로 간주한다.
        (키워드 일치 여부는 확신을 높이는 용도일 뿐, 누락돼도 통과시킨다)
        """
        kw_matched = False
        if self.target_keywords:
            title = patent.title.lower()
            desc = (patent.design_description or "").lower()
            kw_matched = any(
                kw.lower() in title or kw.lower() in desc for kw in self.target_keywords
            )
        return ScreeningResult(
            patent_id=patent.id or patent.application_number,
            passed=True,
            confidence=0.7 if kw_matched else 0.6,
            reason="규칙 기반 통과 (로카르노 일치, 제외 키워드 없음)",
            matched_criteria=["locarno_match"] + (["keyword_match"] if kw_matched else []),
        )

    async def screen(self, patent: DesignPatent) -> ScreeningResult:
        """규칙 기반 → (AI) 순서로 스크리닝"""
        result = self.rule_based_screen(patent)
        if result and result.confidence >= self.min_confidence:
            return result
        if not self.use_ai:
            # 규칙으로 확정 못 한 경우: 로카르노 불일치/제외는 rule_based가 이미 처리했으므로
            # 여기 오는 건 "통과 후보"다.
            if result is not None and not result.passed:
                return result
            return self._rule_only_decision(patent)
        return await self.ai_screen(patent)

    async def screen_batch(self, patents: list[DesignPatent]) -> list[ScreeningResult]:
        results = []
        for patent in patents:
            result = await self.screen(patent)
            results.append(result)
        return results
