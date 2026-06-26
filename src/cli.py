"""DesignMap CLI - 디자인권 분류 에이전트."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(name="designmap", help="디자인권 분류 에이전트 - 디자인 로드맵 분석 및 트렌드 예측")
console = Console()


@app.command()
def template(output: str = "data/template.xlsx"):
    """데이터 입력용 Excel 템플릿 생성"""
    from src.collectors.manual import ManualCollector

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    ManualCollector.create_template(output)
    console.print(f"[green]템플릿 생성 완료: {output}[/green]")


@app.command()
def load(
    file: str = typer.Argument(..., help="Excel/CSV 파일 경로"),
    drawings_dir: str | None = typer.Option(None, help="도면 이미지 디렉토리"),
):
    """Excel 파일에서 디자인권 데이터 로드"""
    from src.collectors.manual import ManualCollector
    from src.utils.database import Database

    patents = ManualCollector.from_excel(file, drawings_dir)
    db = Database()
    asyncio.run(_save_patents(db, patents))
    console.print(f"[green]{len(patents)}건 로드 완료[/green]")


async def _save_patents(db, patents):
    await db.init()
    for p in patents:
        await db.save_patent(p)


@app.command()
def parse_pdf(
    directory: str = typer.Argument(..., help="PDF 파일이 있는 디렉토리 경로"),
    office: str = typer.Option(..., help="특허청 코드 (KIPO, USPTO, EUIPO, CNIPA, JPO)"),
    output: str = typer.Option("data/parsed_patents.xlsx", help="결과 Excel 저장 경로"),
    drawings_dir: str | None = typer.Option(None, help="도면 이미지 저장 디렉토리"),
    no_vision: bool = typer.Option(False, help="Claude Vision OCR 비활성화 (텍스트 추출만 사용)"),
    no_db: bool = typer.Option(False, help="DB 저장 건너뛰기"),
    recursive: bool = typer.Option(True, help="하위 디렉토리까지 검색"),
):
    """PDF 원문공보에서 디자인권 데이터 추출 → Excel 변환

    각국 특허청의 디자인 공보 PDF 파일에서 서지사항(출원번호, 물품명, 출원인, 로카르노 분류 등)과
    도면 이미지를 추출하여 구조화된 Excel 파일과 DB로 저장합니다.

    예시:
        designmap parse-pdf /data/kr_patents --office KIPO
        designmap parse-pdf /data/us_patents --office USPTO --no-vision
        designmap parse-pdf /data/mixed --office JPO --drawings-dir /data/drawings
    """
    asyncio.run(_parse_pdf(directory, office, output, drawings_dir, no_vision, no_db, recursive))


async def _parse_pdf(directory, office, output, drawings_dir, no_vision, no_db, recursive):
    from src.collectors.pdf_parser import GazetteParser
    from src.utils.database import Database

    office = office.upper()
    valid_offices = ["KIPO", "USPTO", "EUIPO", "CNIPA", "JPO"]
    if office not in valid_offices:
        console.print(f"[red]지원하지 않는 특허청: {office}. 사용 가능: {', '.join(valid_offices)}[/red]")
        return

    dir_path = Path(directory)
    if not dir_path.exists():
        console.print(f"[red]디렉토리가 존재하지 않습니다: {directory}[/red]")
        return

    pdf_count = len(list(dir_path.glob("**/*.pdf" if recursive else "*.pdf")))
    if pdf_count == 0:
        console.print(f"[yellow]PDF 파일이 없습니다: {directory}[/yellow]")
        return

    console.print(f"[cyan]{office} 공보 PDF {pdf_count}건 파싱 시작...[/cyan]")
    if no_vision:
        console.print("[dim]Vision OCR 비활성화 - 텍스트 추출만 사용[/dim]")

    parser = GazetteParser(use_vision=not no_vision)
    patents = parser.parse_directory(directory, office, drawings_dir, recursive)

    console.print(f"[green]{len(patents)}/{pdf_count}건 파싱 성공[/green]")

    if patents:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        parser.to_excel(patents, output)
        console.print(f"[green]Excel 저장: {output}[/green]")

        if not no_db:
            db = Database()
            await db.init()
            for p in patents:
                await db.save_patent(p)
            console.print(f"[green]DB 저장 완료: {len(patents)}건[/green]")

    table = Table(title="파싱 결과 요약")
    table.add_column("항목")
    table.add_column("값")
    table.add_row("입력 PDF", str(pdf_count))
    table.add_row("파싱 성공", str(len(patents)))
    table.add_row("파싱 실패", str(pdf_count - len(patents)))

    if patents:
        from collections import Counter
        locarno_counts = Counter(p.locarno_class for p in patents)
        table.add_row("로카르노 분류", ", ".join(f"{k}({v}건)" for k, v in locarno_counts.most_common(5)))
        has_drawings = sum(1 for p in patents if p.drawings)
        table.add_row("도면 보유", f"{has_drawings}건")
        has_desc = sum(1 for p in patents if p.design_description)
        table.add_row("설명 보유", f"{has_desc}건")

    console.print(table)

    if pdf_count - len(patents) > 0:
        console.print("[yellow]파싱 실패 파일은 텍스트 추출이 어려운 스캔 PDF일 수 있습니다.[/yellow]")
        if no_vision:
            console.print("[yellow]--no-vision 플래그를 제거하면 Claude Vision OCR로 재시도할 수 있습니다.[/yellow]")


@app.command()
def collect(
    source: str = typer.Option("kipris", help="데이터 소스 (kipris, wipo)"),
    locarno: str = typer.Option(..., help="로카르노 분류 코드 (예: 14-02)"),
    keyword: str | None = typer.Option(None, help="검색 키워드"),
    date_from: str | None = typer.Option(None, help="시작일 (YYYY-MM-DD)"),
    date_to: str | None = typer.Option(None, help="종료일 (YYYY-MM-DD)"),
    max_results: int = typer.Option(100, help="최대 결과 수"),
):
    """특허청 API에서 디자인권 데이터 수집"""
    asyncio.run(_collect(source, locarno, keyword, date_from, date_to, max_results))


async def _collect(source, locarno, keyword, date_from, date_to, max_results):
    from src.collectors.kipris import KIPRISCollector
    from src.collectors.uspto import USPTOCollector
    from src.collectors.euipo import EUIPOCollector
    from src.collectors.cnipa import CNIPACollector
    from src.collectors.jpo import JPOCollector
    from src.utils.database import Database

    collectors = {
        "kipris": KIPRISCollector,
        "uspto": USPTOCollector,
        "euipo": EUIPOCollector,
        "cnipa": CNIPACollector,
        "jpo": JPOCollector,
    }

    if source not in collectors:
        console.print(f"[red]지원하지 않는 소스: {source}. 사용 가능: {', '.join(collectors)}[/red]")
        return

    collector = collectors[source]()

    console.print(f"[cyan]수집 중... (로카르노: {locarno})[/cyan]")
    patents = await collector.search(locarno, keyword, date_from, date_to, max_results)
    console.print(f"[green]{len(patents)}건 수집[/green]")

    db = Database()
    await db.init()
    for p in patents:
        await db.save_patent(p)
    console.print("[green]DB 저장 완료[/green]")


@app.command()
def screen(
    locarno: str = typer.Option(..., help="대상 로카르노 분류 (콤마 구분)"),
    keywords: str | None = typer.Option(None, help="대상 키워드 (콤마 구분)"),
    exclude: str | None = typer.Option(None, help="제외 키워드 (콤마 구분)"),
    confidence: float = typer.Option(0.7, help="최소 신뢰도"),
):
    """1차 스크리닝 - 노이즈 제거"""
    asyncio.run(_screen(locarno, keywords, exclude, confidence))


async def _screen(locarno, keywords, exclude, confidence):
    from src.screening.screener import DesignScreener
    from src.utils.database import Database
    from src.models.design_patent import PatentOffice, DrawingImage, DesignPatent

    target_locarno = [l.strip() for l in locarno.split(",")]
    target_keywords = [k.strip() for k in keywords.split(",")] if keywords else None
    exclude_keywords = [k.strip() for k in exclude.split(",")] if exclude else None

    screener = DesignScreener(target_locarno, target_keywords, exclude_keywords, confidence)
    db = Database()
    await db.init()

    rows = await db.get_patents_by_locarno(target_locarno[0])
    if not rows:
        console.print("[yellow]대상 디자인권이 없습니다. 먼저 데이터를 수집해주세요.[/yellow]")
        return

    patents = [_row_to_patent(r) for r in rows]
    console.print(f"[cyan]{len(patents)}건 스크리닝 중...[/cyan]")

    results = await screener.screen_batch(patents)
    passed = [r for r in results if r.passed]

    for r in results:
        await db.save_screening(r)

    table = Table(title="스크리닝 결과")
    table.add_column("통과/제외")
    table.add_column("건수")
    table.add_column("비율")
    table.add_row("통과", str(len(passed)), f"{len(passed)/len(results)*100:.1f}%")
    table.add_row("제외", str(len(results)-len(passed)), f"{(len(results)-len(passed))/len(results)*100:.1f}%")
    console.print(table)


@app.command()
def propose(
    locarno: str = typer.Option(..., help="대상 로카르노 분류 (콤마 구분)"),
    context: str | None = typer.Option(None, help="도메인 컨텍스트 설명"),
    output: str = typer.Option("data/proposed_criteria.json", help="제안 기준 저장 경로"),
):
    """분류 기준 제안 (AI 기반)"""
    asyncio.run(_propose(locarno, context, output))


async def _propose(locarno, context, output):
    from src.classifier.criteria_proposer import CriteriaProposer
    from src.utils.database import Database
    from src.models.design_patent import PatentOffice, DrawingImage, DesignPatent

    locarno_list = [l.strip() for l in locarno.split(",")]
    db = Database()
    await db.init()

    rows = await db.get_screened_patents(passed_only=True)
    if not rows:
        rows = await db.get_patents_by_locarno(locarno_list[0])
    if not rows:
        console.print("[yellow]분석 대상 디자인권이 없습니다.[/yellow]")
        return

    patents = [_row_to_patent(r) for r in rows]
    proposer = CriteriaProposer()

    console.print("[cyan]분류 기준 제안 중...[/cyan]")
    criteria = await proposer.propose_criteria(patents, locarno_list, context)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(
        json.dumps(criteria.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    console.print(Panel(proposer.format_criteria_for_review(criteria), title="분류 기준 제안"))
    console.print(f"\n[green]제안 기준 저장: {output}[/green]")
    console.print("[yellow]검토 후 status를 'approved'로 변경하고 classify 명령을 실행하세요.[/yellow]")


@app.command()
def classify(
    criteria_file: str = typer.Option("data/proposed_criteria.json", help="확정된 분류 기준 파일"),
    output: str = typer.Option("data/classification_results.json", help="분류 결과 저장 경로"),
):
    """확정된 기준으로 디자인권 분류"""
    asyncio.run(_classify(criteria_file, output))


async def _classify(criteria_file, output):
    from src.classifier.design_classifier import DesignClassifier
    from src.utils.database import Database
    from src.models import ClassificationCriteria

    criteria_data = json.loads(Path(criteria_file).read_text(encoding="utf-8"))
    criteria = ClassificationCriteria(**criteria_data)

    if criteria.status != "approved":
        console.print(f"[yellow]분류 기준 상태: {criteria.status}. 'approved' 상태에서만 분류를 실행합니다.[/yellow]")
        confirm = typer.confirm("그래도 진행하시겠습니까?")
        if not confirm:
            return

    db = Database()
    await db.init()
    rows = await db.get_screened_patents(passed_only=True)
    if not rows:
        console.print("[yellow]스크리닝 통과 디자인권이 없습니다.[/yellow]")
        return

    patents = [_row_to_patent(r) for r in rows]
    classifier = DesignClassifier(criteria)

    console.print(f"[cyan]{len(patents)}건 분류 중...[/cyan]")
    results = await classifier.classify_batch(patents)

    for r in results:
        await db.save_classification(r)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    table = Table(title="분류 결과 요약")
    table.add_column("카테고리")
    table.add_column("건수")
    from collections import Counter
    cats = Counter(r.primary_category for r in results)
    for cat, cnt in cats.most_common():
        table.add_row(cat, str(cnt))
    console.print(table)
    console.print(f"[green]분류 결과 저장: {output}[/green]")


@app.command()
def report(
    criteria_file: str = typer.Option("data/proposed_criteria.json", help="분류 기준 파일"),
    results_file: str = typer.Option("data/classification_results.json", help="분류 결과 파일"),
    context: str | None = typer.Option(None, help="도메인 컨텍스트"),
    output: str = typer.Option("data/trend_report.md", help="리포트 저장 경로"),
):
    """디자인 트렌드 예측 리포트 생성"""
    asyncio.run(_report(criteria_file, results_file, context, output))


async def _report(criteria_file, results_file, context, output):
    from src.analysis.roadmap import DesignRoadmapAnalyzer
    from src.models import ClassificationCriteria, ClassificationResult
    from src.utils.database import Database

    criteria_data = json.loads(Path(criteria_file).read_text(encoding="utf-8"))
    criteria = ClassificationCriteria(**criteria_data)

    results_data = json.loads(Path(results_file).read_text(encoding="utf-8"))
    results = [ClassificationResult(**r) for r in results_data]

    db = Database()
    await db.init()
    rows = await db.get_screened_patents(passed_only=True)
    patents = [_row_to_patent(r) for r in rows]

    analyzer = DesignRoadmapAnalyzer()
    stats = analyzer.compute_statistics(patents, results)

    console.print("[cyan]트렌드 리포트 생성 중...[/cyan]")
    report_text = await analyzer.generate_trend_report(stats, criteria, context)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(report_text, encoding="utf-8")
    console.print(f"[green]리포트 저장: {output}[/green]")
    console.print(Panel(report_text[:2000] + "..." if len(report_text) > 2000 else report_text, title="트렌드 리포트"))


def _row_to_patent(row: dict):
    """DB row를 DesignPatent로 변환"""
    from src.models.design_patent import PatentOffice, DrawingImage, DesignPatent
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


if __name__ == "__main__":
    app()
