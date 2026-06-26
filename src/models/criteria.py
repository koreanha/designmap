from __future__ import annotations

import enum
from pydantic import BaseModel, Field


class PESTCategory(str, enum.Enum):
    POLITICAL = "political"
    ECONOMIC = "economic"
    SOCIAL = "social"
    TECHNOLOGICAL = "technological"


class PESTFactor(BaseModel):
    category: PESTCategory
    factor: str
    relevance: str
    impact_level: str = "medium"  # low, medium, high


class CriterionDimension(BaseModel):
    name: str
    description: str
    values: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    weight: float = 1.0


class ClassificationCriteria(BaseModel):
    """에이전트가 제안하고 사용자가 검토/확정하는 분류 기준"""
    name: str
    description: str
    locarno_scope: list[str]  # 적용 대상 로카르노 분류
    dimensions: list[CriterionDimension] = Field(default_factory=list)
    pest_factors: list[PESTFactor] = Field(default_factory=list)
    trend_keywords: list[str] = Field(default_factory=list)
    status: str = "proposed"  # proposed, reviewed, approved, rejected
    revision_notes: str | None = None
