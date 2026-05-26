from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
MATERIALS_DIR = DATA_DIR / "materials"
EXPORTS_DIR = DATA_DIR / "exports"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "app.db"


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, MATERIALS_DIR, EXPORTS_DIR, TMP_DIR):
        path.mkdir(parents=True, exist_ok=True)

