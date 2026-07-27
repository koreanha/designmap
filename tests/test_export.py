"""분류 결과 내보내기(Excel·대표도면 삽입) 테스트."""
import io
import json
import zipfile

import pytest
from openpyxl import load_workbook
from PIL import Image

from src.utils.export import (
    representative_image,
    to_excel_bytes,
    to_excel_with_images_bytes,
)


@pytest.fixture
def images(tmp_path):
    paths = []
    for i, color in enumerate(["red", "green", "blue"]):
        p = tmp_path / f"draw{i}.png"
        Image.new("RGB", (900, 700), color).save(p)
        paths.append(str(p))
    return paths


def test_representative_drawing_preferred(images):
    drawings_json = json.dumps([
        {"file_path": images[1], "drawing_type": "perspective"},
        {"file_path": images[0], "drawing_type": "representative"},
    ])
    assert representative_image(drawings_json) == images[0]


def test_falls_back_to_first_existing_file(images):
    drawings_json = json.dumps([
        {"file_path": "/없는/경로.png", "drawing_type": "front"},
        {"file_path": images[2], "drawing_type": "front"},
    ])
    assert representative_image(drawings_json) == images[2]


def test_representative_image_handles_empty_and_invalid():
    assert representative_image(None) is None
    assert representative_image("[]") is None
    assert representative_image("깨진 JSON") is None


def test_excel_embeds_images_and_survives_broken_paths(images):
    rows = [{"출원번호": f"A{i}", "물품명": "Transfer robot"} for i in range(3)]
    data = to_excel_with_images_bytes(rows, [images[0], None, "/없는/파일.png"])

    assert data[:2] == b"PK"  # 유효한 xlsx
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        media = [n for n in z.namelist() if n.startswith("xl/media/")]
    assert len(media) == 1  # 유효한 이미지 1건만 삽입, 나머지는 건너뜀

    ws = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws[1]] == ["대표도면", "출원번호", "물품명"]
    assert ws["B2"].value == "A0"
    assert ws.row_dimensions[2].height > 0  # 이미지가 보이도록 행 높이 확대


def test_excel_without_images_still_works():
    rows = [{"출원번호": "A0", "주분류": "곡선형"}]
    data = to_excel_bytes(rows)
    ws = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws[1]] == ["출원번호", "주분류"]
