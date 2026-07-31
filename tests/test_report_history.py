"""트렌드 리포트 이력 테스트."""
import pytest

from src.utils.report_history import (
    HISTORY_FILE,
    MAX_ENTRIES,
    append_report,
    load_history,
    past_contexts,
)

STATS = {"total_patents": 30, "category_distribution": {"박스형": 12, "곡면형": 18}}


@pytest.fixture(autouse=True)
def clean_history():
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    yield
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()


def test_append_report_records_context_and_body():
    entry = append_report("# 리포트 A\n본문", "향후 5년 물류로봇 방향", "물류로봇 기준", STATS)
    assert entry["version"] == 1
    saved = load_history()[0]
    assert saved["context"] == "향후 5년 물류로봇 방향"
    assert saved["criteria_name"] == "물류로봇 기준"
    assert saved["report"].startswith("# 리포트 A")
    assert saved["summary"]["총 건수"] == 30
    assert saved["summary"]["카테고리 수"] == 2


def test_version_increments():
    append_report("A", "관점1")
    append_report("B", "관점2")
    assert [e["version"] for e in load_history()] == [1, 2]


def test_past_contexts_recent_first_and_deduped():
    append_report("A", "관점 가")
    append_report("B", "관점 나")
    append_report("C", "관점 가")  # 중복
    append_report("D", "")         # 빈 관점은 제외
    assert past_contexts() == ["관점 가", "관점 나"]


def test_history_capped_at_max_entries():
    for i in range(MAX_ENTRIES + 8):
        append_report(f"R{i}", f"관점{i}")
    history = load_history()
    assert len(history) == MAX_ENTRIES
    # 최신 항목이 남아 있어야 함
    assert history[-1]["report"] == f"R{MAX_ENTRIES + 7}"


def test_load_history_handles_missing_and_corrupt():
    assert load_history() == []
    HISTORY_FILE.write_text("깨진 JSON", encoding="utf-8")
    assert load_history() == []
