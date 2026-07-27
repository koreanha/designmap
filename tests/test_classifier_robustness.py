"""분류기 응답 파싱 견고성 테스트 (가짜 API 클라이언트 사용)."""
import asyncio
from types import SimpleNamespace

from src.classifier.design_classifier import DesignClassifier
from src.models import ClassificationCriteria, CriterionDimension, DesignPatent
from src.models.design_patent import PatentOffice


def make_criteria():
    return ClassificationCriteria(
        name="테스트 기준", description="설명", locarno_scope=["12"],
        dimensions=[CriterionDimension(name="형태", description="전체 형태",
                                       values=["직선형", "곡선형"], weight=1.0)],
        trend_keywords=["자동화"], status="approved",
    )


def make_patent():
    p = DesignPatent(application_number="A1", patent_office=PatentOffice.JPO,
                     title="Transfer robot", locarno_class="12-05")
    p.id = "JPO-A1"
    return p


class FakeClient:
    """text 응답 또는 tool_use 응답을 흉내내는 가짜 클라이언트."""

    def __init__(self, text=None, tool_input=None, stop_reason="end_turn", raise_exc=None):
        self._text, self._tool = text, tool_input
        self._stop, self._exc = stop_reason, raise_exc
        self.messages = self

    def create(self, **kw):
        if self._exc:
            raise self._exc
        self.last_kwargs = kw
        if self._tool is not None:
            blocks = [SimpleNamespace(type="tool_use", name="record_classification",
                                      input=self._tool)]
        else:
            blocks = [SimpleNamespace(type="text", text=self._text)]
        return SimpleNamespace(content=blocks, stop_reason=self._stop)


def classify_with(text=None, **kw):
    c = DesignClassifier.__new__(DesignClassifier)
    c.criteria = make_criteria()
    c.client = FakeClient(text, **kw)
    return asyncio.run(DesignClassifier.classify(c, make_patent()))


def test_normal_json():
    r = classify_with('{"primary_category": "곡선형", "confidence": 0.9, '
                      '"design_features": ["곡면"], "trend_tags": ["자동화"]}')
    assert r.primary_category == "곡선형" and r.confidence == 0.9


def test_code_fence_response():
    r = classify_with('```json\n{"primary_category": "직선형", "confidence": 0.7}\n```')
    assert r.primary_category == "직선형"


def test_trailing_comma():
    r = classify_with('{"primary_category": "곡선형", "confidence": 0.6, }')
    assert r.primary_category == "곡선형"


def test_string_confidence_coerced():
    r = classify_with('{"primary_category": "곡선형", "confidence": "0.85"}')
    assert r.confidence == 0.85


def test_scalar_features_coerced_to_list():
    r = classify_with('{"primary_category": "곡선형", "design_features": "곡면"}')
    assert r.design_features == ["곡면"]


def test_truncated_response_reports_reason():
    r = classify_with('{"primary_category": "곡선", "reasoning": "매우 긴 설명',
                      stop_reason="max_tokens")
    assert r.primary_category == "unclassified"
    assert "잘렸" in r.reasoning


def test_api_error_recorded_not_raised():
    r = classify_with("", raise_exc=RuntimeError("connection dropped"))
    assert r.primary_category == "unclassified"
    assert "AI 호출 실패" in r.reasoning


def test_uses_forced_tool_not_prefill():
    """프리필 미지원 모델 대응: assistant 프리필 없이 도구 강제 호출을 쓴다."""
    c = DesignClassifier.__new__(DesignClassifier)
    c.criteria = make_criteria()
    c.client = FakeClient(tool_input={"primary_category": "곡선형", "confidence": 0.9})
    asyncio.run(DesignClassifier.classify(c, make_patent()))
    kw = c.client.last_kwargs
    # 대화는 반드시 user 메시지로 끝나야 함 (프리필 금지)
    assert all(m["role"] == "user" for m in kw["messages"])
    assert kw["messages"][-1]["role"] == "user"
    assert kw["tool_choice"] == {"type": "tool", "name": "record_classification"}
    assert kw["tools"][0]["name"] == "record_classification"


def test_tool_use_response_parsed():
    r = classify_with(tool_input={
        "primary_category": "곡선형", "confidence": 0.92,
        "reasoning": "곡면 위주", "design_features": ["곡면", "대칭"],
        "trend_tags": ["자동화"],
    })
    assert r.primary_category == "곡선형"
    assert r.confidence == 0.92
    assert r.design_features == ["곡면", "대칭"]


def test_tool_schema_uses_first_dimension_values_as_enum():
    c = DesignClassifier.__new__(DesignClassifier)
    c.criteria = make_criteria()
    schema = DesignClassifier._result_tool(c)["input_schema"]
    assert schema["properties"]["primary_category"]["enum"] == ["직선형", "곡선형"]
