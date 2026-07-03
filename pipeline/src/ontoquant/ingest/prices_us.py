"""US 주가 — Tiingo EOD (무료 티어: 50/hr, 1000/day, 500심볼/월).

일일 실행 기준 심볼당 1 요청 (~8건) — 예산의 1% 미만.
수익률 계산은 adjClose (분할/배당 조정) 사용.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ontoquant.config import get_key
from ontoquant.ingest import tsio
from ontoquant.ingest.http import get

BACKFILL_START = date(2021, 1, 1)


def fetch_tiingo_daily(ticker: str, start: date, end: date) -> pd.DataFrame:
    resp = get(
        f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
        params={"startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json"},
        headers={"Authorization": f"Token {get_key('TIINGO_API_KEY')}",
                 "Content-Type": "application/json"},
    )
    rows = resp.json()
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "adjClose", "volume"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"].str[:10])
    return df[["date", "open", "high", "low", "close", "adjClose", "volume"]]


def ingest_instrument(instrument: dict, today: date | None = None) -> dict:
    today = today or date.today()
    path = tsio.price_path(instrument["instrumentId"])
    last = tsio.last_date(path)
    start = (last + timedelta(days=1)) if last else BACKFILL_START
    if start > today:
        return {"instrumentId": instrument["instrumentId"], "added": 0, "status": "up-to-date"}
    df = fetch_tiingo_daily(instrument["ticker"], start, today)
    added = tsio.append_ts(path, df)
    return {"instrumentId": instrument["instrumentId"], "added": added, "status": "ok"}


def run(store, today: date | None = None) -> list[dict]:
    results = []
    for inst in store.query("Instrument", where={"priceSource": "TIINGO"}):
        try:
            results.append(ingest_instrument(inst, today))
        except Exception as exc:  # noqa: BLE001
            results.append({"instrumentId": inst["instrumentId"], "added": 0,
                            "status": f"error: {exc}"})
    return results
