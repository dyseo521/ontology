"""경로/키 설정. 키 로드 순서: 환경변수 → api-key.txt (로컬 전용)."""
from __future__ import annotations

import os
from pathlib import Path


def find_root(start: Path | None = None) -> Path:
    """레포 루트 탐색: ontology/ 스키마 디렉토리와 data/ 가 있는 디렉토리."""
    env = os.environ.get("ONTOQUANT_ROOT")
    if env:
        return Path(env).resolve()
    cur = (start or Path(__file__)).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "ontology" / "objects").is_dir() and (parent / "data").is_dir():
            return parent
    raise RuntimeError("레포 루트를 찾을 수 없습니다 (ONTOQUANT_ROOT 환경변수로 지정 가능)")


ROOT = find_root()
SCHEMA_DIR = ROOT / "ontology"
DATA_DIR = ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"
COMPUTED_DIR = DATA_DIR / "computed"
WRITEBACK_DIR = DATA_DIR / "writeback"
REFERENCE_DIR = DATA_DIR / "reference"
SCENARIOS_DIR = DATA_DIR / "scenarios"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"
EXPORT_DIR = ROOT / "dashboard" / "public" / "data"

_KEY_NAMES = ("FRED_API_KEY", "DART_API_KEY", "TIINGO_API_KEY")


def load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    keyfile = ROOT / "api-key.txt"
    if keyfile.exists():
        for line in keyfile.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    for name in _KEY_NAMES:
        if os.environ.get(name):
            keys[name] = os.environ[name]
    return keys


def get_key(name: str) -> str:
    keys = load_keys()
    if name not in keys or not keys[name]:
        raise RuntimeError(f"{name} 가 없습니다. api-key.txt 또는 환경변수로 제공하세요.")
    return keys[name]
