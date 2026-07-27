"""분류 기준 버전 이력 테스트."""
import pytest

from src.utils.criteria_history import (
    HISTORY_FILE,
    append_version,
    diff_criteria,
    get_latest_approved,
    load_history,
)


@pytest.fixture(autouse=True)
def clean_history():
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    yield
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()


def make_criteria(status="proposed", dims=None, keywords=None):
    return {
        "name": "건축구성요소 분류",
        "status": status,
        "dimensions": dims or [
            {"name": "형태", "description": "전체 형태",
             "values": ["직선형", "곡선형"], "weight": 1.0}
        ],
        "trend_keywords": keywords or ["모듈러"],
        "pest_factors": [],
    }


def test_append_version_increments_and_persists():
    e1 = append_version(make_criteria(), "proposed", note="최초 제안")
    e2 = append_version(make_criteria(status="approved"), "approved")
    assert e1["version"] == 1
    assert e2["version"] == 2
    assert len(load_history()) == 2


def test_get_latest_approved_finds_most_recent_approved():
    append_version(make_criteria(status="proposed"), "proposed")
    approved = append_version(make_criteria(status="approved"), "approved")
    append_version(make_criteria(status="proposed"), "proposed")  # 승인 아님
    latest = get_latest_approved()
    assert latest["version"] == approved["version"]


def test_get_latest_approved_none_when_no_approval():
    append_version(make_criteria(status="proposed"), "proposed")
    assert get_latest_approved() is None


def test_diff_detects_dimension_and_keyword_changes():
    old = make_criteria()
    new = make_criteria(
        dims=[
            {"name": "형태", "description": "전체 형태",
             "values": ["직선형", "곡선형", "비정형"], "weight": 1.0},
            {"name": "색채", "description": "주조색",
             "values": ["모노톤", "컬러풀"], "weight": 0.8},
        ],
        keywords=["모듈러", "친환경"],
    )
    diffs = diff_criteria(old, new)
    joined = "\n".join(diffs)
    assert "색채" in joined and "추가" in joined
    assert "친환경" in joined
    assert "['직선형', '곡선형']" in joined  # 값 변경 전후 표시


def test_diff_no_changes():
    c = make_criteria()
    assert diff_criteria(c, c) == ["변경 사항 없음 (동일한 내용)"]


def test_diff_no_previous_version():
    assert diff_criteria(None, make_criteria()) == ["(이전 버전 없음 — 최초 기준입니다)"]


def test_diff_detects_removed_dimension():
    old = make_criteria(dims=[
        {"name": "형태", "description": "d", "values": ["a"], "weight": 1.0},
        {"name": "질감", "description": "d2", "values": ["b"], "weight": 1.0},
    ])
    new = make_criteria(dims=[
        {"name": "형태", "description": "d", "values": ["a"], "weight": 1.0},
    ])
    diffs = diff_criteria(old, new)
    assert any("삭제" in d and "질감" in d for d in diffs)
