"""분류 결과 내보내기 유틸 (Excel 생성, 대표도면 삽입).

streamlit에 의존하지 않아 단독으로 테스트할 수 있다.
"""
from __future__ import annotations

import json
from pathlib import Path


def _drawing_paths(drawings_json: str | None, limit: int = 12) -> list[str]:
    """도면 목록에서 실제 존재하는 파일 경로를 순서대로 반환 (대표도면 우선)."""
    if not drawings_json:
        return []
    try:
        drawings = json.loads(drawings_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(drawings, list):
        return []

    ordered = [d for d in drawings if isinstance(d, dict) and d.get("drawing_type") == "representative"]
    ordered += [d for d in drawings if isinstance(d, dict) and d not in ordered]

    paths = []
    for d in ordered:
        p = d.get("file_path") or d.get("url")
        if p and Path(p).exists():
            paths.append(p)
        if len(paths) >= limit:
            break
    return paths


def _file_hash(path: str, _cache: dict = {}) -> str | None:
    """파일 내용 해시 (동일 이미지 판별용). 경로별로 캐시."""
    import hashlib

    if path in _cache:
        return _cache[path]
    try:
        h = hashlib.md5(Path(path).read_bytes()).hexdigest()
    except OSError:
        h = None
    _cache[path] = h
    return h


def select_representative_images(rows: list[dict]) -> list[str | None]:
    """각 건의 대표도면을 고르되, 여러 건에 공통으로 나타나는 이미지는 제외한다.

    EUIPO 등록증 표지의 로고·배경 그래픽처럼 모든 문서에 똑같이 들어 있는
    이미지가 대표도면으로 잘못 선택되는 것을 막기 위함이다.
    (같은 이미지가 여러 건에서 반복되면 그 건의 고유 도면일 수 없다)
    """
    from collections import Counter

    per_row = [_drawing_paths(r.get("drawings_json")) for r in rows]

    counts: Counter = Counter()
    row_hashes: list[list[tuple[str, str | None]]] = []
    for paths in per_row:
        hashed = [(p, _file_hash(p)) for p in paths]
        row_hashes.append(hashed)
        counts.update({h for _, h in hashed if h})

    n_rows = max(len(rows), 1)
    # 3건 이상 & 전체의 30% 이상에서 반복되면 서식 장식으로 판단
    boilerplate = {h for h, c in counts.items() if c >= 3 and c / n_rows >= 0.3}

    picked: list[str | None] = []
    for hashed in row_hashes:
        choice = next((p for p, h in hashed if h and h not in boilerplate), None)
        # 전부 공통 이미지뿐이면 어쩔 수 없이 첫 번째라도 사용
        picked.append(choice or (hashed[0][0] if hashed else None))
    return picked


def representative_image(drawings_json: str | None) -> str | None:
    """도면 목록에서 대표도면 파일 경로를 고른다 (없으면 첫 번째 도면)."""
    if not drawings_json:
        return None
    try:
        drawings = json.loads(drawings_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(drawings, list) or not drawings:
        return None

    def path_of(d):
        return d.get("file_path") or d.get("url") if isinstance(d, dict) else None

    for d in drawings:
        if isinstance(d, dict) and d.get("drawing_type") == "representative":
            p = path_of(d)
            if p and Path(p).exists():
                return p
    for d in drawings:
        p = path_of(d)
        if p and Path(p).exists():
            return p
    return None


def to_excel_with_images_bytes(rows: list[dict], image_paths: list[str | None],
                               thumb_px: int = 110) -> bytes:
    """분류 결과를 Excel로 만들되 '대표도면' 열에 이미지를 삽입한다."""
    import io

    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = "분류결과"

    # 한글 폰트를 지정하지 않으면 일부 환경에서 한글이 중국어 폰트로 대체되어
    # 깨져 보일 수 있다.
    from openpyxl.styles import Font

    korean_font = Font(name="Malgun Gothic", size=10)

    headers = ["대표도면"] + list(rows[0].keys()) if rows else ["대표도면"]
    ws.append(headers)

    for r in rows:
        ws.append([""] + [r.get(h, "") for h in headers[1:]])

    # 이미지 열 크기 지정 (열 너비 단위 ≈ px/7, 행 높이 단위 = pt ≈ px*0.75)
    ws.column_dimensions["A"].width = thumb_px / 7
    for i, h in enumerate(headers[1:], start=2):
        ws.column_dimensions[get_column_letter(i)].width = min(max(len(str(h)) + 6, 14), 45)

    for row in ws.iter_rows():
        for cell in row:
            cell.font = korean_font

    buffers = []  # 저장 전까지 스트림을 살려둬야 함
    for idx, src in enumerate(image_paths):
        row_no = idx + 2
        if not src:
            continue
        try:
            with PILImage.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((thumb_px, thumb_px))
                buf = io.BytesIO()
                im.save(buf, format="PNG")
            buf.seek(0)
            buffers.append(buf)
            img = XLImage(buf)
            ws.add_image(img, f"A{row_no}")
            ws.row_dimensions[row_no].height = thumb_px * 0.75
        except Exception:
            continue  # 이미지 하나가 깨져도 엑셀 생성은 계속

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_excel_bytes(rows: list[dict]) -> bytes:
    """dict 목록을 Excel 파일 바이트로 변환 (다운로드용)."""
    import io

    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="분류결과")
    return buf.getvalue()
