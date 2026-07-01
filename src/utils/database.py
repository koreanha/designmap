from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Column, String, Float, Date, Text, Boolean, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from src.models import DesignPatent, ClassificationResult, ScreeningResult


class Base(DeclarativeBase):
    pass


class DesignPatentRow(Base):
    __tablename__ = "design_patents"

    id = Column(String, primary_key=True)
    application_number = Column(String, nullable=False)
    registration_number = Column(String)
    publication_number = Column(String)
    patent_office = Column(String, nullable=False)
    title = Column(String, nullable=False)
    applicant = Column(String)
    designer = Column(String)
    filing_date = Column(Date)
    registration_date = Column(Date)
    publication_date = Column(Date)
    locarno_class = Column(String, nullable=False)
    local_class_codes = Column(Text, default="[]")
    design_description = Column(Text)
    drawings_json = Column(Text, default="[]")
    metadata_json = Column(Text, default="{}")


class ScreeningResultRow(Base):
    __tablename__ = "screening_results"

    patent_id = Column(String, primary_key=True)
    passed = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(Text)
    matched_criteria = Column(Text, default="[]")


class ClassificationResultRow(Base):
    __tablename__ = "classification_results"

    patent_id = Column(String, primary_key=True)
    primary_category = Column(String, nullable=False)
    secondary_categories = Column(Text, default="[]")
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    design_features = Column(Text, default="[]")
    trend_tags = Column(Text, default="[]")


class Database:
    def __init__(self, db_url: str | None = None):
        from src.utils.paths import default_db_url

        self.db_url = db_url or default_db_url()
        self.engine = create_async_engine(self.db_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession)

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save_patent(self, patent: DesignPatent):
        async with self.session_factory() as session:
            row = DesignPatentRow(
                id=patent.id or patent.application_number,
                application_number=patent.application_number,
                registration_number=patent.registration_number,
                publication_number=patent.publication_number,
                patent_office=patent.patent_office.value,
                title=patent.title,
                applicant=patent.applicant,
                designer=patent.designer,
                filing_date=patent.filing_date,
                registration_date=patent.registration_date,
                publication_date=patent.publication_date,
                locarno_class=patent.locarno_class,
                local_class_codes=json.dumps(patent.local_class_codes),
                design_description=patent.design_description,
                drawings_json=json.dumps([d.model_dump() for d in patent.drawings]),
                metadata_json=json.dumps(patent.metadata),
            )
            await session.merge(row)
            await session.commit()

    async def save_screening(self, result: ScreeningResult):
        async with self.session_factory() as session:
            row = ScreeningResultRow(
                patent_id=result.patent_id,
                passed=result.passed,
                confidence=result.confidence,
                reason=result.reason,
                matched_criteria=json.dumps(result.matched_criteria),
            )
            await session.merge(row)
            await session.commit()

    async def save_classification(self, result: ClassificationResult):
        async with self.session_factory() as session:
            row = ClassificationResultRow(
                patent_id=result.patent_id,
                primary_category=result.primary_category,
                secondary_categories=json.dumps(result.secondary_categories),
                confidence=result.confidence,
                reasoning=result.reasoning,
                design_features=json.dumps(result.design_features),
                trend_tags=json.dumps(result.trend_tags),
            )
            await session.merge(row)
            await session.commit()

    async def get_patents_by_locarno(self, locarno_prefix: str) -> list[dict]:
        async with self.session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM design_patents WHERE locarno_class LIKE :prefix"),
                {"prefix": f"{locarno_prefix}%"},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def get_screened_patents(self, passed_only: bool = True) -> list[dict]:
        async with self.session_factory() as session:
            if passed_only:
                result = await session.execute(
                    text("SELECT p.* FROM design_patents p JOIN screening_results s ON p.id = s.patent_id WHERE s.passed = 1")
                )
            else:
                result = await session.execute(text("SELECT * FROM design_patents"))
            return [dict(row._mapping) for row in result.fetchall()]

    async def get_all_classifications(self) -> list[dict]:
        """저장된 모든 분류 결과 행을 반환."""
        async with self.session_factory() as session:
            result = await session.execute(text("SELECT * FROM classification_results"))
            return [dict(row._mapping) for row in result.fetchall()]

    async def get_unclassified_screened_patents(self) -> list[dict]:
        """스크리닝을 통과했지만 아직 분류되지 않은 디자인권 (분류 이어하기용)."""
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT p.* FROM design_patents p "
                    "JOIN screening_results s ON p.id = s.patent_id "
                    "LEFT JOIN classification_results c ON p.id = c.patent_id "
                    "WHERE s.passed = 1 AND c.patent_id IS NULL"
                )
            )
            return [dict(row._mapping) for row in result.fetchall()]
