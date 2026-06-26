"""미국특허상표청(USPTO) 디자인 데이터 수집기.

USPTO PatentsView API와 Open Data Portal을 사용합니다.
API 키는 https://patentsview.org/apis/api-endpoints 에서 확인 가능합니다.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import httpx

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType

LOCARNO_TO_USPC = {
    "01": "D01",
    "02": "D02",
    "03": "D03",
    "06": "D06",
    "07": "D07",
    "09": "D09",
    "12": "D12",
    "14": "D14",
    "15": "D15",
    "23": "D23",
    "26": "D26",
}


class USPTOCollector(BaseCollector):
    PATENTSVIEW_URL = "https://api.patentsview.org/designs/query"
    DRAWING_URL_TEMPLATE = "https://pdfpiw.uspto.gov/.piw?docid=D{patent_number}"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("USPTO_API_KEY", "")

    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        uspc_class = LOCARNO_TO_USPC.get(locarno_class.split("-")[0], "")

        criteria = []
        if uspc_class:
            criteria.append({"_text_any": {"patent_abstract": uspc_class}})
        if keyword:
            criteria.append({"_text_any": {"patent_title": keyword}})
        if date_from:
            criteria.append({"_gte": {"patent_date": date_from}})
        if date_to:
            criteria.append({"_lte": {"patent_date": date_to}})

        if not criteria:
            criteria.append({"_text_any": {"patent_title": "design"}})

        query = {
            "q": {"_and": criteria} if len(criteria) > 1 else criteria[0],
            "f": [
                "patent_number", "patent_title", "patent_date", "patent_type",
                "patent_abstract",
                "assignees.assignee_organization",
                "inventors.inventor_first_name", "inventors.inventor_last_name",
            ],
            "o": {"per_page": min(max_results, 100)},
        }

        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.PATENTSVIEW_URL, json=query, headers=headers)
            resp.raise_for_status()

        return self._parse_results(resp.json(), locarno_class)

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        query = {
            "q": {"patent_number": application_number},
            "f": [
                "patent_number", "patent_title", "patent_date", "patent_type",
                "patent_abstract",
                "assignees.assignee_organization",
                "inventors.inventor_first_name", "inventors.inventor_last_name",
            ],
        }

        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.PATENTSVIEW_URL, json=query, headers=headers)
            resp.raise_for_status()

        results = self._parse_results(resp.json(), "99-99")
        return results[0] if results else None

    async def download_drawings(self, patent: DesignPatent, output_dir: str) -> list[str]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        downloaded = []

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for drawing in patent.drawings:
                if not drawing.url:
                    continue
                try:
                    resp = await client.get(drawing.url)
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    ext = "png" if "png" in ct else "jpg" if "jpg" in ct or "jpeg" in ct else "pdf"
                    filename = f"{patent.application_number}_{drawing.drawing_type.value}.{ext}"
                    filepath = out / filename
                    filepath.write_bytes(resp.content)
                    drawing.file_path = str(filepath)
                    downloaded.append(str(filepath))
                except httpx.HTTPError:
                    continue

        return downloaded

    def _parse_results(self, data: dict, locarno_class: str) -> list[DesignPatent]:
        patents_data = data.get("designs") or data.get("patents") or []
        patents = []

        for item in patents_data:
            patent_num = item.get("patent_number", "")
            if not patent_num:
                continue

            assignees = item.get("assignees") or [{}]
            applicant = assignees[0].get("assignee_organization") if assignees else None

            inventors = item.get("inventors") or []
            designer = None
            if inventors:
                inv = inventors[0]
                first = inv.get("inventor_first_name", "")
                last = inv.get("inventor_last_name", "")
                designer = f"{first} {last}".strip() or None

            pub_date = self._parse_date(item.get("patent_date"))

            drawing_url = f"https://pimg-fpiw.uspto.gov/fdd/00/{patent_num[-5:-3]}/{patent_num[-3:]}/0.png"
            drawings = [
                DrawingImage(drawing_type=DrawingType.REPRESENTATIVE, url=drawing_url)
            ]

            patent = DesignPatent(
                application_number=patent_num,
                registration_number=patent_num,
                patent_office=PatentOffice.USPTO,
                title=item.get("patent_title", "Unknown"),
                applicant=applicant,
                designer=designer,
                publication_date=pub_date,
                locarno_class=locarno_class,
                design_description=item.get("patent_abstract"),
                drawings=drawings,
            )
            patent.id = f"USPTO-{patent_num}"
            patents.append(patent)

        return patents

    @staticmethod
    def _parse_date(date_str: str | None) -> date | None:
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str[:10])
        except ValueError:
            return None
