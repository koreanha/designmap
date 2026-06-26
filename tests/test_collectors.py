"""수집기 모듈 임포트 및 기본 구조 테스트."""
from src.collectors.base import BaseCollector
from src.collectors.kipris import KIPRISCollector
from src.collectors.uspto import USPTOCollector
from src.collectors.euipo import EUIPOCollector
from src.collectors.cnipa import CNIPACollector
from src.collectors.jpo import JPOCollector


def test_all_collectors_inherit_base():
    for cls in [KIPRISCollector, USPTOCollector, EUIPOCollector, CNIPACollector, JPOCollector]:
        assert issubclass(cls, BaseCollector)


def test_uspto_locarno_mapping():
    from src.collectors.uspto import LOCARNO_TO_USPC
    assert LOCARNO_TO_USPC["14"] == "D14"
    assert LOCARNO_TO_USPC["12"] == "D12"


def test_jpo_locarno_mapping():
    from src.collectors.jpo import LOCARNO_TO_DCLASS_JP
    assert LOCARNO_TO_DCLASS_JP["14"] == "H4"
    assert LOCARNO_TO_DCLASS_JP["06"] == "C1"


def test_uspto_parse_empty():
    collector = USPTOCollector()
    result = collector._parse_results({}, "14-03")
    assert result == []


def test_euipo_parse_empty():
    collector = EUIPOCollector()
    result = collector._parse_results({}, "14-03")
    assert result == []


def test_cnipa_parse_empty():
    collector = CNIPACollector()
    result = collector._parse_google_patents({}, "14-03")
    assert result == []


def test_jpo_parse_empty():
    collector = JPOCollector()
    result = collector._parse_results({}, "14-03")
    assert result == []


def test_jpo_parse_date():
    assert JPOCollector._parse_date("20240115") is not None
    assert JPOCollector._parse_date("2024-01-15") is not None
    assert JPOCollector._parse_date(None) is None
    assert JPOCollector._parse_date("bad") is None


def test_uspto_parse_results_with_data():
    collector = USPTOCollector()
    data = {
        "designs": [
            {
                "patent_number": "D1000001",
                "patent_title": "Smartphone case",
                "patent_date": "2024-01-15",
                "assignees": [{"assignee_organization": "Apple Inc."}],
                "inventors": [
                    {"inventor_first_name": "John", "inventor_last_name": "Doe"}
                ],
            }
        ]
    }
    results = collector._parse_results(data, "14-03")
    assert len(results) == 1
    assert results[0].title == "Smartphone case"
    assert results[0].patent_office.value == "USPTO"
    assert results[0].applicant == "Apple Inc."


def test_euipo_parse_results_with_data():
    collector = EUIPOCollector()
    data = {
        "items": [
            {
                "applicationNumber": "002345678",
                "registrationNumber": "002345678",
                "designNumber": "0001",
                "productIndication": "Mobile phone case",
                "filingDate": "2024-03-20",
                "locarnoClass": "1403",
                "holders": [{"name": "Samsung"}],
                "designers": [{"name": "Kim"}],
            }
        ]
    }
    results = collector._parse_results(data, "14-03")
    assert len(results) == 1
    assert results[0].title == "Mobile phone case"
    assert results[0].patent_office.value == "EUIPO"
    assert results[0].locarno_class == "14-03"


def test_jpo_parse_results_with_data():
    collector = JPOCollector()
    data = {
        "items": [
            {
                "applicationNumber": "2024-001234",
                "registrationNumber": "1700001",
                "articleName": "携帯電話ケース",
                "applicationDate": "20240115",
                "locarnoCd": "1403",
                "dClassCd": "H4",
                "mainDrawing": "/images/design/2024001234.png",
            }
        ]
    }
    results = collector._parse_results(data, "14-03")
    assert len(results) == 1
    assert results[0].title == "携帯電話ケース"
    assert results[0].patent_office.value == "JPO"
    assert len(results[0].drawings) >= 1
