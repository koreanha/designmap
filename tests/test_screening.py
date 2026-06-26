from src.models import DesignPatent
from src.models.design_patent import PatentOffice
from src.screening.screener import DesignScreener


def test_rule_based_locarno_mismatch():
    screener = DesignScreener(target_locarno=["14-03"])
    patent = DesignPatent(
        application_number="TEST-001",
        patent_office=PatentOffice.KIPO,
        title="의자",
        locarno_class="06-01",
    )
    patent.id = "TEST-001"
    result = screener.rule_based_screen(patent)
    assert result is not None
    assert not result.passed
    assert "로카르노 분류 불일치" in result.reason


def test_rule_based_exclude_keyword():
    screener = DesignScreener(
        target_locarno=["14-03"],
        exclude_keywords=["케이블"],
    )
    patent = DesignPatent(
        application_number="TEST-002",
        patent_office=PatentOffice.KIPO,
        title="충전용 케이블",
        locarno_class="14-03",
    )
    patent.id = "TEST-002"
    result = screener.rule_based_screen(patent)
    assert result is not None
    assert not result.passed


def test_rule_based_pass():
    screener = DesignScreener(
        target_locarno=["14-03"],
        target_keywords=["스마트폰"],
    )
    patent = DesignPatent(
        application_number="TEST-003",
        patent_office=PatentOffice.KIPO,
        title="스마트폰",
        locarno_class="14-03",
    )
    patent.id = "TEST-003"
    result = screener.rule_based_screen(patent)
    assert result is not None
    assert result.passed


def test_rule_based_uncertain():
    screener = DesignScreener(
        target_locarno=["14-03"],
        target_keywords=["태블릿"],
    )
    patent = DesignPatent(
        application_number="TEST-004",
        patent_office=PatentOffice.KIPO,
        title="전자기기",
        locarno_class="14-03",
    )
    patent.id = "TEST-004"
    result = screener.rule_based_screen(patent)
    assert result is None  # AI 스크리닝 필요
