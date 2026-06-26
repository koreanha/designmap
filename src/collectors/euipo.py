"""유럽연합지식재산청(EUIPO) 디자인 데이터 수집기.

EUIPO eSearch plus API를 사용합니다. 별도 API 키 불필요.
https://euipo.europa.eu/eSearch/
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from src.collectors.base import BaseCollector
from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType


class EUIPOCollector(BaseCollector):
    SEARCH_URL = "https://euipo.europa.eu/eSearch/api/rcd/search"
    DETAIL_URL = "https://euipo.europa.eu/eSearch/api/rcd"
    IMAGE_URL_TEMPLATE = "https://euipo.europa.eu/eSearch/api/rcd/{number}/image/{design_number}"

    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        params: dict[str, str] = {
            "locarnoClass": locarno_class.replace("-", ""),
            "pageSize": str(min(max_results, 100)),
            "page": "1",
            "sortBy": "FilingDate",
            "sortOrder": "desc",
        }
        if keyword:
            params["productIndication"] = keyword
        if date_from:
            params["filingDateFrom"] = date_from
        if date_to:
            params["filingDateTo"] = date_to

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self.SEARCH_URL,
                params=params,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()

        return self._parse_results(resp.json(), locarno_class)

    async def get_patent(self, application_number: str) -> DesignPatent | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.DETAIL_URL}/{application_number}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

        results = self._parse_results({"items": [resp.json()]}, "99-99")
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

    def _parse_results(self, data: dict, locarno_class: str) -> list[DesignPatent]:
        items = data.get("items") or data.get("results") or []
        patents = []

        for item in items:
            app_num = item.get("applicationNumber") or item.get("registrationNumber", "")
            if not app_num:
                continue

            locarno = item.get("locarnoClass") or locarno_class
            if isinstance(locarno, list):
                locarno = locarno[0] if locarno else locarno_class
            locarno_formatted = locarno
            if len(locarno) >= 4 and "-" not in locarno:
                locarno_formatted = f"{locarno[:2]}-{locarno[2:]}"

            drawings = []
            reg_num = item.get("registrationNumber", app_num)
            design_num = item.get("designNumber", "0001")
            img_url = self.IMAGE_URL_TEMPLATE.format(number=reg_num, design_number=design_num)
            drawings.append(DrawingImage(
                drawing_type=DrawingType.REPRESENTATIVE,
                url=img_url,
            ))

            representations = item.get("representations") or []
            for i, rep in enumerate(representations[:5]):
                rep_url = rep.get("url") or rep.get("imageUrl")
                if rep_url:
                    dtype = DrawingType.PERSPECTIVE if i > 0 else DrawingType.REPRESENTATIVE
                    drawings.append(DrawingImage(drawing_type=dtype, url=rep_url))

            holders = item.get("holders") or item.get("applicants") or []
            applicant = holders[0].get("name") if holders else None

            designers_list = item.get("designers") or []
            designer = designers_list[0].get("name") if designers_list else None

            product = item.get("productIndication") or item.get("title", "Unknown")
            if isinstance(product, list):
                product = product[0] if product else "Unknown"

            patent = DesignPatent(
                application_number=str(app_num),
                registration_number=item.get("registrationNumber"),
                publication_number=item.get("publicationNumber"),
                patent_office=PatentOffice.EUIPO,
                title=product,
                applicant=applicant,
                designer=designer,
                filing_date=self._parse_date(item.get("filingDate")),
                registration_date=self._parse_date(item.get("registrationDate")),
                publication_date=self._parse_date(item.get("publicationDate")),
                locarno_class=locarno_formatted,
                local_class_codes=[str(lc) for lc in (item.get("locarnoClasses") or [])],
                design_description=item.get("description"),
                drawings=drawings,
            )
            patent.id = f"EUIPO-{app_num}"
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
