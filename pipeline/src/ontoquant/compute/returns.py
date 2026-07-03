"""수익률/가치 시계열 — 가격 parquet → 종목 수익률, 환율 변환, 포트폴리오 히스토리.

규약:
- 수익률은 소수(decimal) 단순 수익률
- US 종목은 adjClose(분할/배당 조정), KR 종목은 close(네이버 수정주가)
- 포트폴리오 히스토리는 "현재 보유수량을 과거에 고정 적용" (historical simulation 표준)
"""
from __future__ import annotations

import pandas as pd

from ontoquant.ingest import tsio


def load_close(instrument_id: str, prefer_adj: bool = True) -> pd.Series | None:
    df = tsio.read_ts(tsio.price_path(instrument_id))
    if df is None or df.empty:
        return None
    col = "adjClose" if prefer_adj and "adjClose" in df.columns else "close"
    s = df.set_index("date")[col].astype(float)
    s.name = instrument_id
    return s


def load_returns(instrument_id: str) -> pd.Series | None:
    s = load_close(instrument_id)
    if s is None:
        return None
    return s.pct_change().dropna()


def load_usdkrw() -> pd.Series | None:
    """FRED DEXKOUS 레벨 (KRW per USD)."""
    df = tsio.read_ts(tsio.factor_path("MACRO:USDKRW"))
    if df is None or df.empty:
        return None
    return df.set_index("date")["value"].astype(float)


def portfolio_history(store, lookback_days: int = 600) -> pd.DataFrame | None:
    """포지션별 KRW 평가액 + 총액. 반환: 컬럼=positionId..., 'TOTAL'."""
    positions = store.query("Position")
    if not positions:
        return None
    fx = load_usdkrw()
    frames: dict[str, pd.Series] = {}
    for pos in positions:
        # writeback(portfolio.json)에 없는 유령 포지션(과거 computed 스냅샷 잔재) 제외
        if pos.get("quantity") is None:
            continue
        inst = store.get("Instrument", pos["instrumentId"])
        if inst is None:
            continue
        close = load_close(pos["instrumentId"])
        if close is None:
            continue
        value = close * float(pos["quantity"])
        if inst["currency"] == "USD":
            if fx is None:
                continue
            value = value * fx.reindex(value.index.union(fx.index)).ffill().reindex(value.index)
        frames[pos["positionId"]] = value
    if not frames:
        return None
    df = pd.DataFrame(frames).sort_index()
    df = df.ffill().dropna(how="any")
    df = df.tail(lookback_days)
    df["TOTAL"] = df.sum(axis=1)
    return df


def portfolio_returns(history: pd.DataFrame) -> pd.Series:
    return history["TOTAL"].pct_change().dropna()
