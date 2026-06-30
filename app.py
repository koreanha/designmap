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


# ─────────────────────────────── 사이드바: 상태 ───────────────────────────────
st.sidebar.title("📐 DesignMap")
st.sidebar.caption("디자인권 분류 · 트렌드 예측")

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

step = st.sidebar.radio(
    "단계 선택",
    [
        "① PDF 읽기",
        "② 스크리닝",
        "③ 분류 기준 제안",
        "④ 기준 수정/승인",
        "⑤ 분류 실행",
        "⑥ 트렌드 리포트",
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

    folder = st.text_input("PDF가 있는 폴더 경로", placeholder="/Users/내이름/designmap-pdf/korea")
    col1, col2 = st.columns(2)
    office = col1.selectbox("발행 특허청", ["KIPO", "USPTO", "EUIPO", "CNIPA", "JPO"])
    locarno_default = col2.text_input("로카르노 기본값 (선택)", placeholder="예: 25",
                                      help="PDF에서 분류를 못 찾을 때 사용할 값")
    no_vision = st.checkbox("AI Vision OCR 끄기 (텍스트 추출만, 빠름/무료)", value=False)

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
                        folder, office, default_locarno=locarno_default or None,
                        progress_callback=cb,
                    )
                    if patents:
                        parser.to_excel(patents, data_path("parsed_patents.xlsx"))

                        async def _save():
                            db = Database()
                            await db.init()
                            for p in patents:
                                await db.save_patent(p)

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
                                    "도면": len(p.drawings),
                                }
                                for p in patents[:200]
                            ],
                            use_container_width=True,
                        )
                except Exception as e:
                    show_ai_error(e)


# ─────────────────────────────── ② 스크리닝 ───────────────────────────────
elif step.startswith("②"):
    st.header("② 1차 스크리닝")
    st.write("분석 대상과 관계없는 디자인을 걸러 노이즈를 줄입니다.")

    locarno = st.text_input("대상 로카르노 분류", placeholder="예: 25 (콤마로 여러 개)")
    keywords = st.text_input("포함 키워드 (콤마 구분, 선택)")
    exclude = st.text_input("제외 키워드 (콤마 구분, 선택)")
    no_ai = st.checkbox("AI 없이 규칙 기반만 (열쇠/비용 불필요, 빠름)", value=not key_ok)

    if st.button("스크리닝 시작", type="primary"):
        if not locarno:
            st.error("대상 로카르노 분류를 입력하세요.")
        else:
            from src.screening.screener import DesignScreener

            target = [x.strip() for x in locarno.split(",")]
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
                rows = await db.get_patents_by_locarno(target[0])
                if not rows:
                    return None
                patents = [row_to_patent(r) for r in rows]
                screener = DesignScreener(target, kw, ex, use_ai=use_ai)
                results = await screener.screen_batch(patents, progress_callback=cb)
                for r in results:
                    await db.save_screening(r)
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

    locarno = st.text_input("대상 로카르노 분류", placeholder="예: 25")
    context = st.text_area("분석 목적 / 컨텍스트", placeholder="예: 건축구성요소(25류) 외관 디자인 트렌드 분석")

    if st.button("분류 기준 제안 받기", type="primary", disabled=not key_ok):
        if not locarno:
            st.error("대상 로카르노 분류를 입력하세요.")
        else:
            from src.classifier.criteria_proposer import CriteriaProposer

            async def _run():
                db = Database()
                await db.init()
                rows = await db.get_screened_patents(passed_only=True)
                if not rows:
                    rows = await db.get_patents_by_locarno(locarno.split(",")[0].strip())
                if not rows:
                    return None
                patents = [row_to_patent(r) for r in rows]
                proposer = CriteriaProposer()
                crit = await proposer.propose_criteria(
                    patents, [x.strip() for x in locarno.split(",")], context or None
                )
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
                        st.success("제안 완료 → data/proposed_criteria.json 저장됨")
                        st.text(proposer.format_criteria_for_review(crit))
                except Exception as e:
                    show_ai_error(e)


# ─────────────────────────────── ④ 기준 수정/승인 ───────────────────────────────
elif step.startswith("④"):
    st.header("④ 분류 기준 수정 / 승인")
    if not Path(CRITERIA_FILE).exists():
        st.warning("아직 제안된 기준이 없습니다. ③을 먼저 진행하세요.")
    else:
        crit = ClassificationCriteria(**json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8")))
        st.markdown(f"**현재 상태:** `{crit.status}`")

        from src.classifier.criteria_proposer import CriteriaProposer

        st.text(CriteriaProposer().format_criteria_for_review(crit) if False else "")
        with st.expander("현재 분류 기준 보기", expanded=True):
            st.json(crit.model_dump())

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
                        st.success("수정 완료 (저장됨)")
                        st.text(proposer.format_criteria_for_review(revised))
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
        st.write("승인된 기준으로 각 디자인권을 분류합니다.")
        if st.button("분류 시작", type="primary", disabled=not key_ok or crit.status != "approved"):
            from src.classifier.design_classifier import DesignClassifier

            progress = st.progress(0.0, text="시작 준비 중...")

            def cb(done, total, result):
                pct = done / total if total else 1.0
                progress.progress(pct, text=f"{done}/{total}건 분류 ({pct*100:.0f}%)")

            async def _run():
                db = Database()
                await db.init()
                rows = await db.get_screened_patents(passed_only=True)
                if not rows:
                    return None
                patents = [row_to_patent(r) for r in rows]
                classifier = DesignClassifier(crit)
                results = await classifier.classify_batch(patents, progress_callback=cb)
                for r in results:
                    await db.save_classification(r)
                return results

            if True:
                try:
                    results = run_async(_run())
                    if results is None:
                        st.warning("스크리닝 통과 디자인권이 없습니다. ②를 먼저 진행하세요.")
                    else:
                        Path(RESULTS_FILE).write_text(
                            json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        cats = Counter(r.primary_category for r in results)
                        st.success(f"{len(results)}건 분류 완료")
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
        context = st.text_area("리포트 관점 (선택)", placeholder="예: 향후 5년 건축구성요소 디자인 방향 예측")
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
                return text

            with st.spinner("AI가 트렌드 리포트 작성 중..."):
                try:
                    report_text = run_async(_run())
                    Path(REPORT_FILE).write_text(report_text, encoding="utf-8")
                    st.success("리포트 생성 완료 → data/trend_report.md")
                    st.markdown(report_text)
                    st.download_button("리포트 내려받기 (.md)", report_text,
                                       file_name="trend_report.md")
                except Exception as e:
                    show_ai_error(e)
