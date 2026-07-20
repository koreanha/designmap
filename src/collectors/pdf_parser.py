"""디자인 공보 PDF 파서.

각국 특허청의 원문공보 PDF에서 서지사항 및 도면을 추출합니다.

지원 형식:
- KIPO (한국): 디자인공보/등록공보 PDF
- USPTO (미국): Design Patent PDF
- EUIPO (유럽): RCD Publication PDF
- CNIPA (중국): 外观设计专利公报 PDF
- JPO (일본): 意匠公報 PDF

사용법:
    parser = GazetteParser()
    results = parser.parse_directory("/path/to/pdfs", office="KIPO")
    parser.to_excel(results, "output.xlsx")
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from src.models import DesignPatent, DrawingImage
from src.models.design_patent import PatentOffice, DrawingType
from src.utils.ai import get_client, api_key_available


class PDFExtractor:
    """PDF에서 텍스트와 이미지를 추출하는 저수준 유틸리티"""

    @staticmethod
    def extract_text(pdf_path: str, sort: bool = False) -> str:
        """PDF 텍스트 추출. sort=True면 읽기 순서(좌→우, 상→하)로 정렬해
        다단 레이아웃에서 코드와 값이 인접하게 나올 확률을 높인다."""
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text(sort=sort))
        doc.close()
        return "\n".join(text_parts)

    @staticmethod
    def extract_text_by_page(pdf_path: str) -> list[str]:
        doc = fitz.open(pdf_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return pages

    @staticmethod
    def extract_images(pdf_path: str, output_dir: str, prefix: str = "") -> list[dict]:
        """PDF에서 이미지를 추출하여 파일로 저장"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        extracted = []

        img_index = 0
        for page_num, page in enumerate(doc):
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                except Exception:
                    continue

                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                if pix.width < 50 or pix.height < 50:
                    continue

                ext = "png"
                filename = f"{prefix}p{page_num + 1}_img{img_index}.{ext}"
                filepath = out / filename
                pix.save(str(filepath))
                extracted.append({
                    "path": str(filepath),
                    "page": page_num + 1,
                    "index": img_index,
                    "width": pix.width,
                    "height": pix.height,
                })
                img_index += 1

        doc.close()
        return extracted

    @staticmethod
    def render_first_page(pdf_path: str, output_path: str, dpi: int = 200) -> str:
        """첫 페이지를 이미지로 렌더링 (Claude Vision 입력용)"""
        doc = fitz.open(pdf_path)
        page = doc[0]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        pix.save(output_path)
        doc.close()
        return output_path

    @staticmethod
    def render_pages(pdf_path: str, output_dir: str, dpi: int = 150, max_pages: int = 10) -> list[str]:
        """여러 페이지를 이미지로 렌더링"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        rendered = []

        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            stem = Path(pdf_path).stem
            filepath = out / f"{stem}_page{i + 1}.png"
            pix.save(str(filepath))
            rendered.append(str(filepath))

        doc.close()
        return rendered


OFFICE_PATTERNS: dict[str, dict[str, list[re.Pattern]]] = {
    "KIPO": {
        "application_number": [
            re.compile(r"출원번호[:\s]*(\d{2}-\d{4}-\d{7})", re.MULTILINE),
            re.compile(r"출원번호[:\s]*(30-\d{4}-\d+)", re.MULTILINE),
        ],
        "registration_number": [
            re.compile(r"등록번호[:\s]*(\d{2}-\d{7})", re.MULTILINE),
            re.compile(r"등록번호[:\s]*(30-\d+)", re.MULTILINE),
        ],
        "title": [
            re.compile(r"물품[의\s]*명칭[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"디자인의\s*대상이\s*되는\s*물품[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "applicant": [
            re.compile(r"출원인[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"디자인권자[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "designer": [
            re.compile(r"창작자[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "filing_date": [
            re.compile(r"출원일[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "registration_date": [
            re.compile(r"등록일[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "locarno_class": [
            re.compile(r"로카르노\s*분류[^\d]{0,10}(\d{1,2}\s*-\s*\d{1,2})", re.MULTILINE),
            re.compile(r"물품류[^\d]{0,10}(\d{1,2}\s*-\s*\d{1,2})", re.MULTILINE),
            re.compile(r"국제\s*디자인\s*분류[^\d]{0,10}(\d{1,2}\s*-\s*\d{1,2})", re.MULTILINE),
            re.compile(r"\(51\)[^\d]{0,15}(\d{1,2}\s*-\s*\d{1,2})", re.MULTILINE),
            re.compile(r"\bLOC[^\d]{0,8}(\d{1,2}\s*-\s*\d{1,2})", re.MULTILINE | re.IGNORECASE),
        ],
        "local_class_codes": [
            re.compile(r"한국\s*디자인\s*분류[:\s]*([\w\d.-]+)", re.MULTILINE),
            re.compile(r"디자인\s*분류[:\s]*(D[\d-]+)", re.MULTILINE),
        ],
        "design_description": [
            re.compile(r"디자인의\s*설명[:\s]*(.+?)(?:도면|$)", re.DOTALL),
        ],
    },
    "USPTO": {
        "application_number": [
            re.compile(r"Appl[.\s]*No[.:\s]*([\d/,]+)", re.MULTILINE | re.IGNORECASE),
        ],
        "registration_number": [
            re.compile(r"Patent\s*No[.:\s]*D?\s*([\d,]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"(D[\d,]+)", re.MULTILINE),
            re.compile(r"USD\s*([\d,]+)", re.MULTILINE),
        ],
        "title": [
            re.compile(r"Title[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"\(\d+\)\s*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "applicant": [
            re.compile(r"Assignee[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
        ],
        "designer": [
            re.compile(r"Inventor[s]?[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
        ],
        "filing_date": [
            re.compile(r"Filed[:\s]*([\w\s.,\d]+\d{4})", re.MULTILINE | re.IGNORECASE),
        ],
        "registration_date": [
            re.compile(r"Date\s*of\s*Patent[:\s]*([\w\s.,\d]+\d{4})", re.MULTILINE | re.IGNORECASE),
        ],
        "locarno_class": [
            re.compile(r"LOC[.\s]*\(?\d*\)?[:\s]*Cl[.\s]*([\d-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"Int[.\s]*Cl[.\s]*(D[\d-]+)", re.MULTILINE | re.IGNORECASE),
        ],
        "local_class_codes": [
            re.compile(r"U\.?S\.?\s*Cl[.\s]*(D[\d/.-]+)", re.MULTILINE | re.IGNORECASE),
        ],
        "design_description": [
            re.compile(r"CLAIM\s*(.+?)(?:DESCRIPTION|$)", re.DOTALL | re.IGNORECASE),
        ],
    },
    "EUIPO": {
        # 주의: EUIPO/국제공보는 INID 코드(11, 21, 51, 54, 73...)를 괄호 없이
        # 줄 맨 앞에 표기하는 경우가 많다 (예: "51  12 - 05").
        "application_number": [
            re.compile(r"Application\s*(?:No|Number)[.:\s]*([\d\s]+\d)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?21\)?[ \t]+([\d][\d ./-]{4,}\d)[ \t]*$", re.MULTILINE),
        ],
        "registration_number": [
            re.compile(r"Registration\s*(?:No|Number)[.:\s]*([\d\s-]+\d)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"RCD\s*(?:No|Number)?[.:\s]*([\d-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?11\)?[ \t]+([\d][\d ./-]{4,}\d)[ \t]*$", re.MULTILINE),
            # RCD/EU 디자인 등록번호 형식(9자리-4자리)이 단독 줄로 나오는 경우
            re.compile(r"^[ \t]*(\d{9}-\d{4})[ \t]*$", re.MULTILINE),
        ],
        "title": [
            # 다국어 병기(54) 중 영어(EN) 표기를 최우선으로 선택.
            # 'EN - ...' 이 줄 어디에 있든, 다음 언어코드( FR - / DE - ...) 직전까지 캡처
            re.compile(
                r"\bEN[ \t]*[-–][ \t]*(.+?)(?=[ \t]+[A-Z]{2}[ \t]*[-–][ \t]|[\n\r]|$)",
            ),
            re.compile(r"Product\s*(?:Indication)?[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"Indication\s*of\s*(?:the\s*)?product[s]?[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?54\)?\s+(.+?)\s*$", re.MULTILINE),
        ],
        "applicant": [
            re.compile(r"Holder[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"Applicant[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?7[34]\)?[ \t]+(.+?)[ \t]*$", re.MULTILINE),
            # 최후 수단: 회사 표식(Co./Ltd/GmbH 등)이 있는 줄을 문서에서 탐색.
            # 권리자(73)가 대리인(74)보다 먼저 나오므로 첫 매칭이 권리자일 확률이 높음
            re.compile(
                r"^[ \t]*([^\n]{2,90}?\b(?:Co\.?\s*,?\s*Ltd\.?|Ltd\.?|LLC|Inc\.?|Corp\.?"
                r"|GmbH|A\.?G\.?|S\.?L\.?U?\.?|S\.?A\.?|N\.?V\.?|B\.?V\.?|Oy|AB"
                r"|주식회사|株式会社|有限公司)[^\n]{0,30})[ \t]*$",
                re.MULTILINE | re.IGNORECASE,
            ),
        ],
        "designer": [
            re.compile(r"Designer[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?72\)?\s+(.+?)\s*$", re.MULTILINE),
        ],
        "filing_date": [
            re.compile(r"Filing\s*date[:\s]*([\d./-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"Date\s*of\s*filing[:\s]*([\d./-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?22\)?[ \t]+([\d./-]{8,})[ \t]*$", re.MULTILINE),
        ],
        "registration_date": [
            re.compile(r"Registration\s*date[:\s]*([\d./-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"^\s*\(?15\)?[ \t]+([\d./-]{8,})[ \t]*$", re.MULTILINE),
        ],
        "locarno_class": [
            re.compile(r"Locarno[^\d]{0,25}(\d{1,2}\s*[-.]\s*\d{1,2})", re.MULTILINE | re.IGNORECASE),
            re.compile(r"\(51\)[^\d]{0,25}(\d{1,2}\s*[-.]\s*\d{1,2})", re.MULTILINE),
            # INID 51이 줄 맨 앞에 괄호 없이 오고, 같은 줄 또는 다음 줄에 분류가 오는 형식
            re.compile(r"^\s*51\s*\n?\s*(\d{1,2}\s*[-–.]\s*\d{1,2})", re.MULTILINE),
            re.compile(r"\bClass(?:ification)?[^\d]{0,10}(\d{1,2}\s*[-.]\s*\d{1,2})", re.MULTILINE | re.IGNORECASE),
            re.compile(r"\bCl\.?[^\d]{0,6}(\d{1,2}\s*[-.]\s*\d{1,2})", re.MULTILINE | re.IGNORECASE),
            # 최후 수단: 코드와 값이 분리 추출되는 2단 레이아웃 대비 —
            # '12 - 05' 또는 '12-05, 12-08' 처럼 분류만 있는 단독 줄을 직접 탐지.
            # 페이지 번호('1 - 2') 오인 방지를 위해 서브클래스는 2자리(공식 표기)만 허용
            re.compile(
                r"^[ \t]*(\d{1,2}[ \t]*[-–][ \t]*\d{2})(?:[ \t]*[,;][ \t]*\d{1,2}[ \t]*[-–][ \t]*\d{2})*[ \t]*$",
                re.MULTILINE,
            ),
        ],
        "local_class_codes": [],
        "design_description": [
            re.compile(r"Description[:\s]*(.+?)(?:Views|Representations|$)", re.DOTALL | re.IGNORECASE),
        ],
    },
    "CNIPA": {
        "application_number": [
            re.compile(r"申请号[:\s]*([\d.]+)", re.MULTILINE),
            re.compile(r"Application\s*No[.:\s]*([\d.]+)", re.MULTILINE | re.IGNORECASE),
        ],
        "registration_number": [
            re.compile(r"专利号[:\s]*([\d.]+)", re.MULTILINE),
            re.compile(r"Patent\s*No[.:\s]*([\d.]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"授权公告号[:\s]*([\w\d.]+)", re.MULTILINE),
        ],
        "title": [
            re.compile(r"产品名称[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"名\s*称[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"Title[:\s]*(.+?)(?:\n|$)", re.MULTILINE | re.IGNORECASE),
        ],
        "applicant": [
            re.compile(r"申请人[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"专利权人[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "designer": [
            re.compile(r"设计人[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "filing_date": [
            re.compile(r"申请日[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "registration_date": [
            re.compile(r"授权公告日[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "locarno_class": [
            re.compile(r"LOC[:\s]*([\d-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"洛迦诺分类[:\s]*([\d-]+)", re.MULTILINE),
            re.compile(r"国际分类[:\s]*([\d-]+)", re.MULTILINE),
        ],
        "local_class_codes": [
            re.compile(r"分类号[:\s]*([\w\d/.]+)", re.MULTILINE),
        ],
        "design_description": [
            re.compile(r"简要说明[:\s]*(.+?)(?:附图|视图|$)", re.DOTALL),
            re.compile(r"设计要点[:\s]*(.+?)(?:\n\n|$)", re.DOTALL),
        ],
    },
    "JPO": {
        "application_number": [
            re.compile(r"出願番号[:\s]*([\w\d-]+)", re.MULTILINE),
            re.compile(r"意願\s*(\d{4}-\d+)", re.MULTILINE),
        ],
        "registration_number": [
            re.compile(r"登録番号[:\s]*([\d-]+)", re.MULTILINE),
            re.compile(r"意匠登録\s*第?\s*(\d+)\s*号?", re.MULTILINE),
        ],
        "title": [
            re.compile(r"意匠に係る物品[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"物品[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "applicant": [
            re.compile(r"出願人[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
            re.compile(r"意匠権者[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "designer": [
            re.compile(r"創作者[:\s]*(.+?)(?:\n|$)", re.MULTILINE),
        ],
        "filing_date": [
            re.compile(r"出願日[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "registration_date": [
            re.compile(r"登録日[:\s]*([\d./-]+)", re.MULTILINE),
        ],
        "locarno_class": [
            re.compile(r"ロカルノ分類[:\s]*([\d-]+)", re.MULTILINE),
            re.compile(r"LOC[:\s]*([\d-]+)", re.MULTILINE | re.IGNORECASE),
            re.compile(r"国際分類[:\s]*([\d-]+)", re.MULTILINE),
        ],
        "local_class_codes": [
            re.compile(r"日本意匠分類[:\s]*([\w\d-]+)", re.MULTILINE),
            re.compile(r"Dターム[:\s]*([\w\d-]+)", re.MULTILINE),
        ],
        "design_description": [
            re.compile(r"意匠の説明[:\s]*(.+?)(?:図面|$)", re.DOTALL),
        ],
    },
}

OFFICE_MAP = {
    "KIPO": PatentOffice.KIPO,
    "USPTO": PatentOffice.USPTO,
    "EUIPO": PatentOffice.EUIPO,
    "CNIPA": PatentOffice.CNIPA,
    "JPO": PatentOffice.JPO,
}


class GazetteParser:
    """각국 디자인 공보 PDF를 파싱하여 구조화된 데이터로 변환"""

    def __init__(self, use_vision: bool = True):
        # API 키가 없으면 Vision을 자동으로 끈다 (텍스트 추출만 사용)
        self.use_vision = use_vision and api_key_available()
        self.extractor = PDFExtractor()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_client()
        return self._client

    def parse_pdf(
        self,
        pdf_path: str,
        office: str,
        drawings_output_dir: str | None = None,
        default_locarno: str | None = None,
    ) -> DesignPatent | None:
        """단일 PDF 공보를 파싱하여 DesignPatent 반환

        default_locarno: 텍스트에서 로카르노 분류를 찾지 못했을 때 사용할 기본값
            (예: 25류만 모은 공보면 "25" 또는 "25-03"을 지정)
        """
        pdf_path = str(Path(pdf_path).resolve())
        text = self.extractor.extract_text(pdf_path)

        result = self._regex_extract(text, office)

        # 다단 레이아웃 대비: 분류를 못 찾았으면 읽기 순서로 정렬해 재추출 후 빈 항목 보완
        if not result.get("locarno_class"):
            sorted_text = self.extractor.extract_text(pdf_path, sort=True)
            retry = self._regex_extract(sorted_text, office)
            for k, v in retry.items():
                if v and not result.get(k):
                    result[k] = v

        # 핵심 서지정보(출원번호/등록번호)가 없거나, 분류·물품명이 비었으면 Vision으로 보완
        no_id = not result.get("application_number") and not result.get("registration_number")
        missing_core = not result.get("locarno_class") and not default_locarno
        if self.use_vision and (no_id or missing_core or not result.get("title")):
            result = self._vision_extract(pdf_path, office, result)

        # AI가 '확인 불가/N/A' 등으로 답한 placeholder와 형식이 어긋난 값 제거
        result = _sanitize_fields(result)

        if not result.get("application_number") and not result.get("registration_number"):
            # 파일 1개=디자인 1건 전제이므로, 번호를 못 찾으면 파일명을 식별자로 사용
            # (등록증 사본 등에서 파일명이 곧 등록번호인 경우가 많음)
            result["application_number"] = Path(pdf_path).stem

        img_dir = drawings_output_dir or str(Path(pdf_path).parent / "drawings")
        images = self.extractor.extract_images(
            pdf_path, img_dir, prefix=Path(pdf_path).stem + "_"
        )
        drawings = self._classify_drawings(images)

        app_num = result.get("application_number") or result.get("registration_number") or Path(pdf_path).stem
        patent = DesignPatent(
            application_number=app_num,
            registration_number=result.get("registration_number"),
            patent_office=OFFICE_MAP.get(office.upper(), PatentOffice.OTHER),
            title=result.get("title") or Path(pdf_path).stem,
            applicant=result.get("applicant"),
            designer=result.get("designer"),
            filing_date=_parse_date_flexible(result.get("filing_date")),
            registration_date=_parse_date_flexible(result.get("registration_date")),
            locarno_class=_normalize_locarno(result.get("locarno_class") or default_locarno) or "99-99",
            local_class_codes=[c for c in [result.get("local_class_codes")] if c],
            design_description=result.get("design_description"),
            drawings=drawings,
            metadata={"source_pdf": pdf_path},
        )
        patent.id = f"{office.upper()}-{app_num}"
        return patent

    def parse_directory(
        self,
        directory: str,
        office: str,
        drawings_output_dir: str | None = None,
        recursive: bool = True,
        default_locarno: str | None = None,
        progress_callback=None,
    ) -> list[DesignPatent]:
        """디렉토리 내 모든 PDF를 파싱"""
        dir_path = Path(directory)
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = sorted(dir_path.glob(pattern))

        patents = []
        total = len(pdf_files)
        for i, pdf in enumerate(pdf_files, 1):
            patent = self.parse_pdf(str(pdf), office, drawings_output_dir, default_locarno)
            if patent:
                patents.append(patent)
            if progress_callback:
                progress_callback(i, total, patent)

        return patents

    def to_excel(self, patents: list[DesignPatent], output_path: str):
        """파싱 결과를 Excel 파일로 저장"""
        import pandas as pd

        rows = []
        for p in patents:
            drawing_files = ";".join(
                d.file_path for d in p.drawings if d.file_path
            )
            rows.append({
                "application_number": p.application_number,
                "registration_number": p.registration_number or "",
                "patent_office": p.patent_office.value,
                "title": p.title,
                "locarno_class": p.locarno_class,
                "applicant": p.applicant or "",
                "designer": p.designer or "",
                "filing_date": str(p.filing_date) if p.filing_date else "",
                "registration_date": str(p.registration_date) if p.registration_date else "",
                "design_description": p.design_description or "",
                "local_class_codes": ";".join(p.local_class_codes),
                "drawing_files": drawing_files,
                "source_pdf": p.metadata.get("source_pdf", ""),
            })

        df = pd.DataFrame(rows)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)

    def _regex_extract(self, text: str, office: str) -> dict:
        """정규식으로 서지사항 추출.

        한 패턴이 부적합한 값(주소·placeholder 등)을 잡으면 버리고
        다음 패턴으로 계속 시도한다.
        """
        patterns = OFFICE_PATTERNS.get(office.upper(), {})
        result = {}

        for field, regexes in patterns.items():
            for regex in regexes:
                match = regex.search(text)
                if not match:
                    continue
                value = match.group(1).strip()
                if field == "design_description":
                    value = value[:1000]
                if not _candidate_ok(field, value):
                    continue  # 부적합 → 다음 패턴 시도
                result[field] = value
                break

        return result

    def _vision_extract(self, pdf_path: str, office: str, partial: dict) -> dict:
        """Claude Vision으로 PDF 페이지를 분석하여 서지사항 추출"""
        import base64

        # 등록증 사본 등은 앞쪽이 인증 표지이고 실제 서지정보가 뒤에 있으므로
        # 충분한 페이지(최대 5쪽)를 AI에 보여준다.
        rendered = self.extractor.render_pages(
            pdf_path,
            str(Path(pdf_path).parent / ".vision_cache"),
            dpi=150,
            max_pages=5,
        )
        if not rendered:
            return partial

        content: list[dict] = []
        for img_path in rendered:
            img_data = Path(img_path).read_bytes()
            b64 = base64.standard_b64encode(img_data).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })

        field_names = {
            "KIPO": "출원번호, 등록번호, 물품명칭, 출원인, 창작자, 출원일, 등록일, 로카르노분류, 디자인분류, 디자인의설명",
            "USPTO": "Application No, Patent No, Title, Assignee, Inventor, Filed date, Patent date, LOC class, US class, Claim",
            "EUIPO": "Application No, Registration No, Product, Holder, Designer, Filing date, Registration date, Locarno class, Description",
            "CNIPA": "申请号, 专利号, 产品名称, 申请人, 设计人, 申请日, 授权公告日, 洛迦诺分类, 分类号, 简要说明",
            "JPO": "出願番号, 登録番号, 意匠に係る物品, 出願人, 創作者, 出願日, 登録日, ロカルノ分類, 日本意匠分類, 意匠の説明",
        }

        content.append({
            "type": "text",
            "text": f"""이 디자인 공보 PDF({office} 발행)에서 다음 정보를 추출해주세요:
{field_names.get(office.upper(), field_names["KIPO"])}

중요: 문서에서 찾을 수 없는 항목은 반드시 null 로 답하세요.
"확인 불가", "N/A", "없음" 같은 문구를 값으로 넣지 마세요.

JSON으로 응답해주세요:
{{
  "application_number": "출원번호 또는 null",
  "registration_number": "등록번호 또는 null",
  "title": "물품명 또는 null",
  "applicant": "출원인/권리자 또는 null",
  "designer": "창작자/디자이너 또는 null",
  "filing_date": "출원일 YYYY-MM-DD 또는 null",
  "registration_date": "등록일 YYYY-MM-DD 또는 null",
  "locarno_class": "로카르노 분류 XX-XX 또는 null",
  "local_class_codes": "각국 분류코드 또는 null",
  "design_description": "디자인 설명 (최대 500자) 또는 null"
}}""",
        })

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{"role": "user", "content": content}],
            )
            text = response.content[0].text
            start = text.index("{")
            end = text.rindex("}") + 1
            vision_result = json.loads(text[start:end])

            for k, v in vision_result.items():
                if v and not partial.get(k):
                    partial[k] = str(v)
        except Exception:
            pass

        return partial

    def _classify_drawings(self, images: list[dict]) -> list[DrawingImage]:
        """추출된 이미지를 도면 유형별로 분류"""
        drawings = []
        if not images:
            return drawings

        large_images = sorted(images, key=lambda x: x["width"] * x["height"], reverse=True)

        view_order = [
            DrawingType.REPRESENTATIVE,
            DrawingType.FRONT,
            DrawingType.BACK,
            DrawingType.LEFT,
            DrawingType.RIGHT,
            DrawingType.TOP,
            DrawingType.BOTTOM,
            DrawingType.PERSPECTIVE,
        ]

        for i, img in enumerate(large_images):
            dtype = view_order[i] if i < len(view_order) else DrawingType.REFERENCE
            drawings.append(DrawingImage(
                drawing_type=dtype,
                file_path=img["path"],
                description=f"page {img['page']}, {img['width']}x{img['height']}px",
            ))

        return drawings


_PLACEHOLDER_PATTERNS = re.compile(
    r"확인\s*불가|알\s*수\s*없|미기재|기재\s*없|미표시|미포함|명시되지|정보\s*없음|해당\s*정보|해당\s*없"
    r"|^n/?a\b|not\s*(?:specified|available|provided|found|indicated)|unknown|없음$",
    re.IGNORECASE,
)

_FIELD_FORMATS: dict[str, re.Pattern] = {
    # 번호류: 숫자가 4개 이상 포함되어야 함
    "application_number": re.compile(r"(?:\D*\d){4,}"),
    "registration_number": re.compile(r"(?:\D*\d){4,}"),
    "publication_number": re.compile(r"(?:\D*\d){4,}"),
    # 분류: XX-XX / XX.XX / XX 형태
    "locarno_class": re.compile(r"^\s*\(?\s*\d{1,2}\s*(?:[-–.]\s*\d{1,2})?\s*\)?\s*$"),
    # 날짜: 숫자 포함
    "filing_date": re.compile(r"\d"),
    "registration_date": re.compile(r"\d"),
}


# 언어코드 접두어 (다국어 병기 공보의 'ES - ...', 'EN - ...' 등)
_LANG_PREFIX = re.compile(r"^[A-Z]{2}\s*[-–]\s*")

# 주소로 보이는 줄 (출원인 칸에 주소가 들어가는 것 방지)
_ADDRESS_LIKE = re.compile(
    r"^\d|\b(?:Room|Building|Road|Street|Avenue|Floor|District|Blvd|Ave\.?|No\.\s*\d)\b",
    re.IGNORECASE,
)
_COMPANY_LIKE = re.compile(
    r"\b(?:Co\.|Ltd|Inc|Corp|GmbH|LLC|S\.?L\.?|S\.?A\.?|AG|BV|Oy|AB|주식회사|유한회사|株式会社|有限公司)\b",
    re.IGNORECASE,
)


def _candidate_ok(field: str, value: str) -> bool:
    """정규식 후보 값이 해당 필드로 적합한지 검사 (부적합하면 다음 패턴 시도)."""
    if not value or _PLACEHOLDER_PATTERNS.search(value):
        return False
    fmt = _FIELD_FORMATS.get(field)
    if fmt and not fmt.search(value):
        return False
    if field in ("applicant", "designer"):
        if _ADDRESS_LIKE.search(value) and not _COMPANY_LIKE.search(value):
            return False
    return True


def _sanitize_fields(result: dict) -> dict:
    """AI/정규식 추출 결과에서 placeholder 답변과 형식 불일치 값을 제거.

    예: '확인 불가 (문서에 미기재)', 'N/A' 같은 값이 출원번호·분류로
    저장되는 것을 방지한다.
    """
    cleaned: dict = {}
    for k, v in result.items():
        if v is None:
            continue
        s = str(v).strip()
        if not s or _PLACEHOLDER_PATTERNS.search(s):
            continue
        fmt = _FIELD_FORMATS.get(k)
        if fmt and not fmt.search(s):
            continue
        if k == "title":
            s = _LANG_PREFIX.sub("", s).strip() or s
        if k in ("applicant", "designer"):
            # 회사명 표식 없이 주소 형태면 잘못 잡힌 것 → 버림
            if _ADDRESS_LIKE.search(s) and not _COMPANY_LIKE.search(s):
                continue
        cleaned[k] = s
    return cleaned


def _normalize_locarno(value: str | None) -> str | None:
    """로카르노 분류 표기를 'XX-XX' 형식으로 정규화.

    예: '2503' -> '25-03', '25-3' -> '25-03', '25' -> '25', 'LOC 25-03' -> '25-03'
    """
    if not value:
        return None
    value = str(value).strip()

    # 'XX-XX' / 'XX-X' / 'XX.XX' (대시·en대시·점 구분) 형태 추출
    m = re.search(r"(\d{1,2})\s*[-–.]\s*(\d{1,2})", value)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # 붙어있는 4자리 (예: 2503)
    m = re.search(r"\b(\d{2})(\d{2})\b", value)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # 클래스 번호만 (예: 25)
    m = re.search(r"\b(\d{1,2})\b", value)
    if m:
        return f"{int(m.group(1)):02d}"

    return value


def _parse_date_flexible(date_str: str | None) -> date | None:
    """다양한 날짜 형식을 파싱"""
    if not date_str:
        return None

    date_str = date_str.strip()

    for fmt_re, fmt_parse in [
        (r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", None),
        (r"(\d{4})(\d{2})(\d{2})", None),
    ]:
        m = re.match(fmt_re, date_str)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue

    us_match = re.match(
        r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", date_str, re.IGNORECASE
    )
    if us_match:
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            "january": 1, "february": 2, "march": 3, "april": 4,
            "june": 6, "july": 7, "august": 8, "september": 9,
            "october": 10, "november": 11, "december": 12,
        }
        month = months.get(us_match.group(1).lower())
        if month:
            try:
                return date(int(us_match.group(3)), month, int(us_match.group(2)))
            except ValueError:
                pass

    # 유럽식 DD.MM.YYYY / DD-MM-YYYY / DD/MM/YYYY
    eu_match = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", date_str)
    if eu_match:
        try:
            return date(int(eu_match.group(3)), int(eu_match.group(2)), int(eu_match.group(1)))
        except ValueError:
            pass

    return None
