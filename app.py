"""DesignMap 웹 화면 (로컬 전용).

터미널 명령 대신 브라우저 버튼으로 전체 워크플로우를 조작합니다.
PDF와 AI 열쇠가 내 컴퓨터 밖으로 나가지 않습니다.

실행:  streamlit run app.py
"""
from __future__ import annotations

# macOS 보호 폴더에서 getcwd PermissionError 방지 (CLI와 동일한 안전장치)
import os as _os
try:
    _os.getcwd()
except OSError:
    try:
        _os.chdir(_os.path.expanduser("~"))
    except OSError:
        pass

import asyncio
import json
from collections import Counter
from pathlib import Path

import streamlit as st

from src.utils.ai import api_key_available, friendly_api_error
from src.utils.database import Database
from src.utils.export import (
    select_representative_images,
    to_excel_bytes,
    to_excel_with_images_bytes,
)
from src.utils.paths import data_path
from src.models import ClassificationCriteria, ClassificationResult
from src.models.design_patent import PatentOffice, DrawingImage, DesignPatent

CRITERIA_FILE = data_path("proposed_criteria.json")
RESULTS_FILE = data_path("classification_results.json")
REPORT_FILE = data_path("trend_report.md")

st.set_page_config(page_title="DesignMap 디자인권 분류", page_icon="📐", layout="wide")


def run_async(coro):
    return asyncio.run(coro)


def row_to_patent(row: dict) -> DesignPatent:
    drawings = []
    if row.get("drawings_json"):
        try:
            for d in json.loads(row["drawings_json"]):
                drawings.append(DrawingImage(**d))
        except (json.JSONDecodeError, TypeError):
            pass
    local_codes = []
    if row.get("local_class_codes"):
        try:
            local_codes = json.loads(row["local_class_codes"])
        except (json.JSONDecodeError, TypeError):
            pass
    return DesignPatent(
        id=row.get("id"),
        application_number=row["application_number"],
        registration_number=row.get("registration_number"),
        publication_number=row.get("publication_number"),
        patent_office=PatentOffice(row.get("patent_office", "OTHER")),
        title=row["title"],
        applicant=row.get("applicant"),
        designer=row.get("designer"),
        filing_date=row.get("filing_date"),
        registration_date=row.get("registration_date"),
        publication_date=row.get("publication_date"),
        locarno_class=row["locarno_class"],
        local_class_codes=local_codes,
        design_description=row.get("design_description"),
        drawings=drawings,
        metadata=json.loads(row.get("metadata_json", "{}")) if row.get("metadata_json") else {},
    )


async def _db_counts() -> dict:
    from sqlalchemy import text

    db = Database()
    await db.init()
    async with db.session_factory() as s:
        total = (await s.execute(text("SELECT COUNT(*) FROM design_patents"))).scalar() or 0
        screened = (await s.execute(text("SELECT COUNT(*) FROM screening_results"))).scalar() or 0
        passed = (await s.execute(text("SELECT COUNT(*) FROM screening_results WHERE passed=1"))).scalar() or 0
        classified = (await s.execute(text("SELECT COUNT(*) FROM classification_results"))).scalar() or 0
    return {"total": total, "screened": screened, "passed": passed, "classified": classified}


STATUS_LABELS = {
    "proposed": ("🟡", "제안됨 — 검토가 필요합니다"),
    "reviewed": ("🟠", "검토 중"),
    "approved": ("🟢", "승인됨 — 분류 실행 준비 완료"),
    "rejected": ("🔴", "반려됨"),
}
PEST_LABELS = {"political": "정치", "economic": "경제", "social": "사회", "technological": "기술"}


def pick_directory() -> str | None:
    """네이티브 폴더 선택 대화상자를 띄워 선택한 폴더 경로를 반환.

    로컬 실행 전용. tkinter를 별도 프로세스(메인 스레드)에서 실행해
    macOS에서 스레드 충돌 없이 폴더 선택창을 띄운다.
    """
    import subprocess
    import sys

    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw()\n"
        "try:\n"
        "    r.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "p = filedialog.askdirectory(title='PDF 폴더 선택')\n"
        "print(p or '')\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180,
        )
        path = (out.stdout or "").strip()
        return path or None
    except Exception:
        return None


def markdown_to_docx_bytes(md_text: str) -> bytes:
    """마크다운 리포트를 편집 가능한 Word(.docx) 바이트로 변환."""
    import io
    import re

    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt

    KOREAN_FONT = "Malgun Gothic"

    def _set_font(element_rpr):
        """rPr 요소에 한글 폰트를 모든 스크립트(ascii/hAnsi/eastAsia/cs)로 지정."""
        rfonts = element_rpr.get_or_add_rFonts()
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), KOREAN_FONT)

    doc = Document()

    # 한글 폰트를 명시하지 않으면 Word가 동아시아 글꼴을 중국어 폰트로 대체해
    # 한글이 깨져 보일 수 있다. 본문뿐 아니라 제목(Heading)·목록 등
    # **모든 스타일**에 지정해야 한다 (Normal만 지정하면 제목이 깨짐).
    for style in doc.styles:
        try:
            _set_font(style.element.get_or_add_rPr())
        except (AttributeError, TypeError):
            continue  # 폰트를 가질 수 없는 스타일(표/번호 매기기 등)은 건너뜀
    doc.styles["Normal"].font.size = Pt(10.5)

    def add_runs(paragraph, text: str):
        for part in re.split(r"(\*\*.+?\*\*)", text):
            if part.startswith("**") and part.endswith("**"):
                paragraph.add_run(part[2:-2]).bold = True
            elif part:
                paragraph.add_run(part)

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # 표: |...| 다음 줄이 |---| 형태
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?[\s:\-\|]+\|?$", lines[i + 1].strip()) and "-" in lines[i + 1]:
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            table = doc.add_table(rows=1, cols=len(header))
            try:
                table.style = "Table Grid"
            except Exception:
                pass
            for j, h in enumerate(header):
                add_runs(table.rows[0].cells[j].paragraphs[0], h)
            for r in body:
                cells = table.add_row().cells
                for j, c in enumerate(r):
                    if j < len(cells):
                        add_runs(cells[j].paragraphs[0], c)
            doc.add_paragraph("")
            continue
        if not line:
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)))
        elif re.match(r"^[-*]\s+", line):
            add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^[-*]\s+", "", line))
        elif re.match(r"^\d+\.\s+", line):
            add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\d+\.\s+", "", line))
        elif re.match(r"^-{3,}$", line):
            pass
        else:
            add_runs(doc.add_paragraph(), line)
        i += 1

    # 스타일이 덮어써질 수 있으므로, 실제 글자(run) 하나하나에도 직접 지정한다.
    def _apply_to_runs(paragraphs):
        for p in paragraphs:
            for run in p.runs:
                run.font.name = KOREAN_FONT
                _set_font(run._element.get_or_add_rPr())

    _apply_to_runs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _apply_to_runs(cell.paragraphs)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def offer_report_downloads(md_text: str, key_prefix: str = ""):
    """리포트를 Markdown/Word로 내려받는 버튼."""
    st.download_button("⬇️ 리포트 (Markdown .md)", md_text,
                       file_name="trend_report.md", key=f"{key_prefix}md")
    try:
        docx_bytes = markdown_to_docx_bytes(md_text)
        st.download_button(
            "⬇️ 리포트 (Word .docx)", docx_bytes,
            file_name="trend_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"{key_prefix}docx",
        )
    except ImportError:
        st.caption("Word(.docx) 다운로드에는 python-docx가 필요합니다. 코드 업데이트 후 다시 실행하세요.")
    except Exception as e:
        st.caption(f"Word 변환 오류: {e}")


def render_status_banner(status: str):
    icon, label = STATUS_LABELS.get(status, ("⚪", status))
    msg = f"{icon} 현재 상태: **{label}**"
    (st.success if status == "approved" else st.warning)(msg)


def render_criteria(crit):
    """분류 기준을 사람이 읽기 좋게 표시 (JSON 대신 표·태그)."""
    st.markdown(f"### 📋 {crit.name}")
    if crit.description:
        st.caption(crit.description)
    if getattr(crit, "revision_notes", None):
        st.markdown(f"> ✏️ **최근 수정 요청:** {crit.revision_notes}")

    st.markdown("#### 🧩 분류 차원 — 디자인을 나누는 기준 축")
    if crit.dimensions:
        st.dataframe(
            [
                {
                    "차원": d.name,
                    "설명": d.description,
                    "분류 값": " · ".join(d.values),
                    "가중치": d.weight,
                }
                for d in crit.dimensions
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("아직 분류 차원이 없습니다.")

    if crit.trend_keywords:
        st.markdown("#### 🏷️ 트렌드 키워드")
        st.markdown("  ".join(f"`{k}`" for k in crit.trend_keywords))

    if crit.pest_factors:
        st.markdown("#### 🌐 PEST 분석 — 트렌드에 영향을 주는 외부 요인")
        st.dataframe(
            [
                {
                    "구분": PEST_LABELS.get(f.category.value, f.category.value),
                    "요인": f.factor,
                    "영향도": f.impact_level,
                    "관련성": f.relevance,
                }
                for f in crit.pest_factors
            ],
            use_container_width=True,
            hide_index=True,
        )


# ─────────────────────────────── 사이드바: 상태 ───────────────────────────────
APP_VERSION = "v4.2 (리포트 관점 이력)"

st.sidebar.title("📐 DesignMap")
st.sidebar.caption(f"디자인권 분류 · 트렌드 예측 · {APP_VERSION}")

key_ok = api_key_available()
st.sidebar.markdown("**AI 열쇠**: " + ("🟢 설정됨" if key_ok else "🔴 없음"))
if not key_ok:
    st.sidebar.warning("propose/classify/report 단계는 AI 열쇠가 필요합니다.\n터미널에서 `export ANTHROPIC_API_KEY=...` 후 다시 실행하세요.")

try:
    counts = run_async(_db_counts())
    st.sidebar.markdown(
        f"**진행 상황**\n\n"
        f"- 입력된 디자인권: {counts['total']}건\n"
        f"- 스크리닝: {counts['screened']}건 (통과 {counts['passed']})\n"
        f"- 분류 완료: {counts['classified']}건"
    )
except Exception as e:
    st.sidebar.error(f"DB 상태 조회 실패: {e}")

st.sidebar.divider()
if st.sidebar.button("💾 데이터 백업"):
    from src.utils.paths import backup_data

    try:
        dest = backup_data()
        st.sidebar.success(f"백업 완료:\n{dest}")
    except Exception as e:
        st.sidebar.error(f"백업 실패: {e}")

step = st.sidebar.radio(
    "단계 선택",
    [
        "① PDF 읽기",
        "② 스크리닝",
        "③ 분류 기준 제안",
        "④ 기준 수정/승인",
        "⑤ 분류 실행",
        "⑥ 트렌드 리포트",
        "⑦ 결과 보기 / 내려받기",
    ],
)


def show_ai_error(e: Exception):
    friendly = friendly_api_error(e)
    if friendly:
        st.error(friendly)
    else:
        st.error(f"오류: {e}")


# ─────────────────────────────── ① PDF 읽기 ───────────────────────────────
if step.startswith("①"):
    st.header("① PDF 원문공보 읽기")
    st.write("저장해 둔 디자인 공보 PDF 폴더에서 서지정보와 도면을 추출합니다.")

    with st.expander("🗑️ 새로 시작하기 — 기존 데이터 초기화"):
        st.warning("아래를 실행하면 지금까지의 **모든 데이터(수집·스크리닝·분류·리포트)가 삭제**되고 처음부터 다시 시작합니다. "
                   "삭제 직전 자동으로 백업(data/backups/)이 만들어집니다.")
        confirm = st.checkbox("네, 모든 데이터를 삭제하고 초기화합니다.")
        if st.button("🗑️ 초기화 실행", disabled=not confirm):
            from src.utils.paths import reset_data

            try:
                backup_dir = reset_data(backup=True)
                for k in ["pdf_folder"]:
                    st.session_state.pop(k, None)
                st.success(f"초기화 완료. (백업: {backup_dir})")
                st.rerun()
            except Exception as e:
                st.error(f"초기화 실패: {e}")

    st.divider()

    if st.button("📁 폴더 찾아보기"):
        picked = pick_directory()
        if picked:
            st.session_state["pdf_folder"] = picked
        else:
            st.info("폴더를 선택하지 않았습니다. 경로를 직접 입력해도 됩니다.")

    folder = st.text_input(
        "PDF가 있는 폴더 경로", key="pdf_folder",
        placeholder="위 '폴더 찾아보기'로 선택하거나 경로를 직접 입력",
    )
    office = st.selectbox("발행 특허청", ["KIPO", "USPTO", "EUIPO", "CNIPA", "JPO"])
    no_vision = st.checkbox("AI Vision OCR 끄기 (텍스트 추출만, 빠름/무료)", value=False)

    with st.expander("🔍 진단 — PDF에서 글자가 어떻게 읽히는지 확인 (분류가 99-99로 나올 때)"):
        st.write("폴더의 첫 번째 PDF에서 추출된 실제 텍스트와 인식 결과를 보여줍니다. "
                 "이 내용을 복사해 개발자(AI)에게 보여주면 원인을 정확히 찾을 수 있습니다.")
        if st.button("진단 실행"):
            if not folder or not Path(folder).exists():
                st.error("먼저 위에서 폴더를 지정하세요.")
            else:
                pdfs = sorted(Path(folder).glob("**/*.pdf"))
                if not pdfs:
                    st.error("폴더에 PDF가 없습니다.")
                else:
                    from src.collectors.pdf_parser import PDFExtractor, GazetteParser, _normalize_locarno

                    target = pdfs[0]
                    text = PDFExtractor.extract_text(str(target))
                    st.markdown(f"**파일:** `{target.name}` · 추출된 글자 수: **{len(text.strip())}자**")
                    if len(text.strip()) < 30:
                        st.error("⚠️ 이 PDF는 글자가 거의 추출되지 않습니다 → **스캔(이미지) PDF**입니다. "
                                 "정규식으로는 읽을 수 없고, 'AI Vision OCR 끄기'를 **해제**하고 읽어야 합니다(크레딧 소모).")
                    parser = GazetteParser(use_vision=False)
                    fields = parser._regex_extract(text, office)
                    st.markdown("**인식된 항목:**")
                    st.json({
                        "출원번호": fields.get("application_number"),
                        "등록번호": fields.get("registration_number"),
                        "물품명": fields.get("title"),
                        "출원인": fields.get("applicant"),
                        "로카르노(원문)": fields.get("locarno_class"),
                        "로카르노(정규화)": _normalize_locarno(fields.get("locarno_class")),
                    })

                    # 물품명·출원인 관련 원문 줄 표시 (원인 파악용)
                    lines = text.split("\n")
                    interesting = []
                    for idx, ln in enumerate(lines):
                        s = ln.strip()
                        if not s:
                            continue
                        import re as _re
                        if (_re.search(r"\b(?:EN|ES|FR|DE|IT)\s*[-–]", s)
                                or _re.match(r"^\(?5[14]\)?\b", s)
                                or _re.match(r"^\(?7[234]\)?\b", s)
                                or _re.search(r"\b(?:Co\.|Ltd|Inc|GmbH|LLC)\b", s, _re.IGNORECASE)):
                            interesting.append(f"[{idx + 1}행] {ln}")
                    st.markdown("**물품명(54/EN)·출원인(73/74) 관련 원문 줄:** — 이 부분을 복사해서 공유해주세요")
                    st.code("\n".join(interesting[:40]) or "(관련 줄을 찾지 못함)")

                    st.markdown("**추출 텍스트 앞부분 (2,000자):**")
                    st.code(text[:2000] or "(비어 있음)")
                    st.download_button("⬇️ 전체 추출 텍스트 (.txt)", text,
                                       file_name=f"{target.stem}_extracted.txt")

    translate_titles = st.checkbox(
        "물품명·출원인을 영문으로 통일 (일본어·중국어를 AI로 번역, 소량 크레딧)",
        value=key_ok, disabled=not key_ok,
    )

    st.divider()
    with st.expander("🔧 이미 불러온 데이터의 물품명·출원인 다시 추출 (무료, AI 미사용)"):
        st.write("추출 규칙이 개선되었을 때, PDF를 다시 통째로 읽지 않고 "
                 "**물품명·출원인·로카르노만** 원본 PDF에서 다시 뽑아 고칩니다. "
                 "잘못 들어간 값(언어 코드 'FR', 타언어 물품명 등)은 빈칸으로 정리됩니다.")
        if st.button("다시 추출 실행"):
            from src.collectors.pdf_parser import GazetteParser

            async def _reextract():
                db = Database()
                await db.init()
                rows = await db.get_all_patents()
                parser = GazetteParser(use_vision=False)
                fixed, missing, unchanged = 0, 0, 0
                prog = st.progress(0.0, text="다시 추출 중...")
                for i, r in enumerate(rows, 1):
                    meta = json.loads(r.get("metadata_json") or "{}")
                    src = meta.get("source_pdf")
                    if not src or not Path(src).exists():
                        missing += 1
                    else:
                        try:
                            new = parser.reextract_fields(src, r.get("patent_office", "EUIPO"))
                        except Exception:
                            new = {}
                        p = row_to_patent(r)
                        before = (p.title, p.applicant, p.locarno_class)
                        p.title = new.get("title") or Path(src).stem
                        p.applicant = new.get("applicant")
                        from src.collectors.pdf_parser import _normalize_locarno
                        p.locarno_class = _normalize_locarno(new.get("locarno_class")) or p.locarno_class
                        if (p.title, p.applicant, p.locarno_class) != before:
                            await db.save_patent(p)
                            fixed += 1
                        else:
                            unchanged += 1
                    prog.progress(i / len(rows), text=f"{i}/{len(rows)}건 처리")
                return fixed, unchanged, missing

            try:
                fixed, unchanged, missing = run_async(_reextract())
                st.success(f"완료 — 수정 {fixed}건 · 변경 없음 {unchanged}건")
                if missing:
                    st.warning(f"원본 PDF를 찾을 수 없는 {missing}건은 건너뛰었습니다. "
                               "(PDF 폴더가 이동·삭제된 경우)")
                st.rerun()
            except Exception as e:
                st.error(f"다시 추출 실패: {e}")

    with st.expander("🤖 빈칸인 물품명·출원인을 AI로 채우기 (빈칸만, 소량 크레딧)"):
        st.write("규칙으로 읽지 못해 **비어 있는 항목만** AI가 원본 PDF를 보고 채웁니다. "
                 "이미 값이 있는 건은 건드리지 않아 비용이 최소화됩니다.")

        async def _count_blanks():
            db = Database()
            await db.init()
            rows = await db.get_all_patents()
            blanks = []
            for r in rows:
                meta = json.loads(r.get("metadata_json") or "{}")
                src = meta.get("source_pdf")
                need = []
                title = (r.get("title") or "").strip()
                # 물품명이 비었거나 파일명으로 대체된 경우도 보완 대상
                if not title or (src and title == Path(src).stem):
                    need.append("title")
                if not (r.get("applicant") or "").strip():
                    need.append("applicant")
                if need and src and Path(src).exists():
                    blanks.append((r, need))
            return blanks

        try:
            blanks = run_async(_count_blanks())
        except Exception:
            blanks = []

        st.markdown(f"**보완이 필요한 건: {len(blanks)}건**")
        if blanks and st.button(f"🤖 {len(blanks)}건 AI로 채우기", disabled=not key_ok):
            from src.collectors.pdf_parser import GazetteParser

            async def _fill():
                db = Database()
                await db.init()
                parser = GazetteParser(use_vision=True)
                prog = st.progress(0.0, text="AI 보완 중...")
                filled = 0
                for i, (r, need) in enumerate(blanks, 1):
                    meta = json.loads(r.get("metadata_json") or "{}")
                    got = parser.vision_fill_fields(
                        meta["source_pdf"], r.get("patent_office", "EUIPO"), need
                    )
                    if got:
                        p = row_to_patent(r)
                        if got.get("title"):
                            p.title = got["title"]
                        if got.get("applicant"):
                            p.applicant = got["applicant"]
                        await db.save_patent(p)
                        filled += 1
                    prog.progress(i / len(blanks), text=f"{i}/{len(blanks)}건 · 채움 {filled}")
                return filled

            try:
                filled = run_async(_fill())
                st.success(f"{filled}건 보완 완료")
                st.rerun()
            except Exception as e:
                show_ai_error(e)

    with st.expander("🌐 이미 불러온 데이터의 영문 통일 (다시 읽을 필요 없음)"):
        st.write("DB에 저장된 **물품명**을 영문으로 통일합니다 "
                 "(스페인어·프랑스어·일본어 등 모든 언어 → 영어, 이미 영어면 그대로). "
                 "**출원인**은 고유명사이므로 한자·가나인 경우만 로마자로 바꿉니다.")
        if st.button("영문 통일 실행", disabled=not key_ok):
            from src.utils.translate import (
                needs_english_normalization, needs_translation, translate_to_english,
            )

            async def _translate_existing():
                db = Database()
                await db.init()
                rows = await db.get_all_patents()
                t_targets = [r for r in rows if needs_english_normalization(r.get("title"))]
                a_targets = [r for r in rows if needs_translation(r.get("applicant"))]
                if not t_targets and not a_targets:
                    return 0, 0, 0

                t_map = translate_to_english([r["title"] for r in t_targets], kind="title") \
                    if t_targets else {}
                a_map = translate_to_english([r["applicant"] for r in a_targets], kind="applicant") \
                    if a_targets else {}

                changed_t = changed_a = 0
                for r in {id(x): x for x in (t_targets + a_targets)}.values():
                    p = row_to_patent(r)
                    meta = dict(p.metadata or {})
                    hit = False
                    if r.get("title") in t_map:
                        meta["original_title"] = r["title"]
                        p.title = t_map[r["title"]]
                        changed_t += 1
                        hit = True
                    if r.get("applicant") in a_map:
                        meta["original_applicant"] = r["applicant"]
                        p.applicant = a_map[r["applicant"]]
                        changed_a += 1
                        hit = True
                    if hit:
                        p.metadata = meta
                        await db.save_patent(p)
                return len(t_targets) + len(a_targets), changed_t, changed_a

            with st.spinner("AI가 물품명·출원인 번역 중..."):
                try:
                    total_t, changed_t, changed_a = run_async(_translate_existing())
                    if total_t == 0:
                        st.info("영문 통일이 필요한 항목이 없습니다.")
                    else:
                        st.success(f"영문 변경 완료 — 물품명 {changed_t}건, 출원인 {changed_a}건 "
                                   "(원문은 보존됨)")
                except Exception as e:
                    show_ai_error(e)

    if st.button("PDF 읽기 시작", type="primary"):
        if not folder or not Path(folder).exists():
            st.error("폴더 경로가 올바르지 않습니다.")
        else:
            from src.collectors.pdf_parser import GazetteParser

            progress = st.progress(0.0, text="시작 준비 중...")

            def cb(done, total, patent):
                pct = done / total if total else 1.0
                progress.progress(pct, text=f"{done}/{total}개 PDF 처리 ({pct*100:.0f}%)")

            if True:
                try:
                    parser = GazetteParser(use_vision=not no_vision)
                    patents = parser.parse_directory(
                        folder, office, progress_callback=cb,
                    )
                    if patents:
                        parser.to_excel(patents, data_path("parsed_patents.xlsx"))

                        async def _save():
                            db = Database()
                            await db.init()
                            for p in patents:
                                await db.save_patent(p)

                        if translate_titles and key_ok:
                            from src.utils.translate import (
                                needs_english_normalization, needs_translation,
                                translate_to_english,
                            )

                            cjk_titles = [p.title for p in patents if needs_english_normalization(p.title)]
                            cjk_apps = [p.applicant for p in patents if needs_translation(p.applicant)]
                            if cjk_titles or cjk_apps:
                                progress.progress(1.0, text="물품명·출원인 영문 번역 중... (AI)")
                                t_map = translate_to_english(cjk_titles, kind="title") if cjk_titles else {}
                                a_map = translate_to_english(cjk_apps, kind="applicant") if cjk_apps else {}
                                for p in patents:
                                    meta = dict(p.metadata or {})
                                    if p.title in t_map:
                                        meta["original_title"] = p.title
                                        p.title = t_map[p.title]
                                    if p.applicant in a_map:
                                        meta["original_applicant"] = p.applicant
                                        p.applicant = a_map[p.applicant]
                                    p.metadata = meta
                        run_async(_save())
                    st.success(f"{len(patents)}건 추출 완료 → DB 저장됨")
                    if patents:
                        loc = Counter(p.locarno_class for p in patents)
                        st.write("**로카르노 분류 분포:**", dict(loc.most_common()))
                        st.dataframe(
                            [
                                {
                                    "출원번호": p.application_number,
                                    "물품명": p.title,
                                    "로카르노": p.locarno_class,
                                    "출원인": p.applicant or "",
                                    "추출된 도면 수": len(p.drawings),
                                }
                                for p in patents[:200]
                            ],
                            use_container_width=True,
                        )
                        st.caption("※ '추출된 도면 수'는 PDF에서 뽑아낸 이미지 개수입니다 "
                                   "(대표도·정면도·사시도 등 모든 도면과 문서 내 기타 이미지 포함). "
                                   "이미지 파일은 PDF 폴더 옆 drawings 폴더에 저장됩니다.")
                except Exception as e:
                    show_ai_error(e)


# ─────────────────────────────── ② 스크리닝 ───────────────────────────────
elif step.startswith("②"):
    st.header("② 1차 스크리닝")
    st.write("분석 대상과 관계없는 디자인을 걸러 노이즈를 줄입니다.")

    st.caption("불러온 전체 디자인권을 대상으로 합니다. (로카르노는 사전 정리 전제)")
    keywords = st.text_input("포함 키워드 (콤마 구분, 선택)")
    exclude = st.text_input("제외 키워드 (콤마 구분, 선택)")
    no_ai = st.checkbox("AI 없이 규칙 기반만 (열쇠/비용 불필요, 빠름)", value=not key_ok)

    if st.button("스크리닝 시작", type="primary"):
        if True:
            from src.screening.screener import DesignScreener

            kw = [x.strip() for x in keywords.split(",")] if keywords else None
            ex = [x.strip() for x in exclude.split(",")] if exclude else None
            use_ai = not no_ai and key_ok

            progress = st.progress(0.0, text="시작 준비 중...")
            tally = {"pass": 0}

            def cb(done, total, result):
                if result.passed:
                    tally["pass"] += 1
                pct = done / total if total else 1.0
                progress.progress(
                    pct,
                    text=f"{done}/{total}건 처리 ({pct*100:.0f}%) · 통과 {tally['pass']} / 제외 {done - tally['pass']}",
                )

            async def _run():
                db = Database()
                await db.init()
                rows = await db.get_all_patents()
                if not rows:
                    return None
                patents = [row_to_patent(r) for r in rows]
                screener = DesignScreener([], kw, ex, use_ai=use_ai)
                results = []
                total = len(patents)
                for i, p in enumerate(patents, 1):
                    r = await screener.screen(p)
                    await db.save_screening(r)  # 건별 즉시 저장 (중단돼도 유지)
                    results.append(r)
                    cb(i, total, r)
                return results

            try:
                if use_ai:
                    st.info("AI 정밀 스크리닝은 도면을 한 건씩 확인해 다소 느릴 수 있습니다. 아래 막대로 진행률을 확인하세요.")
                results = run_async(_run())
                if results is None:
                    st.warning("대상 디자인권이 없습니다. ①에서 먼저 PDF를 읽어주세요.")
                else:
                    passed = sum(1 for r in results if r.passed)
                    progress.progress(1.0, text=f"완료 · 통과 {passed} / 제외 {len(results)-passed}")
                    st.success(f"완료: 통과 {passed}건 / 제외 {len(results)-passed}건 (총 {len(results)}건)")
                    st.bar_chart({"통과": passed, "제외": len(results) - passed})
            except Exception as e:
                show_ai_error(e)


# ─────────────────────────────── ③ 분류 기준 제안 ───────────────────────────────
elif step.startswith("③"):
    st.header("③ 분류 기준 제안 (AI)")
    st.write("도면과 PEST 분석을 바탕으로 AI가 분류 기준을 제안합니다.")

    from src.utils.criteria_history import append_version, get_latest_approved

    prev_approved = get_latest_approved()
    if prev_approved:
        prev_name = prev_approved["criteria"].get("name", "")
        st.warning(
            f"⚠️ 이미 **승인된 기준(버전 {prev_approved['version']}: {prev_name})** 이 있습니다.\n\n"
            "지금 새로 제안을 받으면 이 기준을 대체합니다. 데이터를 나눠서 불러오는 중이라면, "
            "새 기준이 이전 분석과 달라져 **일관성이 깨질 수 있습니다.**\n\n"
            "👉 대부분의 경우 **④ 기준 수정/승인**에서 '이전 기준 이어서 쓰기'를 눌러 "
            "**기존 기준을 유지한 채** 이번에 추가된 데이터만 반영하는 것을 권장합니다."
        )

    st.caption("스크리닝을 통과한 디자인권을 대상으로 분석합니다.")
    context = st.text_area("분석 목적 / 컨텍스트", placeholder="예: 건축구성요소 외관 디자인 트렌드 분석")

    btn_label = "🆕 새 기준 제안 받기 (기존 기준 대체)" if prev_approved else "분류 기준 제안 받기"
    if st.button(btn_label, type="primary" if not prev_approved else "secondary", disabled=not key_ok):
        if True:
            from src.classifier.criteria_proposer import CriteriaProposer

            async def _run():
                db = Database()
                await db.init()
                rows = await db.get_screened_patents(passed_only=True)
                if not rows:
                    rows = await db.get_all_patents()
                if not rows:
                    return None
                patents = [row_to_patent(r) for r in rows]
                # 데이터에 존재하는 로카르노 분류를 자동으로 범위로 사용
                scope = sorted({p.locarno_class for p in patents if p.locarno_class})
                proposer = CriteriaProposer()
                crit = await proposer.propose_criteria(patents, scope, context or None)
                return proposer, crit

            with st.spinner("AI가 분류 기준 제안 중... (네트워크에 따라 1~2분)"):
                try:
                    out = run_async(_run())
                    if out is None:
                        st.warning("분석 대상이 없습니다. 먼저 ①②를 진행하세요.")
                    else:
                        proposer, crit = out
                        Path(CRITERIA_FILE).write_text(
                            json.dumps(crit.model_dump(), ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        entry = append_version(crit.model_dump(), "proposed",
                                               note="AI 신규 제안" + (f" · {context}" if context else ""))
                        st.success(f"제안 완료 (버전 {entry['version']}로 이력에 기록됨) "
                                   "→ data/proposed_criteria.json 저장됨")
                        render_criteria(crit)
                        st.info("👉 다음: 왼쪽 메뉴 **④ 기준 수정/승인** 에서 검토·수정 후 승인하세요.")
                except Exception as e:
                    show_ai_error(e)


# ─────────────────────────────── ④ 기준 수정/승인 ───────────────────────────────
elif step.startswith("④"):
    st.header("④ 분류 기준 수정 / 승인")

    from src.utils.criteria_history import (
        append_version, diff_criteria, get_latest_approved, load_history,
    )

    history = load_history()
    prev_approved = get_latest_approved()
    has_current = Path(CRITERIA_FILE).exists()

    def use_criteria(criteria_dict: dict, label: str):
        """선택한 기준을 현재 기준으로 적용."""
        Path(CRITERIA_FILE).write_text(
            json.dumps(criteria_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        st.success(f"{label} 적용했습니다.")
        st.rerun()

    def render_history_browser(expanded: bool = False):
        """버전 이력 목록 + 차이 비교 + 복원 (현재 기준 유무와 무관하게 사용)."""
        with st.expander(f"🕘 기준 버전 이력 ({len(history)}개)", expanded=expanded):
            if not history:
                st.caption("아직 이력이 없습니다.")
                return
            for entry in reversed(history):
                c = entry["criteria"]
                ts = entry["timestamp"][:16].replace("T", " ")
                badge = "🟢 승인됨" if c.get("status") == "approved" else "🟡 " + entry["action"]
                with st.container(border=True):
                    st.markdown(f"**버전 {entry['version']}** · {ts} · {badge}"
                                + (f" · _{entry['note']}_" if entry.get("note") else ""))
                    st.caption(f"　📋 {c.get('name', '(이름 없음)')}")
                    prior = next(
                        (h["criteria"] for h in history if h["version"] == entry["version"] - 1),
                        None,
                    )
                    for line in diff_criteria(prior, c):
                        st.caption(f"　{line}")
                    if st.button(f"이 버전(v{entry['version']})으로 복원",
                                 key=f"restore_{entry['version']}"):
                        use_criteria(c, f"버전 {entry['version']}로 복원했습니다.")

    # ── 현재 기준 파일이 없는 경우: 이력에서 이어서 쓰기/복원할 수 있게 한다 ──
    if not has_current:
        if prev_approved:
            st.info(
                f"💡 현재 작업 중인 기준은 없지만, **승인된 기준(버전 {prev_approved['version']}: "
                f"{prev_approved['criteria'].get('name', '')})** 이 이력에 있습니다.\n\n"
                "아래 버튼을 누르면 그 기준을 그대로 이어서 사용합니다. "
                "(③에서 새로 제안받을 필요 없음)"
            )
            if st.button("↩️ 이전 승인 기준 이어서 쓰기", type="primary"):
                use_criteria(prev_approved["criteria"],
                             f"버전 {prev_approved['version']} 기준을")
            render_history_browser(expanded=True)
        elif history:
            st.warning("현재 기준 파일이 없습니다. 아래 이력에서 복원하거나 ③에서 새로 제안받으세요.")
            render_history_browser(expanded=True)
        else:
            st.warning("아직 제안된 기준이 없습니다. ③을 먼저 진행하세요.")
    else:
        crit = ClassificationCriteria(**json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8")))
        from src.classifier.criteria_proposer import CriteriaProposer

        # 방금 ③에서 새로 제안받아 이전 승인본과 다른 경우, 되돌리기 옵션 제공
        if (prev_approved and crit.status != "approved"
                and prev_approved["criteria"] != crit.model_dump()):
            st.info(f"💡 이전에 **승인된 기준(버전 {prev_approved['version']})** 이 있습니다. "
                    "지금 화면은 아직 승인 안 된 새 제안입니다.")
            if st.button("↩️ 이전 승인 기준 이어서 쓰기 (새 제안 취소)"):
                use_criteria(prev_approved["criteria"],
                             f"버전 {prev_approved['version']}로 되돌렸습니다.")

        render_status_banner(crit.status)
        render_criteria(crit)
        with st.expander("원본 데이터(JSON) 보기 — 고급"):
            st.json(crit.model_dump())

        render_history_browser()

        st.subheader("AI에게 수정 요청")
        feedback = st.text_area("수정 요청 내용",
                                placeholder="예: 소재감 차원은 빼고 '색채 전략'을 추가해줘. 트렌드 키워드에 '모듈러' 추가.")
        if st.button("AI로 수정하기", disabled=not key_ok):
            if not feedback:
                st.error("수정 요청 내용을 입력하세요.")
            else:
                async def _run():
                    proposer = CriteriaProposer()
                    return proposer, await proposer.refine_criteria(crit, feedback)

                with st.spinner("AI가 기준 수정 중..."):
                    try:
                        proposer, revised = run_async(_run())
                        Path(CRITERIA_FILE).write_text(
                            json.dumps(revised.model_dump(), ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        append_version(revised.model_dump(), "refined", note=feedback[:200])
                        st.success("수정 완료 (이력에 기록됨). 아래에 반영된 내용을 확인하세요.")
                        st.rerun()
                    except Exception as e:
                        show_ai_error(e)

        st.divider()
        st.subheader("승인")
        st.write("기준이 만족스러우면 승인하세요. 승인해야 ⑤ 분류를 실행할 수 있습니다.")
        if st.button("이 기준 승인하기", type="primary"):
            data = json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8"))
            data["status"] = "approved"
            Path(CRITERIA_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            append_version(data, "approved", note="사용자 승인")
            st.success("승인 완료 (status: approved) → ⑤ 분류 실행으로 이동하세요.")


# ─────────────────────────────── ⑤ 분류 실행 ───────────────────────────────
elif step.startswith("⑤"):
    st.header("⑤ 분류 실행 (AI)")
    if not Path(CRITERIA_FILE).exists():
        st.warning("분류 기준이 없습니다. ③④를 먼저 진행하세요.")
    else:
        crit = ClassificationCriteria(**json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8")))
        if crit.status != "approved":
            st.warning(f"기준 상태가 '{crit.status}' 입니다. ④에서 먼저 '승인'하세요.")

        # 현재 분류 현황 집계
        async def _counts():
            db = Database()
            await db.init()
            passed = await db.get_screened_patents(passed_only=True)
            pending = await db.get_unclassified_screened_patents()
            return len(passed), len(pending)

        try:
            passed_n, pending_n = run_async(_counts())
        except Exception:
            passed_n, pending_n = 0, 0
        done_n = passed_n - pending_n

        c1, c2, c3 = st.columns(3)
        c1.metric("분류 대상(통과)", passed_n)
        c2.metric("이미 분류됨", done_n)
        c3.metric("남은 건수", pending_n)

        # 분류 실패(unclassified) 건 안내 및 재시도
        async def _failed_info():
            db = Database()
            await db.init()
            return await db.count_unclassified_results(), await db.get_failed_classification_samples()

        try:
            failed_n, failed_samples = run_async(_failed_info())
        except Exception:
            failed_n, failed_samples = 0, []

        if failed_n:
            st.error(f"⚠️ 분류 실패(unclassified) {failed_n}건이 있습니다. 아래 사유를 확인하세요.")
            for s in failed_samples:
                st.caption(f"• `{s['patent_id']}` — {s.get('reasoning') or '(사유 없음)'}")
            if st.button(f"🔄 실패한 {failed_n}건 다시 분류하기 (기존 실패 기록 삭제)"):
                async def _clear():
                    db = Database()
                    await db.init()
                    return await db.delete_unclassified_results()

                try:
                    n = run_async(_clear())
                    st.success(f"{n}건의 실패 기록을 삭제했습니다. 아래에서 다시 분류를 실행하세요.")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 실패: {e}")

        with st.expander("🧪 1건만 시험 분류 (크레딧 최소, 결과·오류 원인 확인)"):
            st.write("먼저 1건만 분류해 결과와 실패 사유를 확인한 뒤 전체를 돌리는 것을 권장합니다.")
            if st.button("시험 분류 실행", disabled=not key_ok or crit.status != "approved"):
                from src.classifier.design_classifier import DesignClassifier

                async def _trial():
                    db = Database()
                    await db.init()
                    rows = await db.get_unclassified_screened_patents() \
                        or await db.get_screened_patents(passed_only=True)
                    if not rows:
                        return None, None
                    p = row_to_patent(rows[0])
                    return p, await DesignClassifier(crit).classify(p)

                with st.spinner("1건 분류 중..."):
                    try:
                        patent, res = run_async(_trial())
                        if res is None:
                            st.warning("분류할 대상이 없습니다.")
                        elif res.primary_category == "unclassified":
                            st.error("❌ 분류 실패 — 사유:")
                            st.code(res.reasoning or "(사유 없음)")
                        else:
                            st.success(f"✅ 분류 성공: **{res.primary_category}** (신뢰도 {res.confidence})")
                            st.json({
                                "물품명": patent.title,
                                "주분류": res.primary_category,
                                "보조분류": res.secondary_categories,
                                "신뢰도": res.confidence,
                                "근거": res.reasoning,
                                "디자인특징": res.design_features,
                                "트렌드태그": res.trend_tags,
                            })
                    except Exception as e:
                        show_ai_error(e)

        # 지금까지 저장된 분류 결과 보기 (비용 없음)
        if done_n > 0:
            with st.expander(f"📊 지금까지 저장된 분류 결과 보기 ({done_n}건)", expanded=False):
                async def _load_done():
                    db = Database()
                    await db.init()
                    return await db.get_all_classifications()

                try:
                    rows = run_async(_load_done())
                    cats = Counter(r["primary_category"] for r in rows)
                    st.bar_chart(dict(cats.most_common()))
                    st.dataframe(
                        [
                            {
                                "디자인권 ID": r["patent_id"],
                                "분류": r["primary_category"],
                                "신뢰도": r["confidence"],
                                "특징": ", ".join(json.loads(r.get("design_features") or "[]")[:3]),
                            }
                            for r in rows
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption("저장 위치: data/classification_results.json · data/designmap.db (DB)")
                except Exception as e:
                    st.error(f"결과 조회 실패: {e}")

        st.info("💡 AI 분류는 1건당 크레딧이 듭니다. 아래에서 **이번에 처리할 최대 건수**를 정할 수 있고, "
                "이미 분류된 건은 건너뜁니다(이어서 하기). 중단해도 처리분은 저장됩니다.")

        resume = st.checkbox("이미 분류된 건은 건너뛰기 (이어서 하기)", value=True)
        target_pool = pending_n if resume else passed_n
        max_n = st.number_input(
            "이번에 분류할 최대 건수 (비용 조절용)",
            min_value=1, max_value=max(target_pool, 1),
            value=max(min(target_pool, 20), 1),
            help="처음에는 적게(예: 10~20) 돌려보고 결과를 확인한 뒤 늘리는 것을 권장합니다.",
        )

        if st.button("분류 시작", type="primary", disabled=not key_ok or crit.status != "approved" or target_pool == 0):
            from src.classifier.design_classifier import DesignClassifier

            progress = st.progress(0.0, text="시작 준비 중...")

            def cb(done, total, result):
                pct = done / total if total else 1.0
                progress.progress(pct, text=f"{done}/{total}건 분류 ({pct*100:.0f}%) · 방금: {result.primary_category}")

            async def _run():
                db = Database()
                await db.init()
                rows = (await db.get_unclassified_screened_patents()) if resume \
                    else (await db.get_screened_patents(passed_only=True))
                if not rows:
                    return None, []
                patents = [row_to_patent(r) for r in rows][: int(max_n)]
                classifier = DesignClassifier(crit)
                total = len(patents)
                for i, p in enumerate(patents, 1):
                    r = await classifier.classify(p)
                    await db.save_classification(r)  # 건별 즉시 저장 (중단돼도 유지)
                    cb(i, total, r)
                all_rows = await db.get_all_classifications()
                return "ok", all_rows

            try:
                status, all_rows = run_async(_run())
                if status is None:
                    st.warning("분류할 디자인권이 없습니다. (이미 모두 분류됐거나 ②를 먼저 진행하세요)")
                else:
                    # DB의 전체 분류 결과를 결과 파일로 내보내기
                    results = [ClassificationResult(
                        patent_id=r["patent_id"],
                        primary_category=r["primary_category"],
                        secondary_categories=json.loads(r.get("secondary_categories") or "[]"),
                        confidence=r["confidence"],
                        reasoning=r.get("reasoning") or "",
                        design_features=json.loads(r.get("design_features") or "[]"),
                        trend_tags=json.loads(r.get("trend_tags") or "[]"),
                    ) for r in all_rows]
                    Path(RESULTS_FILE).write_text(
                        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    cats = Counter(r.primary_category for r in results)
                    st.success(f"완료! 지금까지 총 {len(results)}건 분류됨 (data/classification_results.json 저장)")
                    st.bar_chart(dict(cats.most_common()))
                    st.dataframe(
                        [
                            {"분류": r.primary_category, "신뢰도": r.confidence,
                             "특징": ", ".join(r.design_features[:3])}
                            for r in results
                        ],
                        use_container_width=True,
                    )
            except Exception as e:
                show_ai_error(e)


# ─────────────────────────────── ⑥ 리포트 ───────────────────────────────
elif step.startswith("⑥"):
    st.header("⑥ 트렌드 예측 리포트 (AI)")
    if not (Path(CRITERIA_FILE).exists() and Path(RESULTS_FILE).exists()):
        st.warning("분류 결과가 없습니다. ⑤ 분류를 먼저 실행하세요.")
    else:
        from src.utils.report_history import (
            append_report, load_history as load_report_history, past_contexts,
        )

        rep_history = load_report_history()
        contexts = past_contexts()

        # 이전에 쓴 관점을 그대로 재사용할 수 있게 제공
        if contexts:
            picked_ctx = st.selectbox(
                "이전에 사용한 관점 불러오기",
                ["(직접 입력)"] + contexts,
                help="같은 관점으로 다시 분석하면 이전 리포트와 비교하기 쉽습니다.",
            )
            if picked_ctx != "(직접 입력)" and st.button("이 관점 사용하기"):
                st.session_state["report_context"] = picked_ctx
                st.rerun()

        context = st.text_area(
            "리포트 관점 (선택)", key="report_context",
            placeholder="예: 향후 5년 건축구성요소 디자인 방향 예측",
        )

        if st.button("리포트 생성", type="primary", disabled=not key_ok):
            from src.analysis.roadmap import DesignRoadmapAnalyzer

            crit = ClassificationCriteria(**json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8")))
            results = [ClassificationResult(**r) for r in json.loads(Path(RESULTS_FILE).read_text(encoding="utf-8"))]

            async def _run():
                db = Database()
                await db.init()
                rows = await db.get_screened_patents(passed_only=True)
                patents = [row_to_patent(r) for r in rows]
                analyzer = DesignRoadmapAnalyzer()
                stats = analyzer.compute_statistics(patents, results)
                text = await analyzer.generate_trend_report(stats, crit, context or None)
                return text, stats

            with st.spinner("AI가 트렌드 리포트 작성 중..."):
                try:
                    report_text, stats = run_async(_run())
                    Path(REPORT_FILE).write_text(report_text, encoding="utf-8")
                    entry = append_report(report_text, context or "", crit.name, stats)
                    st.success(f"리포트 생성 완료 (버전 {entry['version']}로 이력에 기록됨) "
                               "→ data/trend_report.md")
                    st.markdown(report_text)
                    offer_report_downloads(report_text, key_prefix="rep6_")
                except Exception as e:
                    show_ai_error(e)

        # ── 리포트 이력 ──
        with st.expander(f"🕘 리포트 이력 ({len(rep_history)}개)", expanded=False):
            if not rep_history:
                st.caption("아직 생성한 리포트가 없습니다.")
            else:
                for entry in reversed(rep_history):
                    ts = entry["timestamp"][:16].replace("T", " ")
                    ctx = entry.get("context") or "(관점 미지정)"
                    with st.container(border=True):
                        st.markdown(f"**버전 {entry['version']}** · {ts}")
                        st.caption(f"　🎯 관점: {ctx}")
                        summary = entry.get("summary") or {}
                        bits = [f"{k} {v}" for k, v in summary.items() if v]
                        if entry.get("criteria_name"):
                            bits.insert(0, f"기준: {entry['criteria_name']}")
                        if bits:
                            st.caption("　📊 " + " · ".join(bits))
                        c1, c2 = st.columns(2)
                        if c1.button(f"이 관점 다시 쓰기 (v{entry['version']})",
                                     key=f"rep_ctx_{entry['version']}"):
                            st.session_state["report_context"] = entry.get("context", "")
                            st.rerun()
                        if c2.button(f"내용 보기 (v{entry['version']})",
                                     key=f"rep_view_{entry['version']}"):
                            st.session_state["show_report"] = entry["version"]

                        if st.session_state.get("show_report") == entry["version"]:
                            st.markdown(entry["report"])
                            offer_report_downloads(
                                entry["report"], key_prefix=f"hist{entry['version']}_"
                            )


# ─────────────────────────────── ⑦ 결과 보기 / 내려받기 ───────────────────────────────
elif step.startswith("⑦"):
    st.header("⑦ 분류 결과 보기 / 내려받기")
    st.write("지금까지 저장된 분류 결과를 확인하고 Excel 등으로 내려받습니다. (AI 호출 없음, 무료)")

    async def _load_joined():
        db = Database()
        await db.init()
        return await db.get_classified_joined()

    try:
        rows = run_async(_load_joined())
    except Exception as e:
        st.error(f"결과 조회 실패: {e}")
        rows = []

    if not rows:
        st.warning("아직 저장된 분류 결과가 없습니다. ⑤ 분류를 먼저 실행하세요.")
    else:
        # 표에 보기 좋게 가공
        office_ko = {
            "KIPO": "한국", "USPTO": "미국", "EUIPO": "유럽",
            "CNIPA": "중국", "JPO": "일본", "WIPO": "WIPO", "OTHER": "기타",
        }
        table_rows = []
        for r in rows:
            table_rows.append({
                "출원번호": r.get("application_number", ""),
                "물품명": r.get("title", ""),
                "출원청": office_ko.get(r.get("patent_office", ""), r.get("patent_office", "")),
                "로카르노": r.get("locarno_class", ""),
                "출원인": r.get("applicant", "") or "",
                "주분류": r.get("primary_category", ""),
                "신뢰도": r.get("confidence", ""),
                "디자인특징": ", ".join(json.loads(r.get("design_features") or "[]")),
                "트렌드태그": ", ".join(json.loads(r.get("trend_tags") or "[]")),
                "분류근거": r.get("reasoning", "") or "",
            })

        cats = Counter(r["primary_category"] for r in rows)
        c1, c2 = st.columns([1, 2])
        c1.metric("총 분류 건수", len(rows))
        c1.metric("분류 카테고리 수", len(cats))
        c2.markdown("**분류 분포**")
        c2.bar_chart(dict(cats.most_common()))

        st.markdown("#### 분류 결과 표")
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.markdown("#### 내려받기")

        # 여러 건에 반복되는 서식 이미지(로고·표지)를 제외하고 고유 도면을 고른다
        img_paths = select_representative_images(rows)
        found = sum(1 for p in img_paths if p)
        with_images = st.checkbox(
            f"Excel에 대표도면 이미지 포함 (도면 확인됨 {found}/{len(rows)}건)",
            value=found > 0, disabled=found == 0,
            help="이미지가 들어가면 파일이 커지고 생성에 시간이 조금 걸립니다.",
        )
        if found == 0:
            st.caption("※ 도면 이미지 파일을 찾을 수 없습니다. PDF를 읽은 폴더(옆의 drawings 폴더)가 "
                       "이동·삭제되지 않았는지 확인하세요.")

        d1, d2, d3 = st.columns(3)
        try:
            if with_images and found:
                with st.spinner(f"대표도면 {found}건을 엑셀에 넣는 중..."):
                    xlsx = to_excel_with_images_bytes(table_rows, img_paths)
                label, fname = "⬇️ Excel (도면 포함)", "classification_results_with_images.xlsx"
            else:
                xlsx = to_excel_bytes(table_rows)
                label, fname = "⬇️ Excel (.xlsx)", "classification_results.xlsx"
            d1.download_button(
                label, xlsx, file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            d1.error(f"Excel 생성 실패: {e}")

        import io as _io

        import pandas as _pd

        csv_bytes = _pd.DataFrame(table_rows).to_csv(index=False).encode("utf-8-sig")
        d2.download_button("⬇️ CSV (.csv)", csv_bytes, file_name="classification_results.csv", mime="text/csv")

        json_bytes = json.dumps(table_rows, ensure_ascii=False, indent=2).encode("utf-8")
        d3.download_button("⬇️ JSON (.json)", json_bytes, file_name="classification_results.json",
                           mime="application/json")

        if Path(REPORT_FILE).exists():
            st.markdown("#### 트렌드 리포트")
            offer_report_downloads(Path(REPORT_FILE).read_text(encoding="utf-8"), key_prefix="rep7_")
