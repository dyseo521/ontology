"""FRED 매크로 시계열 (~120 req/min 한도, 시리즈당 1 요청)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ontoquant.config import get_key
from ontoquant.ingest import tsio
from ontoquant.ingest.http import get

URL = "https://api.stlouisfed.org/fred/series/observations"
BACKFILL_START = date(2021, 1, 1)


def fetch_series(series_id: str, start: date, end: date) -> pd.DataFrame:
    resp = get(URL, params={
        "series_id": series_id, "api_key": get_key("FRED_API_KEY"),
        "file_type": "json",
        "observation_start": start.isoformat(), "observation_end": end.isoformat(),
    })
    obs = resp.json().get("observations", [])
    df = pd.DataFrame(obs, columns=["date", "value"]) if obs else pd.DataFrame(columns=["date", "value"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "." → NaN
    return df.dropna(subset=["value"])[["date", "value"]]


def run(store, today: date | None = None) -> list[dict]:
    today = today or date.today()
    results = []
    for factor in store.query("Factor", where={"source": "FRED"}):
        path = tsio.factor_path(factor["factorId"])
        last = tsio.last_date(path)
        start = (last + timedelta(days=1)) if last else BACKFILL_START
        if start > today:
            results.append({"factorId": factor["factorId"], "added": 0, "status": "up-to-date"})
            continue
        try:
            df = fetch_series(factor["sourceSeriesId"], start, today)
            added = tsio.append_ts(path, df)
            results.append({"factorId": factor["factorId"], "added": added, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            results.append({"factorId": factor["factorId"], "added": 0, "status": f"error: {exc}"})
    return results
