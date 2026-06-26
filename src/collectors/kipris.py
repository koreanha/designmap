"""한국특허정보원(KIPRIS) 디자인 데이터 수집기.

KIPRIS OpenAPI를 사용하여 한국 디자인권 데이터를 수집합니다.
API 키는 http://plus.kipris.or.kr 에서 발급받을 수 있습니다.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import httpx

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType


class KIPRISCollector(BaseCollector):
    BASE_URL = "http://plus.kipris.or.kr/kipo-api/kipi"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("KIPRIS_API_KEY", "")

    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        if not self.api_key:
            raise ValueError("KIPRIS_API_KEY not configured. Get one at http://plus.kipris.or.kr")

        params = {
            "ServiceKey": self.api_key,
            "locarnoCd": locarno_class.replace("-", ""),
            "numOfRows": str(min(max_results, 500)),
            "pageNo": "1",
        }
        if keyword:
            params["articleName"] = keyword
        if date_from:
            params["applicationDateFrom"] = date_from.replace("-", "")
        if date_to:
            params["applicationDateTo"] = date_to.replace("-", "")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/designInfoSearchService/getAdvancedSearch",
                params=params,
            )
            resp.raise_for_status()

        return self._parse_search_results(resp.text)

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        if not self.api_key:
            raise ValueError("KIPRIS_API_KEY not configured")

        params = {
            "ServiceKey": self.api_key,
            "applicationNumber": application_number,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/designInfoSearchService/getDesignInfo",
                params=params,
            )
            resp.raise_for_status()

        results = self._parse_search_results(resp.text)
        return results[0] if results else None

    async def download_drawings(self, patent: DesignPatent, output_dir: str) -> list[str]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        downloaded = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for drawing in patent.drawings:
                if not drawing.url:
                    continue
                try:
                    resp = await client.get(drawing.url, follow_redirects=True)
                    resp.raise_for_status()
                    ext = "png" if "png" in resp.headers.get("content-type", "") else "jpg"
                    filename = f"{patent.application_number}_{drawing.drawing_type.value}.{ext}"
                    filepath = out / filename
                    filepath.write_bytes(resp.content)
                    drawing.file_path = str(filepath)
                    downloaded.append(str(filepath))
                except httpx.HTTPError:
                    continue

        return downloaded

    def _parse_search_results(self, xml_text: str) -> list[DesignPatent]:
        import xml.etree.ElementTree as ET

        patents = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return patents

        for item in root.iter("item"):
            app_num = self._get_text(item, "applicationNumber", "")
            if not app_num:
                continue

            drawings = []
            img_url = self._get_text(item, "bigDrawing") or self._get_text(item, "drawing")
            if img_url:
                drawings.append(DrawingImage(
                    drawing_type=DrawingType.REPRESENTATIVE,
                    url=img_url,
                ))

            filing = self._parse_date(self._get_text(item, "applicationDate"))
            reg = self._parse_date(self._get_text(item, "registrationDate"))
            pub = self._parse_date(self._get_text(item, "publicationDate"))

            patent = DesignPatent(
                application_number=app_num,
                registration_number=self._get_text(item, "registrationNumber"),
                publication_number=self._get_text(item, "publicationNumber"),
                patent_office=PatentOffice.KIPO,
                title=self._get_text(item, "articleName", "Unknown"),
                applicant=self._get_text(item, "applicantName"),
                designer=self._get_text(item, "inventorName"),
                filing_date=filing,
                registration_date=reg,
                publication_date=pub,
                locarno_class=self._get_text(item, "locarnoCd", "99-99"),
                local_class_codes=[c for c in [self._get_text(item, "designClassCode")] if c],
                design_description=self._get_text(item, "designDescription"),
                drawings=drawings,
            )
            patent.id = app_num
            patents.append(patent)

        return patents

    @staticmethod
    def _get_text(elem, tag: str, default: str | None = None) -> str | None:
        child = elem.find(tag)
        return child.text if child is not None and child.text else default

    @staticmethod
    def _parse_date(date_str: str | None) -> date | None:
        if not date_str or len(date_str) < 8:
            return None
        try:
            clean = date_str.replace("-", "").replace("/", "")[:8]
            return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        except (ValueError, IndexError):
            return None
