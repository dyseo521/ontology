"""리스크 지표 — historical simulation VaR, 변동성, MDD, 집중도 + 포지션 평가.

산출(모두 computed 계층 스냅샷):
- Position: lastPriceLocal, marketValueBase, weight, dailyPnlBase, unrealizedPnlPct
- Portfolio: totalValueBase, dailyPnlBase
- RiskMetric: 포트폴리오 VAR_95_1D / VOL_30D / BETA_MKT / MDD_1Y / HHI + 포지션 CONTRIB_VAR
- data/computed/risk_series.parquet: 대시보드 차트용 롤링 시계열
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.store import LinkRecord, OntologyStore

VAR_WINDOW = 250
VOL_WINDOW = 30


def max_drawdown(values: pd.Series) -> float:
    peak = values.cummax()
    dd = values / peak - 1.0
    return float(-dd.min())


def run(store: OntologyStore) -> dict:
    history = ret.portfolio_history(store)
    if history is None or history.empty:
        return {"status": "no-data"}
    as_of = history.index.max()
    as_of_str = str(as_of.date())
    port_ret = ret.portfolio_returns(history)
    total = float(history["TOTAL"].iloc[-1])
    prev_total = float(history["TOTAL"].iloc[-2]) if len(history) > 1 else total

    fx = ret.load_usdkrw()
    fx_last = float(fx.dropna().iloc[-1]) if fx is not None else None

    portfolio = store.query("Portfolio")[0]
    pf_id = portfolio["portfolioId"]
    limits = portfolio.get("riskLimits", {}) or {}

    # ── 포지션 평가 스냅샷 ────────────────────────────────────────────
    pos_snapshots: list[dict] = []
    weights: dict[str, float] = {}
    for pos in store.query("Position", where={"portfolioId": pf_id}):
        pid = pos["positionId"]
        if pid not in history.columns:
            continue
        inst = store.get("Instrument", pos["instrumentId"])
        close = ret.load_close(pos["instrumentId"], prefer_adj=False)
        last_price = float(close.iloc[-1]) if close is not None else None
        value = float(history[pid].iloc[-1])
        prev_value = float(history[pid].iloc[-2]) if len(history) > 1 else value
        weight = value / total if total else 0.0
        weights[pid] = weight
        unreal = None
        if last_price is not None and pos.get("avgCostLocal"):
            unreal = last_price / float(pos["avgCostLocal"]) - 1.0
        pos_snapshots.append({
            "positionId": pid, "portfolioId": pf_id, "instrumentId": pos["instrumentId"],
            "lastPriceLocal": last_price,
            "marketValueBase": round(value, 2),
            "weight": round(weight, 6),
            "dailyPnlBase": round(value - prev_value, 2),
            "unrealizedPnlPct": round(unreal, 6) if unreal is not None else None,
        })
    store.replace_objects("computed", "Position", pos_snapshots)
    store.replace_objects("computed", "Portfolio", [{
        "portfolioId": pf_id,
        "totalValueBase": round(total, 2),
        "dailyPnlBase": round(total - prev_total, 2),
    }])

    # ── 포트폴리오 지표 ──────────────────────────────────────────────
    tail = port_ret.tail(VAR_WINDOW)
    var95 = float(-np.quantile(tail, 0.05)) if len(tail) >= 60 else None
    vol30 = float(port_ret.tail(VOL_WINDOW).std() * np.sqrt(252)) if len(port_ret) >= VOL_WINDOW else None
    mdd = max_drawdown(history["TOTAL"].tail(252))
    hhi = float(sum(w * w for w in weights.values()))

    beta_mkt = None
    bench_id = portfolio.get("benchmark")
    if bench_id:
        bench_close = ret.load_close(bench_id)
        bench_inst = store.get("Instrument", bench_id)
        if bench_close is not None:
            if bench_inst and bench_inst["currency"] == "USD" and fx is not None:
                bench_close = bench_close * fx.reindex(
                    bench_close.index.union(fx.index)).ffill().reindex(bench_close.index)
            bench_ret = bench_close.pct_change().dropna()
            df = pd.concat([port_ret.rename("p"), bench_ret.rename("b")], axis=1).dropna().tail(252)
            if len(df) >= 60 and df["b"].var() > 0:
                beta_mkt = float(df["p"].cov(df["b"]) / df["b"].var())

    metrics: list[dict] = []
    metric_links: list[LinkRecord] = []

    def add_metric(scope_type: str, scope_id: str, mtype: str, value: float | None,
                   limit: float | None = None):
        if value is None:
            return
        mid = f"{scope_type}:{scope_id}:{mtype}"
        metrics.append({
            "metricId": mid, "scopeType": scope_type, "scopeId": scope_id,
            "metricType": mtype, "value": round(float(value), 6),
            "asOfDate": as_of_str,
            "limitBreached": bool(limit is not None and value > limit),
            "limitValue": limit,
        })
        link_type = "metricScopePortfolio" if scope_type == "PORTFOLIO" else "metricScopePosition"
        target_type = "Portfolio" if scope_type == "PORTFOLIO" else "Position"
        metric_links.append(LinkRecord(link_type, "RiskMetric", mid, target_type, scope_id))

    add_metric("PORTFOLIO", pf_id, "VAR_95_1D", var95, limits.get("maxVar95"))
    add_metric("PORTFOLIO", pf_id, "VOL_30D", vol30)
    add_metric("PORTFOLIO", pf_id, "MDD_1Y", mdd)
    add_metric("PORTFOLIO", pf_id, "HHI", hhi)
    add_metric("PORTFOLIO", pf_id, "BETA_MKT", beta_mkt)

    # 포지션 VaR 기여 (Euler 분해: w_i * cov(r_i, r_p)/var(r_p) * VaR_p)
    if var95 is not None and port_ret.var() > 0:
        pos_ret = history.drop(columns="TOTAL").pct_change().dropna().tail(VAR_WINDOW)
        aligned_p = port_ret.reindex(pos_ret.index)
        for pid in pos_ret.columns:
            beta_i = float(pos_ret[pid].cov(aligned_p) / aligned_p.var())
            add_metric("POSITION", pid, "CONTRIB_VAR", weights.get(pid, 0.0) * beta_i * var95)

    store.replace_objects("computed", "RiskMetric", metrics)
    pf_links = [l for l in metric_links if l.linkType == "metricScopePortfolio"]
    pos_links = [l for l in metric_links if l.linkType == "metricScopePosition"]
    store.replace_links("computed", "metricScopePortfolio", pf_links)
    store.replace_links("computed", "metricScopePosition", pos_links)

    # ── 대시보드용 롤링 시계열 ────────────────────────────────────────
    curve = history["TOTAL"].tail(252 + VAR_WINDOW)
    r = curve.pct_change()
    series = pd.DataFrame({
        "date": curve.index,
        "totalValueBase": curve.values,
        "drawdown": (curve / curve.cummax() - 1.0).values,
        "var95": (-r.rolling(VAR_WINDOW).quantile(0.05)).values,
        "vol30": (r.rolling(VOL_WINDOW).std() * np.sqrt(252)).values,
    }).tail(252)
    config.COMPUTED_DIR.mkdir(parents=True, exist_ok=True)
    series.to_parquet(config.COMPUTED_DIR / "risk_series.parquet", index=False)

    breaches = [m for m in metrics if m["limitBreached"]]
    # 종목별 비중 한도 검사 (인사이트 규칙이 소비)
    max_w = limits.get("maxWeightPerName")
    weight_breaches = [
        {"positionId": pid, "weight": w, "limit": max_w}
        for pid, w in weights.items() if max_w and w > max_w
    ]
    return {
        "asOf": as_of_str, "totalValueBase": total,
        "var95": var95, "vol30": vol30, "mdd": mdd, "hhi": hhi, "betaMkt": beta_mkt,
        "limitBreaches": breaches, "weightBreaches": weight_breaches,
        "positions": len(pos_snapshots),
    }
