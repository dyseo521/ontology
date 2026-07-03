"""시계열 parquet I/O — 증분 append 규약.

파일: data/source/prices/{instrumentId ':'→'_'}.parquet  (date, open, high, low, close, adjClose?, volume)
      data/source/factors/{factorId ':'→'_'}.parquet     (date, value)
date 는 문자열 아닌 datetime64[ns] (naive, 거래일)로 저장.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from ontoquant import config


def sanitize(identifier: str) -> str:
    return identifier.replace(":", "_")


def price_path(instrument_id: str) -> Path:
    return config.SOURCE_DIR / "prices" / f"{sanitize(instrument_id)}.parquet"


def factor_path(factor_id: str) -> Path:
    return config.SOURCE_DIR / "factors" / f"{sanitize(factor_id)}.parquet"


def read_ts(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    # parquet 은 us 해상도로 저장될 수 있음 — merge/asof 호환을 위해 ns 로 통일
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df.sort_values("date").reset_index(drop=True)


def last_date(path: Path) -> date | None:
    df = read_ts(path)
    if df is None or df.empty:
        return None
    return df["date"].max().date()


def append_ts(path: Path, new_rows: pd.DataFrame) -> int:
    """date 기준 dedupe 후 append. 추가된 행 수 반환."""
    if new_rows.empty:
        return 0
    new_rows = new_rows.copy()
    new_rows["date"] = pd.to_datetime(new_rows["date"])
    existing = read_ts(path)
    if existing is not None:
        merged = pd.concat([existing, new_rows], ignore_index=True)
        merged = merged.drop_duplicates(subset="date", keep="last").sort_values("date")
        added = len(merged) - len(existing)
    else:
        merged = new_rows.drop_duplicates(subset="date", keep="last").sort_values("date")
        added = len(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.reset_index(drop=True).to_parquet(path, index=False)
    return added
