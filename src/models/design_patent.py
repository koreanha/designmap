from __future__ import annotations

import enum
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class PatentOffice(str, enum.Enum):
    KIPO = "KIPO"      # 한국특허청
    USPTO = "USPTO"     # 미국특허상표청
    EUIPO = "EUIPO"     # 유럽연합지식재산청
    CNIPA = "CNIPA"     # 중국국가지식산권국
    JPO = "JPO"         # 일본특허청
    WIPO = "WIPO"       # 세계지식재산기구
    UKIPO = "UKIPO"     # 영국지식재산청
    OTHER = "OTHER"


class DrawingType(str, enum.Enum):
    REPRESENTATIVE = "representative"  # 대표도면
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    PERSPECTIVE = "perspective"        # 사시도
    SECTIONAL = "sectional"            # 단면도
    REFERENCE = "reference"            # 참고도
    THREE_D = "3d"


class DrawingImage(BaseModel):
    drawing_type: DrawingType
    file_path: str | None = None
    url: str | None = None
    description: str | None = None


class DesignPatent(BaseModel):
    id: str | None = None
    application_number: str
    registration_number: str | None = None
    publication_number: str | None = None
    patent_office: PatentOffice
    title: str                              # 대상물품명
    applicant: str | None = None
    designer: str | None = None
    filing_date: date | None = None
    registration_date: date | None = None
    publication_date: date | None = None
    locarno_class: str                      # 로카르노 분류 (e.g., "14-02")
    local_class_codes: list[str] = Field(default_factory=list)  # 각국 세부 디자인분류기호
    design_description: str | None = None   # 디자인의 설명
    drawings: list[DrawingImage] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @property
    def representative_drawing(self) -> DrawingImage | None:
        for d in self.drawings:
            if d.drawing_type == DrawingType.REPRESENTATIVE:
                return d
        return self.drawings[0] if self.drawings else None


class ScreeningResult(BaseModel):
    patent_id: str
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    matched_criteria: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    patent_id: str
    primary_category: str
    secondary_categories: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    design_features: list[str] = Field(default_factory=list)
    trend_tags: list[str] = Field(default_factory=list)
