"""수동 데이터 입력 수집기.

API 접근이 불가능한 경우 Excel/CSV 파일 또는 직접 입력으로 데이터를 등록합니다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType


class ManualCollector(BaseCollector):
    """Excel/CSV 파일 또는 직접 입력으로 디자인 특허 데이터 수집"""

    async def search(self, locarno_class: str, **kwargs) -> list[DesignPatent]:
        return []

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        return None

    async def download_drawings(self, patent: DesignPatent, output_dir: str) -> list[str]:
        return []

    @staticmethod
    def from_excel(file_path: str, drawings_dir: str | None = None) -> list[DesignPatent]:
        """Excel 파일에서 디자인권 데이터 로드.

        Expected columns:
            application_number, patent_office, title, locarno_class,
            applicant (opt), filing_date (opt), design_description (opt),
            local_class_codes (opt, semicolon-separated),
            drawing_files (opt, semicolon-separated filenames)
        """
        df = pd.read_excel(file_path, dtype=str).fillna("")
        patents = []

        for _, row in df.iterrows():
            drawings = []
            if row.get("drawing_files") and drawings_dir:
                for i, fname in enumerate(str(row["drawing_files"]).split(";")):
                    fname = fname.strip()
                    if not fname:
                        continue
                    dtype = DrawingType.REPRESENTATIVE if i == 0 else DrawingType.PERSPECTIVE
                    fpath = Path(drawings_dir) / fname
                    drawings.append(DrawingImage(
                        drawing_type=dtype,
                        file_path=str(fpath) if fpath.exists() else None,
                        description=fname,
                    ))

            local_codes = [c.strip() for c in str(row.get("local_class_codes", "")).split(";") if c.strip()]
            filing = None
            if row.get("filing_date"):
                try:
                    filing = date.fromisoformat(str(row["filing_date"])[:10])
                except ValueError:
                    pass

            office = PatentOffice(row.get("patent_office", "OTHER")) if row.get("patent_office") else PatentOffice.OTHER

            patent = DesignPatent(
                application_number=str(row["application_number"]),
                patent_office=office,
                title=str(row["title"]),
                locarno_class=str(row["locarno_class"]),
                applicant=row.get("applicant") or None,
                filing_date=filing,
                design_description=row.get("design_description") or None,
                local_class_codes=local_codes,
                drawings=drawings,
            )
            patent.id = patent.application_number
            patents.append(patent)

        return patents

    @staticmethod
    def create_template(output_path: str):
        """데이터 입력용 Excel 템플릿 생성"""
        df = pd.DataFrame(columns=[
            "application_number",
            "patent_office",
            "title",
            "locarno_class",
            "applicant",
            "filing_date",
            "design_description",
            "local_class_codes",
            "drawing_files",
        ])
        sample = {
            "application_number": "30-2024-0001234",
            "patent_office": "KIPO",
            "title": "휴대폰 케이스",
            "locarno_class": "14-03",
            "applicant": "삼성전자",
            "filing_date": "2024-01-15",
            "design_description": "본 디자인은 휴대폰 보호 케이스에 관한 것으로...",
            "local_class_codes": "D14-0301;D14-0302",
            "drawing_files": "front.png;back.png;left.png;right.png",
        }
        df = pd.concat([df, pd.DataFrame([sample])], ignore_index=True)
        df.to_excel(output_path, index=False)
