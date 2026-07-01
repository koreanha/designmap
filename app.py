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


STATUS_LABELS = {
    "proposed": ("🟡", "제안됨 — 검토가 필요합니다"),
    "reviewed": ("🟠", "검토 중"),
    "approved": ("🟢", "승인됨 — 분류 실행 준비 완료"),
    "rejected": ("🔴", "반려됨"),
}
PEST_LABELS = {"political": "정치", "economic": "경제", "social": "사회", "technological": "기술"}


def to_excel_bytes(rows: list[dict]) -> bytes:
    """dict 목록을 Excel 파일 바이트로 변환 (다운로드용)."""
    import io

    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="분류결과")
    return buf.getvalue()


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
                        render_criteria(crit)
                        st.info("👉 다음: 왼쪽 메뉴 **④ 기준 수정/승인** 에서 검토·수정 후 승인하세요.")
                except Exception as e:
                    show_ai_error(e)


# ─────────────────────────────── ④ 기준 수정/승인 ───────────────────────────────
elif step.startswith("④"):
    st.header("④ 분류 기준 수정 / 승인")
    if not Path(CRITERIA_FILE).exists():
        st.warning("아직 제안된 기준이 없습니다. ③을 먼저 진행하세요.")
    else:
        crit = ClassificationCriteria(**json.loads(Path(CRITERIA_FILE).read_text(encoding="utf-8")))
        from src.classifier.criteria_proposer import CriteriaProposer

        render_status_banner(crit.status)
        render_criteria(crit)
        with st.expander("원본 데이터(JSON) 보기 — 고급"):
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
                        st.success("수정 완료 (저장됨). 아래에 반영된 내용을 확인하세요.")
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
        d1, d2, d3 = st.columns(3)
        try:
            xlsx = to_excel_bytes(table_rows)
            d1.download_button(
                "⬇️ Excel (.xlsx)", xlsx,
                file_name="classification_results.xlsx",
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
            st.download_button("⬇️ 트렌드 리포트 (.md)", Path(REPORT_FILE).read_text(encoding="utf-8"),
                               file_name="trend_report.md")
