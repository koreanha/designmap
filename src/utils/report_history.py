"""트렌드 리포트 생성 이력 관리.

리포트를 생성할 때마다 '분석 관점(컨텍스트)'과 결과를 함께 저장한다.
같은 관점으로 다시 분석하거나, 과거 리포트를 다시 열어보기 위함이다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.paths import data_path

HISTORY_FILE = Path(data_path("report_history.json"))

# 리포트 본문이 길어 파일이 비대해지지 않도록 보관 개수를 제한
MAX_ENTRIES = 30


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def append_report(
    report_md: str,
    context: str = "",
    criteria_name: str = "",
    stats: dict | None = None,
) -> dict:
    """생성된 리포트를 관점·통계 요약과 함께 이력에 추가."""
    history = load_history()
    entry = {
        "version": (history[-1]["version"] + 1) if history else 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": (context or "").strip(),
        "criteria_name": criteria_name,
        "summary": {
            "총 건수": (stats or {}).get("total_patents"),
            "카테고리 수": len((stats or {}).get("category_distribution", {}) or {}),
        },
        "report": report_md,
    }
    history.append(entry)
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def past_contexts() -> list[str]:
    """이전에 사용한 분석 관점 목록 (최근 순, 중복 제거)."""
    seen: dict[str, None] = {}
    for entry in reversed(load_history()):
        ctx = (entry.get("context") or "").strip()
        if ctx and ctx not in seen:
            seen[ctx] = None
    return list(seen)
