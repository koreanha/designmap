"""프로젝트 데이터 경로 헬퍼.

실행 위치(현재 작업 디렉토리)가 어디든, 데이터/DB가 항상 코드 폴더 옆의
`data/` 디렉토리에 일관되게 저장되도록 절대 경로를 제공한다.

(macOS 보호 폴더 회피용 chdir 등으로 cwd가 바뀌어도 DB/결과 위치가
흔들리지 않게 하기 위함)
"""
from __future__ import annotations

from pathlib import Path

# .../designmap/src/utils/paths.py → parents[2] == 프로젝트 루트(designmap/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def data_path(*parts: str) -> str:
    """data 디렉토리 하위 경로를 절대 경로 문자열로 반환 (디렉토리 자동 생성)."""
    ensure_data_dir()
    return str(DATA_DIR.joinpath(*parts))


def default_db_url() -> str:
    """SQLite 절대 경로 URL. data 디렉토리를 보장한다."""
    ensure_data_dir()
    return f"sqlite+aiosqlite:///{DATA_DIR / 'designmap.db'}"


_DATA_FILES = [
    "designmap.db",
    "proposed_criteria.json",
    "classification_results.json",
    "parsed_patents.xlsx",
    "trend_report.md",
]


def reset_data(backup: bool = True) -> str | None:
    """모든 작업 데이터(DB·결과 파일·도면)를 삭제하고 초기화. 삭제 전 백업(기본)."""
    import shutil

    ensure_data_dir()
    backup_dir = backup_data() if backup else None
    for name in _DATA_FILES:
        f = DATA_DIR / name
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass
    drawings = DATA_DIR / "drawings"
    if drawings.exists():
        shutil.rmtree(drawings, ignore_errors=True)
    return backup_dir


def backup_data() -> str:
    """DB와 결과 파일을 data/backups/<시각>/ 로 복사. 백업 폴더 경로 반환."""
    import shutil
    from datetime import datetime

    ensure_data_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = DATA_DIR / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for name in [
        "designmap.db",
        "proposed_criteria.json",
        "classification_results.json",
        "parsed_patents.xlsx",
        "trend_report.md",
    ]:
        src = DATA_DIR / name
        if src.exists():
            shutil.copy2(src, dest / name)
    return str(dest)
