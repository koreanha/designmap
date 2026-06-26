"""일본특허청(JPO) 디자인 데이터 수집기.

J-PlatPat (특허정보 플랫폼) 및 JPO Open API를 사용합니다.
https://www.j-platpat.inpit.go.jp/
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import httpx

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType

LOCARNO_TO_DCLASS_JP = {
    "01": "A1",
    "02": "B1",
    "03": "B5",
    "06": "C1",
    "07": "C3",
    "09": "F4",
    "12": "G2",
    "14": "H4",
    "15": "J1",
    "23": "K1",
    "26": "L1",
}


class JPOCollector(BaseCollector):
    """JPO 디자인 수집기 - J-PlatPat API 경유"""

    JPLATPAT_API = "https://www.j-platpat.inpit.go.jp/api/design"
    JPO_OPD_URL = "https://www.j-platpat.inpit.go.jp/c1801/DE/JP"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("JPO_API_KEY", "")

    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        jp_class = LOCARNO_TO_DCLASS_JP.get(locarno_class.split("-")[0], "")

        params: dict[str, str] = {
            "locarnoCd": locarno_class.replace("-", ""),
            "displayCount": str(min(max_results, 100)),
            "pageNo": "1",
            "sortKey": "applicationDate",
            "sortOrder": "desc",
        }
        if keyword:
            params["articleName"] = keyword
        if jp_class:
            params["dClassCd"] = jp_class
        if date_from:
            params["applicationDateFrom"] = date_from.replace("-", "")
        if date_to:
            params["applicationDateTo"] = date_to.replace("-", "")

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.JPLATPAT_API}/search",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()

        return self._parse_results(resp.json(), locarno_class)

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.JPLATPAT_API}/detail/{application_number}",
                headers=headers,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

        data = resp.json()
        return self._parse_detail(data)

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

    def _parse_results(self, data: dict, locarno_class: str) -> list[DesignPatent]:
        items = data.get("result") or data.get("data") or data.get("items") or []
        if isinstance(items, dict):
            items = items.get("list") or items.get("items") or []
        patents = []

        for item in items:
            app_num = item.get("applicationNumber") or item.get("appNo", "")
            if not app_num:
                continue

            drawings = self._extract_drawings(item, app_num)

            locarno = item.get("locarnoCd") or item.get("locarnoClass") or locarno_class
            if isinstance(locarno, list):
                locarno = locarno[0] if locarno else locarno_class
            if len(locarno) >= 4 and "-" not in locarno:
                locarno = f"{locarno[:2]}-{locarno[2:]}"

            local_codes = []
            d_class = item.get("dClassCd") or item.get("japaneseDesignClass")
            if d_class:
                if isinstance(d_class, list):
                    local_codes = [str(c) for c in d_class]
                else:
                    local_codes = [str(d_class)]

            patent = DesignPatent(
                application_number=str(app_num),
                registration_number=item.get("registrationNumber") or item.get("regNo"),
                publication_number=item.get("publicationNumber") or item.get("pubNo"),
                patent_office=PatentOffice.JPO,
                title=item.get("articleName") or item.get("title", "Unknown"),
                applicant=item.get("applicantName") or item.get("applicant"),
                designer=item.get("creatorName") or item.get("designer"),
                filing_date=self._parse_date(item.get("applicationDate") or item.get("appDate")),
                registration_date=self._parse_date(item.get("registrationDate") or item.get("regDate")),
                publication_date=self._parse_date(item.get("publicationDate") or item.get("pubDate")),
                locarno_class=locarno,
                local_class_codes=local_codes,
                design_description=item.get("designDescription") or item.get("description"),
                drawings=drawings,
            )
            patent.id = f"JPO-{app_num}"
            patents.append(patent)

        return patents

    def _parse_detail(self, data: dict) -> DesignPatent | None:
        item = data.get("result") or data.get("data") or data
        app_num = item.get("applicationNumber") or item.get("appNo", "")
        if not app_num:
            return None

        results = self._parse_results({"items": [item]}, "99-99")
        return results[0] if results else None

    def _extract_drawings(self, item: dict, app_num: str) -> list[DrawingImage]:
        drawings = []

        main_img = item.get("mainDrawing") or item.get("representativeImage") or item.get("imageUrl")
        if main_img:
            if not main_img.startswith("http"):
                main_img = f"https://www.j-platpat.inpit.go.jp{main_img}"
            drawings.append(DrawingImage(
                drawing_type=DrawingType.REPRESENTATIVE,
                url=main_img,
            ))

        view_images = item.get("drawings") or item.get("images") or []
        view_types = [
            DrawingType.FRONT, DrawingType.BACK,
            DrawingType.LEFT, DrawingType.RIGHT,
            DrawingType.TOP, DrawingType.BOTTOM,
            DrawingType.PERSPECTIVE,
        ]
        for i, img in enumerate(view_images[:7]):
            url = img if isinstance(img, str) else img.get("url", "")
            if url:
                if not url.startswith("http"):
                    url = f"https://www.j-platpat.inpit.go.jp{url}"
                dtype = view_types[i] if i < len(view_types) else DrawingType.PERSPECTIVE
                drawings.append(DrawingImage(drawing_type=dtype, url=url))

        return drawings

    @staticmethod
    def _parse_date(date_str: str | None) -> date | None:
        if not date_str:
            return None
        try:
            clean = str(date_str).replace("-", "").replace("/", "").replace(".", "")[:8]
            if len(clean) >= 8:
                return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
            return date.fromisoformat(str(date_str)[:10])
        except (ValueError, IndexError):
            return None
