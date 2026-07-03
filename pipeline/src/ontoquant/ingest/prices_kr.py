"""KR 주가 — Naver siseJson (키리스, 1차 소스).

응답 형식: 파이썬 리터럴 유사 배열
  [["날짜","시가","고가","저가","종가","거래량","외국인소진율"], ["20240102",...], ...]
"""
from __future__ import annotations

import ast
import json
from datetime import date, timedelta

import pandas as pd

from ontoquant.ingest import tsio
from ontoquant.ingest.http import BROWSER_UA, get

URL = "https://api.finance.naver.com/siseJson.naver"
BACKFILL_START = date(2021, 1, 1)


def fetch_naver_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    resp = get(URL, params={
        "symbol": symbol, "requestType": "1",
        "startTime": start.strftime("%Y%m%d"), "endTime": end.strftime("%Y%m%d"),
        "timeframe": "day",
    }, headers={"User-Agent": BROWSER_UA})
    text = resp.text.strip()
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        rows = ast.literal_eval(text)
    if not rows or len(rows) < 2:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows[1:], columns=rows[0][: len(rows[1])])
    df = df.rename(columns={"날짜": "date", "시가": "open", "고가": "high",
                            "저가": "low", "종가": "close", "거래량": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"])


def ingest_instrument(instrument: dict, today: date | None = None) -> dict:
    today = today or date.today()
    path = tsio.price_path(instrument["instrumentId"])
    last = tsio.last_date(path)
    start = (last + timedelta(days=1)) if last else BACKFILL_START
    if start > today:
        return {"instrumentId": instrument["instrumentId"], "added": 0, "status": "up-to-date"}
    df = fetch_naver_daily(instrument["ticker"], start, today)
    added = tsio.append_ts(path, df)
    return {"instrumentId": instrument["instrumentId"], "added": added, "status": "ok"}


def run(store, today: date | None = None) -> list[dict]:
    results = []
    for inst in store.query("Instrument", where={"priceSource": "NAVER"}):
        try:
            results.append(ingest_instrument(inst, today))
        except Exception as exc:  # noqa: BLE001 — 부분 실패 허용
            results.append({"instrumentId": inst["instrumentId"], "added": 0,
                            "status": f"error: {exc}"})
    return results
