"""분류 기준 버전 이력 관리.

기준이 제안/수정/승인될 때마다 스냅샷을 data/criteria_history.json에
누적 저장한다. 데이터를 나눠서 불러올 때 기준이 흔들리는 것을 막기 위해,
이전 승인 버전과의 차이를 비교하고 필요하면 과거 버전으로 복원할 수 있게 한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.paths import data_path

HISTORY_FILE = Path(data_path("criteria_history.json"))


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(history: list[dict]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_version(criteria_dict: dict, action: str, note: str = "") -> dict:
    """기준 스냅샷을 이력에 추가. action: 'proposed'|'refined'|'approved' 등.

    저장된 버전 항목을 반환한다.
    """
    history = load_history()
    version = len(history) + 1
    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "note": note,
        "criteria": criteria_dict,
    }
    history.append(entry)
    _save_history(history)
    return entry


def get_latest_approved() -> dict | None:
    history = load_history()
    for entry in reversed(history):
        if entry["criteria"].get("status") == "approved":
            return entry
    return None


def _dim_index(dims: list[dict]) -> dict[str, dict]:
    return {d["name"]: d for d in dims}


def diff_criteria(old: dict | None, new: dict) -> list[str]:
    """두 기준 딕셔너리(모델 dump)의 차이를 사람이 읽는 문장 목록으로 반환."""
    if old is None:
        return ["(이전 버전 없음 — 최초 기준입니다)"]

    changes: list[str] = []

    if old.get("name") != new.get("name"):
        changes.append(f"이름 변경: '{old.get('name')}' → '{new.get('name')}'")

    old_dims = _dim_index(old.get("dimensions", []))
    new_dims = _dim_index(new.get("dimensions", []))

    for name in new_dims.keys() - old_dims.keys():
        d = new_dims[name]
        changes.append(f"➕ 차원 추가: '{name}' (값: {', '.join(d.get('values', []))})")

    for name in old_dims.keys() - new_dims.keys():
        changes.append(f"➖ 차원 삭제: '{name}'")

    for name in old_dims.keys() & new_dims.keys():
        o, n = old_dims[name], new_dims[name]
        if o.get("values") != n.get("values"):
            changes.append(
                f"✏️ '{name}' 분류 값 변경: {o.get('values')} → {n.get('values')}"
            )
        if o.get("description") != n.get("description"):
            changes.append(f"✏️ '{name}' 설명 변경")
        if o.get("weight") != n.get("weight"):
            changes.append(f"✏️ '{name}' 가중치 변경: {o.get('weight')} → {n.get('weight')}")

    old_kw = set(old.get("trend_keywords", []))
    new_kw = set(new.get("trend_keywords", []))
    if added := new_kw - old_kw:
        changes.append(f"➕ 트렌드 키워드 추가: {', '.join(sorted(added))}")
    if removed := old_kw - new_kw:
        changes.append(f"➖ 트렌드 키워드 제거: {', '.join(sorted(removed))}")

    old_pest = len(old.get("pest_factors", []))
    new_pest = len(new.get("pest_factors", []))
    if old_pest != new_pest:
        changes.append(f"PEST 요인 개수 변경: {old_pest}개 → {new_pest}개")

    if old.get("status") != new.get("status"):
        changes.append(f"상태 변경: {old.get('status')} → {new.get('status')}")

    return changes or ["변경 사항 없음 (동일한 내용)"]
