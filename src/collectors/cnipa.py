"""중국국가지식산권국(CNIPA) 디자인 데이터 수집기.

CNIPA는 공개 REST API를 제공하지 않으므로 WIPO Global Design Database 및
Google Patents Public Data를 경유하여 중국 디자인권 데이터를 수집합니다.
직접 수집 시 CNIPA 웹사이트 조회 후 Excel 수동입력을 권장합니다.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import httpx

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType

LOCARNO_TO_CN_CLASS = {
    "01": "01",
    "02": "02",
    "03": "03",
    "06": "06",
    "07": "07",
    "09": "09",
    "12": "12",
    "14": "14",
    "15": "15",
    "23": "23",
    "26": "26",
}


class CNIPACollector(BaseCollector):
    """CNIPA 디자인 수집기 - WIPO Global Design DB 경유"""

    WIPO_GDD_URL = "https://www.wipo.int/designdb/en/search.jsp"
    GOOGLE_PATENTS_URL = "https://patents.google.com/xhr/query"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("CNIPA_API_KEY", "")

    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        query_parts = [f"locarno:{locarno_class}", "country:CN", "type:design"]
        if keyword:
            query_parts.append(keyword)
        if date_from:
            query_parts.append(f"after:filing:{date_from}")
        if date_to:
            query_parts.append(f"before:filing:{date_to}")

        params = {
            "url": " ".join(query_parts),
            "num": str(min(max_results, 100)),
            "type": "12",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self.GOOGLE_PATENTS_URL, params=params)
            resp.raise_for_status()

        return self._parse_google_patents(resp.json(), locarno_class)

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        clean_num = application_number.replace(" ", "")
        params = {"url": f"patent/{clean_num}", "type": "12"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self.GOOGLE_PATENTS_URL, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

        results = self._parse_google_patents(resp.json(), "99-99")
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
                    ext = "png" if "png" in ct else "jpg"
                    filename = f"{patent.application_number}_{drawing.drawing_type.value}.{ext}"
                    filepath = out / filename
                    filepath.write_bytes(resp.content)
                    drawing.file_path = str(filepath)
                    downloaded.append(str(filepath))
                except httpx.HTTPError:
                    continue

        return downloaded

    def _parse_google_patents(self, data: dict, locarno_class: str) -> list[DesignPatent]:
        results = data.get("results") or data.get("organic_results") or []
        patents = []

        cluster = results.get("cluster") if isinstance(results, dict) else results
        if isinstance(cluster, list):
            items = []
            for c in cluster:
                items.extend(c.get("result") or [])
        elif isinstance(results, list):
            items = results
        else:
            return patents

        for item in items:
            patent_info = item.get("patent") or item
            patent_id = patent_info.get("publication_number") or patent_info.get("patent_number", "")
            if not patent_id:
                continue

            country = patent_id[:2] if len(patent_id) >= 2 else "CN"
            if country != "CN":
                continue

            title = patent_info.get("title", "")
            if isinstance(title, dict):
                title = title.get("zh", title.get("en", "Unknown"))

            drawings = []
            thumbnail = patent_info.get("thumbnail") or patent_info.get("image")
            if thumbnail:
                drawings.append(DrawingImage(
                    drawing_type=DrawingType.REPRESENTATIVE,
                    url=thumbnail if thumbnail.startswith("http") else f"https://patentimages.storage.googleapis.com/{thumbnail}",
                ))

            for img in (patent_info.get("images") or [])[:5]:
                url = img if isinstance(img, str) else img.get("url", "")
                if url:
                    if not url.startswith("http"):
                        url = f"https://patentimages.storage.googleapis.com/{url}"
                    drawings.append(DrawingImage(drawing_type=DrawingType.PERSPECTIVE, url=url))

            applicant = patent_info.get("assignee") or patent_info.get("applicant")
            if isinstance(applicant, list):
                applicant = applicant[0] if applicant else None

            inventor = patent_info.get("inventor")
            if isinstance(inventor, list):
                inventor = inventor[0] if inventor else None

            patent = DesignPatent(
                application_number=patent_info.get("application_number", patent_id),
                registration_number=patent_id,
                publication_number=patent_id,
                patent_office=PatentOffice.CNIPA,
                title=title or "Unknown",
                applicant=applicant,
                designer=inventor,
                filing_date=self._parse_date(patent_info.get("filing_date")),
                publication_date=self._parse_date(patent_info.get("publication_date")),
                locarno_class=patent_info.get("locarno_class", locarno_class),
                local_class_codes=[c for c in [patent_info.get("ipc")] if c],
                design_description=patent_info.get("abstract"),
                drawings=drawings,
            )
            patent.id = f"CNIPA-{patent_id}"
            patents.append(patent)

        return patents

    @staticmethod
    def _parse_date(date_str: str | None) -> date | None:
        if not date_str:
            return None
        try:
            clean = str(date_str).replace("-", "").replace("/", "")[:8]
            if len(clean) >= 8:
                return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
            return date.fromisoformat(str(date_str)[:10])
        except (ValueError, IndexError):
            return None
