from datetime import date

from src.models import DesignPatent, DrawingImage, ScreeningResult, ClassificationResult
from src.models.design_patent import PatentOffice, DrawingType
from src.models.criteria import ClassificationCriteria, CriterionDimension, PESTFactor, PESTCategory


def test_design_patent_creation():
    patent = DesignPatent(
        application_number="30-2024-0001234",
        patent_office=PatentOffice.KIPO,
        title="휴대폰 케이스",
        locarno_class="14-03",
        drawings=[
            DrawingImage(drawing_type=DrawingType.REPRESENTATIVE, url="https://example.com/img.png"),
            DrawingImage(drawing_type=DrawingType.FRONT, file_path="/tmp/front.png"),
        ],
    )
    assert patent.application_number == "30-2024-0001234"
    assert patent.representative_drawing.drawing_type == DrawingType.REPRESENTATIVE
    assert len(patent.drawings) == 2


def test_patent_no_drawings():
    patent = DesignPatent(
        application_number="30-2024-0005678",
        patent_office=PatentOffice.USPTO,
        title="Smartphone case",
        locarno_class="14-03",
    )
    assert patent.representative_drawing is None


def test_screening_result():
    result = ScreeningResult(
        patent_id="30-2024-0001234",
        passed=True,
        confidence=0.85,
        reason="로카르노 및 키워드 일치",
        matched_criteria=["locarno_match", "keyword_match"],
    )
    assert result.passed
    assert result.confidence == 0.85


def test_classification_result():
    result = ClassificationResult(
        patent_id="30-2024-0001234",
        primary_category="minimal",
        secondary_categories=["geometric", "monochrome"],
        confidence=0.9,
        reasoning="간결한 형태와 단색 처리",
        design_features=["곡면 처리", "단일 소재"],
        trend_tags=["minimalism", "sustainability"],
    )
    assert result.primary_category == "minimal"
    assert len(result.trend_tags) == 2


def test_classification_criteria():
    criteria = ClassificationCriteria(
        name="스마트폰 디자인 분류",
        description="스마트폰 외관 디자인 트렌드 분석을 위한 분류 기준",
        locarno_scope=["14-03"],
        dimensions=[
            CriterionDimension(
                name="형태 언어",
                description="전체적인 형태 특성",
                values=["직선적", "곡선적", "유기적", "기하학적"],
                weight=1.5,
            ),
        ],
        pest_factors=[
            PESTFactor(
                category=PESTCategory.TECHNOLOGICAL,
                factor="폴더블 디스플레이 기술",
                relevance="새로운 폼팩터 디자인 가능",
                impact_level="high",
            ),
        ],
        trend_keywords=["foldable", "sustainability", "biomorphic"],
    )
    assert criteria.status == "proposed"
    assert len(criteria.dimensions) == 1
    assert criteria.dimensions[0].weight == 1.5
