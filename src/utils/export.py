"""분류 결과 내보내기 유틸 (Excel 생성, 대표도면 삽입).

streamlit에 의존하지 않아 단독으로 테스트할 수 있다.
"""
from __future__ import annotations

import json
from pathlib import Path


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

    headers = ["대표도면"] + list(rows[0].keys()) if rows else ["대표도면"]
    ws.append(headers)

    for r in rows:
        ws.append([""] + [r.get(h, "") for h in headers[1:]])

    # 이미지 열 크기 지정 (열 너비 단위 ≈ px/7, 행 높이 단위 = pt ≈ px*0.75)
    ws.column_dimensions["A"].width = thumb_px / 7
    for i, h in enumerate(headers[1:], start=2):
        ws.column_dimensions[get_column_letter(i)].width = min(max(len(str(h)) + 6, 14), 45)

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
