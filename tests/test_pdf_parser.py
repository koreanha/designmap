"""PDF 파서 테스트."""
from datetime import date

from src.collectors.pdf_parser import (
    GazetteParser,
    PDFExtractor,
    _parse_date_flexible,
    _normalize_locarno,
    OFFICE_PATTERNS,
)


def test_normalize_locarno_formats():
    assert _normalize_locarno("25-03") == "25-03"
    assert _normalize_locarno("2503") == "25-03"
    assert _normalize_locarno("25-3") == "25-03"
    assert _normalize_locarno("25") == "25"
    assert _normalize_locarno("LOC 25-03") == "25-03"
    assert _normalize_locarno("로카르노분류 12-08") == "12-08"
    assert _normalize_locarno(None) is None


def test_kipo_locarno_pattern_variants():
    parser = GazetteParser(use_vision=False)
    for text in [
        "로카르노분류 25-03",
        "물품류구분: 25-03",
        "(51) Int. Cl. 25-03",
    ]:
        result = parser._regex_extract(text, "KIPO")
        assert result.get("locarno_class", "").replace(" ", "").startswith("25-03") or \
            _normalize_locarno(result.get("locarno_class")) == "25-03", f"실패: {text}"


def test_euipo_locarno_inid_variants():
    parser = GazetteParser(use_vision=False)
    for text in [
        "(51) 12-05",
        "(51) 12 - 05",
        "(51)  12.05",
        "Locarno Classification: 12-05",
        "Locarno Cl. 12-05",
        "Class 12-05",
    ]:
        result = parser._regex_extract(text, "EUIPO")
        assert _normalize_locarno(result.get("locarno_class")) == "12-05", f"실패: {text}"


def test_normalize_locarno_dot():
    assert _normalize_locarno("12.05") == "12-05"
    assert _normalize_locarno("(51) 12.05") == "12-05"


def test_euipo_inid_bare_codes():
    """국제공보식: INID 코드가 괄호 없이 줄 앞에 오는 형식."""
    parser = GazetteParser(use_vision=False)
    text = (
        "11 015021210-0001\n"
        "21 015021210\n"
        "22 15.03.2025\n"
        "73 SHENZHEN ABC CO., LTD.\n"
        "74 GULDE & PARTNER PATENT- UND\n"
        "Wallstr. 58/59\n"
        "D-10179 Berlin\n"
        "51 12 - 05\n"
        "54 Trolley cases\n"
    )
    r = parser._regex_extract(text, "EUIPO")
    assert _normalize_locarno(r.get("locarno_class")) == "12-05"
    assert r.get("application_number") == "015021210"
    assert r.get("registration_number") == "015021210-0001"
    assert r.get("title") == "Trolley cases"
    assert "SHENZHEN" in r.get("applicant", "")


def test_euipo_inid_51_next_line():
    parser = GazetteParser(use_vision=False)
    r = parser._regex_extract("51\n12 - 05\n", "EUIPO")
    assert _normalize_locarno(r.get("locarno_class")) == "12-05"


def test_parse_date_european():
    assert _parse_date_flexible("15.03.2025") == date(2025, 3, 15)
    assert _parse_date_flexible("15/03/2025") == date(2025, 3, 15)


def test_parse_date_iso():
    assert _parse_date_flexible("2024-01-15") == date(2024, 1, 15)


def test_parse_date_dot():
    assert _parse_date_flexible("2024.01.15") == date(2024, 1, 15)


def test_parse_date_compact():
    assert _parse_date_flexible("20240115") == date(2024, 1, 15)


def test_parse_date_us_format():
    assert _parse_date_flexible("Jan 15, 2024") == date(2024, 1, 15)
    assert _parse_date_flexible("March 3, 2024") == date(2024, 3, 3)


def test_parse_date_none():
    assert _parse_date_flexible(None) is None
    assert _parse_date_flexible("") is None
    assert _parse_date_flexible("invalid") is None


def test_all_offices_have_patterns():
    for office in ["KIPO", "USPTO", "EUIPO", "CNIPA", "JPO"]:
        patterns = OFFICE_PATTERNS[office]
        assert "application_number" in patterns
        assert "title" in patterns
        assert "locarno_class" in patterns


def test_regex_extract_kipo():
    parser = GazetteParser(use_vision=False)
    text = """
    출원번호: 30-2024-0001234
    등록번호: 30-0999888
    물품의 명칭: 휴대폰 케이스
    출원인: 삼성전자 주식회사
    창작자: 홍길동
    출원일: 2024.01.15
    등록일: 2024.06.20
    로카르노 분류: 14-03
    디자인의 설명: 본 디자인은 휴대폰 보호 케이스에 관한 것으로 전면부에 곡면 처리를 적용하였다.
    """
    result = parser._regex_extract(text, "KIPO")
    assert result["application_number"] == "30-2024-0001234"
    assert result["registration_number"] == "30-0999888"
    assert result["title"] == "휴대폰 케이스"
    assert result["applicant"] == "삼성전자 주식회사"
    assert result["designer"] == "홍길동"
    assert result["locarno_class"] == "14-03"


def test_regex_extract_uspto():
    parser = GazetteParser(use_vision=False)
    text = """
    United States Design Patent
    Patent No.: D 1,000,123
    Title: Smartphone case
    Assignee: Apple Inc.
    Inventors: John Doe
    Filed: Jan 15, 2024
    Date of Patent: Jun 20, 2024
    LOC (14) Cl. 14-03
    U.S. Cl. D14/486
    CLAIM
    The ornamental design for a smartphone case, as shown and described.
    """
    result = parser._regex_extract(text, "USPTO")
    assert "1,000,123" in result.get("registration_number", "")
    assert result["title"] == "Smartphone case"
    assert result["applicant"] == "Apple Inc."
    assert result["locarno_class"] == "14-03"


def test_regex_extract_euipo():
    parser = GazetteParser(use_vision=False)
    text = """
    Registration Number: 002345678-0001
    Product: Mobile phone cover
    Holder: Samsung Electronics Co., Ltd.
    Designer: Kim
    Filing date: 2024-03-20
    Registration date: 2024-05-10
    Locarno: 14-03
    """
    result = parser._regex_extract(text, "EUIPO")
    assert "002345678" in result.get("registration_number", "")
    assert result["title"] == "Mobile phone cover"
    assert result["locarno_class"] == "14-03"


def test_regex_extract_cnipa():
    parser = GazetteParser(use_vision=False)
    text = """
    申请号: 202430001234.5
    授权公告号: CN 305001234 S
    产品名称: 手机壳
    申请人: 华为技术有限公司
    设计人: 张三
    申请日: 2024.01.15
    授权公告日: 2024.06.20
    洛迦诺分类: 14-03
    简要说明: 本外观设计产品用于保护手机。设计要点在于形状。
    """
    result = parser._regex_extract(text, "CNIPA")
    assert result["application_number"] == "202430001234.5"
    assert result["title"] == "手机壳"
    assert result["applicant"] == "华为技术有限公司"
    assert result["locarno_class"] == "14-03"


def test_regex_extract_jpo():
    parser = GazetteParser(use_vision=False)
    text = """
    出願番号: 意願2024-001234
    登録番号: 1700001
    意匠に係る物品: 携帯電話カバー
    出願人: ソニーグループ株式会社
    創作者: 田中太郎
    出願日: 2024.01.15
    登録日: 2024.06.20
    ロカルノ分類: 14-03
    日本意匠分類: H4-810
    意匠の説明: 本意匠は携帯電話用保護カバーに関するもので、曲面デザインを特徴とする。
    """
    result = parser._regex_extract(text, "JPO")
    assert "2024-001234" in result.get("application_number", "")
    assert result["title"] == "携帯電話カバー"
    assert result["applicant"] == "ソニーグループ株式会社"
    assert result["locarno_class"] == "14-03"


def test_classify_drawings_empty():
    parser = GazetteParser(use_vision=False)
    drawings = parser._classify_drawings([])
    assert drawings == []


def test_classify_drawings_assigns_types():
    parser = GazetteParser(use_vision=False)
    images = [
        {"path": "/img/a.png", "page": 1, "index": 0, "width": 800, "height": 600},
        {"path": "/img/b.png", "page": 1, "index": 1, "width": 400, "height": 300},
        {"path": "/img/c.png", "page": 2, "index": 2, "width": 600, "height": 400},
    ]
    drawings = parser._classify_drawings(images)
    assert len(drawings) == 3
    from src.models.design_patent import DrawingType
    assert drawings[0].drawing_type == DrawingType.REPRESENTATIVE


def test_gazette_parser_init_no_vision():
    parser = GazetteParser(use_vision=False)
    assert not parser.use_vision


def test_parse_json_response_robustness():
    from src.utils.ai import parse_json_response
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('설명 {"a": [1,2,3]} 끝') == {"a": [1, 2, 3]}
    assert parse_json_response('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}


def test_euipo_disjoint_columns_fallback():
    """등록증(2단 레이아웃)에서 코드와 값이 분리 추출되는 경우의 최후 패턴."""
    parser = GazetteParser(use_vision=False)
    text = (
        "Copia Certificada\n"
        "D113D\n"
        "10/12/2025\n"
        "015021210-0001\n"
        "CERTIFICATE OF REGISTRATION\n"
        "Trolley cases\n"
        "12 - 05\n"
    )
    r = parser._regex_extract(text, "EUIPO")
    assert _normalize_locarno(r.get("locarno_class")) == "12-05"
    assert r.get("registration_number") == "015021210-0001"


def test_euipo_fallback_no_false_positives():
    parser = GazetteParser(use_vision=False)
    for bad in ["10/12/2025\n", "1 - 2\n", "E - 03008 Alicante\n"]:
        r = parser._regex_extract(bad, "EUIPO")
        assert not r.get("locarno_class"), f"오인: {bad!r}"


def test_sanitize_rejects_placeholders():
    from src.collectors.pdf_parser import _sanitize_fields
    bad = {
        "application_number": "확인 불가 (문서에 미기재)",
        "registration_number": "N/A (문서에 기재 없음)",
        "title": "알 수 없음 (문서에 미기재)",
        "applicant": "확인불가 (이미지에 미기재)",
        "locarno_class": "해당 정보 없음",
        "designer": "not specified",
    }
    assert _sanitize_fields(bad) == {}


def test_sanitize_keeps_valid_values():
    from src.collectors.pdf_parser import _sanitize_fields
    good = {
        "application_number": "015021210-0001",
        "title": "Trolley cases",
        "locarno_class": "12 - 05",
        "applicant": "SHENZHEN ABC CO., LTD.",
    }
    assert _sanitize_fields(good) == good


def test_sanitize_rejects_malformed_locarno():
    from src.collectors.pdf_parser import _sanitize_fields
    assert _sanitize_fields({"locarno_class": "class twelve"}) == {}


def test_title_language_prefix_stripped():
    from src.collectors.pdf_parser import _sanitize_fields
    assert _sanitize_fields({"title": "ES - Robots de transporte"})["title"] == "Robots de transporte"


def test_title_prefers_english_line():
    parser = GazetteParser(use_vision=False)
    text = "54\nES - Robots de transporte\nEN - Transport robots\n"
    r = parser._regex_extract(text, "EUIPO")
    assert r.get("title") == "Transport robots"


def test_applicant_address_rejected_company_kept():
    from src.collectors.pdf_parser import _sanitize_fields
    assert _sanitize_fields({"applicant": "Room 802, Information Building 13"}) == {}
    assert _sanitize_fields({"applicant": "500 OAKWOOD ROAD"}) == {}
    assert _sanitize_fields({"applicant": "SHENZHEN ABC CO., LTD."}) != {}


def test_euipo_title_en_and_applicant_company():
    """사용자 실제 사례: 54의 EN 값, 73 블록의 회사명 추출."""
    parser = GazetteParser(use_vision=False)
    text = (
        "54\n"
        "ES - Robots de transporte (parte de -)\n"
        "EN - transportation robots (part of - )\n"
        "FR - robots de transport\n"
        "73 Room 802, Information Building 13 Linyin North\n"
        "HAI ROBOTICS Co., LTD\n"
        "74 GULDE & PARTNER PATENT- UND\n"
    )
    r = parser._regex_extract(text, "EUIPO")
    assert r.get("title") == "transportation robots (part of - )"
    assert r.get("applicant") == "HAI ROBOTICS Co., LTD"


def test_euipo_title_en_inline():
    parser = GazetteParser(use_vision=False)
    text = "54 ES - Robots EN - transportation robots (part of - ) FR - robots\n"
    r = parser._regex_extract(text, "EUIPO")
    assert r.get("title") == "transportation robots (part of - )"


def test_jpo_fullwidth_gazette():
    """실제 의장공보(전각 문자 + 【라벨】 구조) 사례."""
    from src.collectors.pdf_parser import _sanitize_fields
    parser = GazetteParser(use_vision=False)
    text = (
        "（１１）【登録番号】意匠登録第１８１１７７１号（Ｄ１８１１７７１）\n"
        "（２４）【登録日】令和７年１０月２０日（２０２５．１０．２０）\n"
        "（５４）【意匠に係る物品】Ｔｒａｎｓｆｅｒ　ｒｏｂｏｔ\n"
        "（５４）【意匠に係る物品の訳（参考）】搬送ロボット\n"
        "（５１）【国際意匠分類】Ｌｏｃ（１４）Ｃｌ．１２－０５\n"
        "（２１）【出願番号】意願２０２５－５０００３２（Ｄ２０２５－５０００３２）\n"
        "（７３）【意匠権者】\n"
        "【氏名又は名称】ＢＥＩＪＩＮＧ　ＪＩＮＧＤＯＮＧ　ＱＩＡＮＳＨＩ　ＴＥＣＨＮＯＬＯＧＹ　ＣＯ．，　\n"
        "ＬＴＤ．\n"
        "【住所又は居所】Ｒｏｏｍ　Ａ１９０５\n"
    )
    r = _sanitize_fields(parser._regex_extract(text, "JPO"))
    assert r.get("title") == "Transfer robot"
    assert _normalize_locarno(r.get("locarno_class")) == "12-05"
    assert r.get("registration_number") == "1811771"
    assert r.get("application_number") == "2025-500032"
    assert "BEIJING JINGDONG" in r.get("applicant", "")
    assert r.get("applicant", "").endswith("LTD.")


def test_needs_translation_cjk_detection():
    from src.utils.translate import needs_translation
    assert needs_translation("電動車両")
    assert needs_translation("搬送ロボット")
    assert not needs_translation("Transfer robot")
    assert not needs_translation("의자")
    assert not needs_translation(None)


def test_jpo_special_char_markers_cleaned():
    """일본 공보의 ▲문자▼ 표기(ST▲A▼UBLI = Stäubli) 복원."""
    from src.collectors.pdf_parser import _sanitize_fields
    from src.utils.translate import clean_special_chars
    assert clean_special_chars("ST▲A▼UBLI WFT GmbH") == "STAUBLI WFT GmbH"
    assert _sanitize_fields({"applicant": "ST▲A▼UBLI WFT GmbH"})["applicant"] == "STAUBLI WFT GmbH"


def test_needs_translation_applicant_names():
    from src.utils.translate import needs_translation
    assert needs_translation("山田工業株式会社")
    assert needs_translation("アプライド・エレクトリック・ビークルズ・リミテッド")
    assert not needs_translation("BEIJING JINGDONG QIANSHI TECHNOLOGY CO., LTD.")
    assert not needs_translation("Ocado Innovation Limited")


def test_korean_not_treated_as_cjk_for_translation():
    """한글은 번역 대상이 아니다 (한자 범위에 한글이 섞이지 않도록)."""
    from src.utils.translate import needs_translation
    for korean in ["의자", "휴대폰 케이스", "건축용 벽체", "가나다"]:
        assert not needs_translation(korean), korean
