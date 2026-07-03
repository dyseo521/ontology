"""제안 백테스트 — vectorbt walk-forward: 제안 전략 vs 보유 지속(baseline).

방법론:
  - 유니버스 KRW 환산 종가 3년, 월간(21영업일) 리밸런스 constant-mix
  - STATIC 모드: 제안 legs 적용 후 목표 비중 vs 현재 비중
  - EVENT_RULE 모드: strategyRule {severityMin, carMax, weightStep, holdDays}
    과거 이벤트 스트림에 규칙 적용 — 조건 충족 이벤트 발생 시 해당 종목 비중을
    weightStep 만큼 holdDays 동안 감축(현금 이동) 후 복원
  - 거래비용: KR 10bp / US 5bp (vectorbt fees, 종목별)
게이트: sharpe > sharpeBaseline AND mdd <= mddBaseline × 1.1
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.store import OntologyStore
from ontoquant.modeling.objective import active_model, record_evaluation

LOOKBACK_BD = 756          # 3년
REBAL_EVERY_BD = 21        # 월간 리밸런스
COST_BP = {"KRW": 0.0010, "USD": 0.0005}
DEFAULT_HOLD_DAYS = 20


def krw_close_matrix(store: OntologyStore, lookback: int = LOOKBACK_BD) -> pd.DataFrame | None:
    fx = ret.load_usdkrw()
    cols: dict[str, pd.Series] = {}
    for inst in store.query("Instrument"):
        close = ret.load_close(inst["instrumentId"])
        if close is None:
            continue
        if inst["currency"] == "USD":
            if fx is None:
                continue
            close = close * fx.reindex(close.index.union(fx.index)).ffill().reindex(close.index)
        cols[inst["instrumentId"]] = close
    if not cols:
        return None
    df = pd.DataFrame(cols).sort_index().ffill().dropna(how="any")
    return df.tail(lookback)


def _weights_schedule(index: pd.DatetimeIndex, base: dict[str, float],
                      columns: list[str], overrides: list[tuple[pd.Timestamp, pd.Timestamp, str, float]],
                      ) -> pd.DataFrame:
    """월간 리밸런스 날짜 + override 변경일에 목표 비중 행을 만든다 (그 외 NaN)."""
    size = pd.DataFrame(np.nan, index=index, columns=columns)
    rebal_days = set(index[::REBAL_EVERY_BD])
    change_days = set()
    for start, end, _, _ in overrides:
        change_days.add(index[index.searchsorted(start)] if index.searchsorted(start) < len(index) else index[-1])
        if index.searchsorted(end) < len(index):
            change_days.add(index[index.searchsorted(end)])
    for day in sorted(rebal_days | change_days):
        w = dict(base)
        for start, end, iid, delta in overrides:
            if start <= day < end and iid in w:
                w[iid] = max(0.0, w[iid] + delta)
        for iid, val in w.items():
            size.loc[day, iid] = val
    return size


def _simulate(close: pd.DataFrame, size: pd.DataFrame, fees: np.ndarray):
    import vectorbt as vbt
    return vbt.Portfolio.from_orders(
        close, size=size, size_type="targetpercent",
        group_by=True, cash_sharing=True, fees=fees, freq="1D",
    )


def _metrics(pf) -> dict:
    value = pf.value()
    sharpe = float(pf.sharpe_ratio())
    mdd = float(pf.max_drawdown())
    try:
        rec = pf.orders.records_readable
        traded = float((rec["Size"].abs() * rec["Price"]).sum())
        years = len(value) / 252
        turnover = traded / float(value.mean()) / max(years, 1e-9)
        n_trades = int(len(rec))
    except Exception:  # noqa: BLE001
        turnover, n_trades = None, None
    return {"sharpe": round(sharpe, 3), "mdd": round(abs(mdd), 4),
            "turnover": round(turnover, 3) if turnover is not None else None,
            "nTrades": n_trades, "value": value}


def _rule_overrides(store: OntologyStore, rule: dict, index: pd.DatetimeIndex,
                    ) -> list[tuple[pd.Timestamp, pd.Timestamp, str, float]]:
    from ontoquant.insights.event_study import get_type_summary
    severity_min = float(rule.get("severityMin", 0.7))
    car_max = float(rule.get("carMax", -0.01))
    step = -abs(float(rule.get("weightStep", 0.02)))
    hold = int(rule.get("holdDays", DEFAULT_HOLD_DAYS))
    type_ok: dict[tuple[str, str], bool] = {}
    overrides = []
    event_types = store.schema.interfaces["Event"].implementedBy
    for e in store.query("Event"):
        sev = e.get("severity")
        if sev is None or sev < severity_min or not e.get("occurredAt"):
            continue
        etype = e["eventType"]
        market = e.get("market") or "US"
        key = (etype, market)
        if key not in type_ok:
            s = get_type_summary(store, etype, market)
            type_ok[key] = bool(s and s["n"] >= 10 and s["carMean"] <= car_max)
        if not type_ok[key]:
            continue
        otype = store.get_type_of(e["eventId"], event_types)
        if not otype:
            continue
        ts = pd.Timestamp(str(e["occurredAt"])[:10])
        if ts < index[0] or ts > index[-1]:
            continue
        pos = index.searchsorted(ts)
        end = index[min(pos + hold, len(index) - 1)]
        for nb in store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out"):
            if float(nb.link.props.get("relevance", 0)) >= 0.9:
                overrides.append((ts, end, nb.pk, step))
    return overrides


def validate_proposal(store: OntologyStore, proposal: dict) -> dict:
    from ontoquant.core.action_functions import apply_legs_to_weights

    close = krw_close_matrix(store)
    if close is None or len(close) < 252:
        raise ValueError("백테스트용 가격 히스토리 부족")
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    cols = list(close.columns)
    fees = np.array([[COST_BP.get(instruments[c]["currency"], 0.001) for c in cols]])

    current = {p["instrumentId"]: float(p.get("weight") or 0.0) for p in store.query("Position")}
    current = {k: v for k, v in current.items() if k in close.columns}

    rule = proposal.get("strategyRule")
    if rule:
        overrides = _rule_overrides(store, rule, close.index)
        strat_size = _weights_schedule(close.index, current, cols, overrides)
        mode = "EVENT_RULE"
        n_events = len(overrides)
    else:
        proposed = apply_legs_to_weights(current, proposal.get("legs") or [])
        proposed = {k: v for k, v in proposed.items() if k in close.columns}
        strat_size = _weights_schedule(close.index, proposed, cols, [])
        mode = "STATIC"
        n_events = 0
    base_size = _weights_schedule(close.index, current, cols, [])

    strat = _metrics(_simulate(close, strat_size, fees))
    base = _metrics(_simulate(close, base_size, fees))
    strat_value = strat.pop("value")
    base_value = base.pop("value")

    # VaR 델타 (전략 vs 베이스라인, 최근 250일 historical)
    def _var95(value: pd.Series) -> float | None:
        r = value.pct_change().dropna().tail(250)
        return float(-np.quantile(r, 0.05)) if len(r) >= 60 else None

    var_s, var_b = _var95(strat_value), _var95(base_value)

    metric_set = {
        "mode": mode, "nRuleEvents": n_events,
        "sharpe": strat["sharpe"], "sharpeBaseline": base["sharpe"],
        "mdd": strat["mdd"], "mddBaseline": base["mdd"],
        "turnover": strat["turnover"], "nTrades": strat["nTrades"],
        "var95": round(var_s, 5) if var_s is not None else None,
        "var95Baseline": round(var_b, 5) if var_b is not None else None,
    }
    gates = [
        ("sharpe > sharpeBaseline", strat["sharpe"] > base["sharpe"],
         f"{strat['sharpe']} vs {base['sharpe']}"),
        ("mdd <= mddBaseline * 1.1", strat["mdd"] <= base["mdd"] * 1.1,
         f"{strat['mdd']} vs {base['mdd']}"),
    ]
    model = active_model(store, "rebalance-strategy") or {"modelVersionId": "rebalance-strategy@1.0.0"}
    run = record_evaluation(store, model["modelVersionId"], "PROPOSAL_BACKTEST",
                            metric_set, (str(close.index[0].date()), str(close.index[-1].date())),
                            gates, run_key=f"backtest:{proposal['proposalId']}")

    # 대시보드용 equity curve (다운샘플, 정규화)
    curve = pd.DataFrame({"strategy": strat_value, "baseline": base_value})
    curve = curve / curve.iloc[0]
    curve = curve.iloc[:: max(1, len(curve) // 160)]
    bt_dir = config.COMPUTED_DIR / "backtests"
    bt_dir.mkdir(parents=True, exist_ok=True)
    (bt_dir / f"{run['runId']}.json").write_text(json.dumps({
        "runId": run["runId"],
        "dates": [str(d.date()) for d in curve.index],
        "strategy": [round(float(v), 4) for v in curve["strategy"]],
        "baseline": [round(float(v), 4) for v in curve["baseline"]],
    }), encoding="utf-8")

    var_delta = (var_s - var_b) if (var_s is not None and var_b is not None) else None
    return {"run": run, "metricSet": metric_set,
            "expectedImpact": {"var95Delta": round(var_delta, 5) if var_delta is not None else None,
                               "betaDelta": None, "hhiDelta": None}}
