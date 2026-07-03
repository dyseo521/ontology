"""제안 백테스트 — 누출 없는 검증 (PIT 규칙 판정 + purged walk-forward + DSR).

STATIC 모드 (legs 고정 제안):
  전체 3년, 제안 비중 vs 현재 비중 constant-mix (월간 리밸런스, 거래비용).
  게이트: sharpe > baseline AND mdd <= baseline×1.1. PSR 은 정보 표기.

EVENT_RULE 모드 (이벤트 규칙 전략) — purged walk-forward:
  - 규칙 발동 판정은 각 이벤트 발생일 기준 PIT CAR 통계만 사용 (결과론적 학습 차단)
  - anchored 4폴드, test 126bd, embargo 26bd(=최대 보유 20 + 이벤트창 5 + 1)
  - 그리드 탐색 시 train 에서 파라미터 선택, test(OOS)만 보고
  - DSR(Bailey-López de Prado) >= 0.95 게이트, 시도 수 = 그리드 + 과거 rule-hash 이력
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.store import OntologyStore
from ontoquant.modeling.deflated_sharpe import deflated_sharpe, probabilistic_sharpe
from ontoquant.modeling.objective import active_model, count_trials, record_evaluation, rule_hash

LOOKBACK_BD = 756          # 3년
REBAL_EVERY_BD = 21        # 월간 리밸런스
COST_BP = {"KRW": 0.0010, "USD": 0.0005}
DEFAULT_HOLD_DAYS = 20
N_FOLDS = 4
TEST_BD = 126
EMBARGO_BD = 26            # max(holdDays) + EVT_END + 1
MIN_TRAIN_BD = 252
DEFAULT_GRID = {
    "severityMin": [0.6, 0.7, 0.8],
    "carMax": [-0.005, -0.01, -0.02],
    "weightStep": [0.02],
    "holdDays": [10, 20],
}


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
                      columns: list[str],
                      overrides: list[tuple[pd.Timestamp, pd.Timestamp, str, float]],
                      ) -> pd.DataFrame:
    """월간 리밸런스 + override 변경일에 목표 비중 행 (그 외 NaN)."""
    size = pd.DataFrame(np.nan, index=index, columns=columns)
    rebal_days = set(index[::REBAL_EVERY_BD])
    change_days = set()
    for start, end, _, _ in overrides:
        s_pos = index.searchsorted(start)
        e_pos = index.searchsorted(end)
        if s_pos < len(index):
            change_days.add(index[s_pos])
        if e_pos < len(index):
            change_days.add(index[e_pos])
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


class _PitMeanLookup:
    """(eventType, market) 별 knownAt 정렬 + prefix sum — O(log n) expanding CAR 평균."""

    def __init__(self, cars: pd.DataFrame):
        self._groups: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
        for (etype, market), g in cars.groupby(["eventType", "market"]):
            g = g.sort_values("knownAt")
            self._groups[(etype, market)] = (
                g["knownAt"].to_numpy(), np.cumsum(g["car"].to_numpy()))

    def stats(self, etype: str, market: str, as_of: pd.Timestamp) -> tuple[int, float] | None:
        g = self._groups.get((etype, market))
        if g is None:
            return None
        known, cumsum = g
        n = int(np.searchsorted(known, np.datetime64(as_of), side="right"))
        if n == 0:
            return None
        return n, float(cumsum[n - 1] / n)


def _rule_overrides(store: OntologyStore, rule: dict, index: pd.DatetimeIndex,
                    cars: pd.DataFrame | None,
                    lookup: "_PitMeanLookup | None" = None,
                    ) -> list[tuple[pd.Timestamp, pd.Timestamp, str, float]]:
    """이벤트 규칙 → 비중 오버라이드. 발동 판정은 이벤트 발생일 기준 PIT 통계만 사용
    (결과론적 학습 차단 — 규칙은 그 시점에 알 수 있던 CAR 평균만 본다)."""
    if cars is None or cars.empty:
        return []
    lookup = lookup or _PitMeanLookup(cars)
    severity_min = float(rule.get("severityMin", 0.7))
    car_max = float(rule.get("carMax", -0.01))
    step = -abs(float(rule.get("weightStep", 0.02)))
    hold = int(rule.get("holdDays", DEFAULT_HOLD_DAYS))
    overrides = []
    event_types = store.schema.interfaces["Event"].implementedBy
    for e in store.query("Event"):
        sev = e.get("severity")
        if sev is None or sev < severity_min or not e.get("occurredAt"):
            continue
        ts = pd.Timestamp(str(e["occurredAt"])[:10])
        if ts < index[0] or ts > index[-1]:
            continue
        market = e.get("market") or ("KR" if str(e["eventId"]).startswith(("dart", "naver")) else "US")
        # PIT: 이 이벤트 발생 시점까지 알려진 표본으로만 타입 판정 (누출 차단의 핵심)
        pit = lookup.stats(e["eventType"], market, ts)
        if pit is None or pit[0] < 10 or pit[1] > car_max:
            continue
        otype = store.get_type_of(e["eventId"], event_types)
        if not otype:
            continue
        pos = index.searchsorted(ts)
        end = index[min(pos + hold, len(index) - 1)]
        for nb in store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out"):
            if float(nb.link.props.get("relevance", 0)) >= 0.9:
                overrides.append((ts, end, nb.pk, step))
    return overrides


def _fold_bounds(index: pd.DatetimeIndex, n_folds: int = N_FOLDS,
                 test_bd: int = TEST_BD, embargo: int = EMBARGO_BD,
                 min_train: int = MIN_TRAIN_BD) -> list[tuple[slice, slice]]:
    """anchored walk-forward: (train_slice, test_slice) 목록. train 끝 + embargo = test 시작."""
    folds = []
    n = len(index)
    for k in range(n_folds):
        test_start = min_train + k * test_bd
        test_end = min(test_start + test_bd, n)
        train_end = test_start - embargo
        if train_end < min_train // 2 or test_start >= n:
            break
        folds.append((slice(0, train_end), slice(test_start, test_end)))
    return folds


def _clip_overrides(overrides, boundary: pd.Timestamp):
    """purge: 경계를 넘는 보유 오버라이드는 경계에서 절단."""
    return [(s, min(e, boundary), iid, d) for s, e, iid, d in overrides if s < boundary]


def _sim_window(close: pd.DataFrame, base: dict[str, float], overrides, fees) -> dict:
    size = _weights_schedule(close.index, base, list(close.columns), overrides)
    return _metrics(_simulate(close, size, fees))


def _grid_combos(grid: dict) -> list[dict]:
    from itertools import product
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in product(*(grid[k] for k in keys))]


def walk_forward_validate(store: OntologyStore, proposal: dict) -> dict:
    """EVENT_RULE 전용 purged walk-forward + DSR. WALK_FORWARD EvaluationRun 기록."""
    from ontoquant.insights.event_study import load_cars

    close = krw_close_matrix(store)
    if close is None or len(close) < MIN_TRAIN_BD + TEST_BD:
        raise ValueError("walk-forward 에 필요한 가격 히스토리 부족")
    cars = load_cars()
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    cols = list(close.columns)
    fees = np.array([[COST_BP.get(instruments[c]["currency"], 0.001) for c in cols]])
    current = {p["instrumentId"]: float(p.get("weight") or 0.0) for p in store.query("Position")}
    current = {k: v for k, v in current.items() if k in close.columns}

    rule = dict(proposal.get("strategyRule") or {})
    grid_spec = rule.pop("grid", None)
    combos = _grid_combos(DEFAULT_GRID if grid_spec is True else grid_spec) if grid_spec else [rule]

    folds = _fold_bounds(close.index)
    oos_returns: list[pd.Series] = []
    oos_base_returns: list[pd.Series] = []
    n_oos_events = 0
    best_params_per_fold = []
    # 시도 SR 풀 (DSR 의 V[{SRn}]): 각 조합의 전기간 성과
    trial_srs: list[float] = []
    lookup = _PitMeanLookup(cars) if cars is not None and not cars.empty else None
    combo_overrides = {rule_hash(c): _rule_overrides(store, c, close.index, cars, lookup)
                       for c in combos}
    for c in combos:
        m = _sim_window(close, current, combo_overrides[rule_hash(c)], fees)
        r = m["value"].pct_change().dropna()
        if len(r) > 30 and float(r.std()) > 0:
            trial_srs.append(float(r.mean() / r.std()))

    for train_sl, test_sl in folds:
        train_close = close.iloc[train_sl]
        test_close = close.iloc[test_sl]
        boundary = train_close.index[-1]
        # train 에서 조합 선택 (탐색 없으면 그대로)
        best, best_sr = combos[0], -np.inf
        if len(combos) > 1:
            for c in combos:
                ov = _clip_overrides(
                    [o for o in combo_overrides[rule_hash(c)] if o[0] <= boundary], boundary)
                m = _sim_window(train_close, current, ov, fees)
                if m["sharpe"] > best_sr:
                    best, best_sr = c, m["sharpe"]
        best_params_per_fold.append(best)
        # test(OOS) 실행 — embargo 이후 구간, 해당 구간 이벤트만
        test_ov = [o for o in combo_overrides[rule_hash(best)]
                   if test_close.index[0] <= o[0] <= test_close.index[-1]]
        n_oos_events += len(test_ov)
        strat = _sim_window(test_close, current, test_ov, fees)
        base = _sim_window(test_close, current, [], fees)
        oos_returns.append(strat["value"].pct_change().dropna())
        oos_base_returns.append(base["value"].pct_change().dropna())

    oos = pd.concat(oos_returns)
    oos_base = pd.concat(oos_base_returns)
    dsr_trials = trial_srs + [None] * 0
    hist_n, hist_srs = count_trials(store, "rebalance-strategy")
    dsr = deflated_sharpe(oos, trial_srs + hist_srs)
    oos_sharpe = float(oos.mean() / oos.std() * np.sqrt(252)) if oos.std() > 0 else 0.0
    oos_base_sharpe = float(oos_base.mean() / oos_base.std() * np.sqrt(252)) if oos_base.std() > 0 else 0.0

    def _mdd(r: pd.Series) -> float:
        curve = (1 + r).cumprod()
        return float(-(curve / curve.cummax() - 1).min())

    metric_set = {
        "mode": "EVENT_RULE_WF", "ruleHash": rule_hash(rule if len(combos) == 1 else {"grid": True, **DEFAULT_GRID}),
        "folds": len(folds), "nOosEvents": n_oos_events,
        "oosSharpe": round(oos_sharpe, 3), "oosSharpeBaseline": round(oos_base_sharpe, 3),
        "oosMdd": round(_mdd(oos), 4), "oosMddBaseline": round(_mdd(oos_base), 4),
        "dsr": dsr["dsr"], "psr0": dsr["psr0"], "nTrials": dsr["nTrials"] + hist_n,
        "srAnnual": dsr["srAnnual"],
        "bestParams": best_params_per_fold[-1] if best_params_per_fold else rule,
        "oosDays": int(len(oos)),
    }
    gates = [
        ("oosSharpe > oosSharpeBaseline", oos_sharpe > oos_base_sharpe,
         f"{metric_set['oosSharpe']} vs {metric_set['oosSharpeBaseline']}"),
        ("oosMdd <= oosMddBaseline * 1.1", metric_set["oosMdd"] <= metric_set["oosMddBaseline"] * 1.1,
         f"{metric_set['oosMdd']} vs {metric_set['oosMddBaseline']}"),
        ("nOosEvents >= 5", n_oos_events >= 5,
         f"nOosEvents={n_oos_events}" + ("" if n_oos_events >= 5 else " (표본 부족)")),
        ("dsr >= 0.95", (dsr["dsr"] or 0) >= 0.95, f"dsr={dsr['dsr']}"),
    ]
    model = active_model(store, "rebalance-strategy") or {"modelVersionId": "rebalance-strategy@1.0.0"}
    run = record_evaluation(store, model["modelVersionId"], "WALK_FORWARD",
                            metric_set, (str(close.index[0].date()), str(close.index[-1].date())),
                            gates, run_key=f"wf:{proposal['proposalId']}")
    _write_curve(run["runId"], (1 + oos).cumprod(), (1 + oos_base).cumprod())
    return {"run": run, "metricSet": metric_set, "expectedImpact": None}


def _write_curve(run_id: str, strat_curve: pd.Series, base_curve: pd.Series) -> None:
    curve = pd.DataFrame({"strategy": strat_curve, "baseline": base_curve}).dropna()
    curve = curve / curve.iloc[0]
    curve = curve.iloc[:: max(1, len(curve) // 160)]
    bt_dir = config.COMPUTED_DIR / "backtests"
    bt_dir.mkdir(parents=True, exist_ok=True)
    (bt_dir / f"{run_id}.json").write_text(json.dumps({
        "runId": run_id,
        "dates": [str(d.date()) for d in curve.index],
        "strategy": [round(float(v), 4) for v in curve["strategy"]],
        "baseline": [round(float(v), 4) for v in curve["baseline"]],
    }), encoding="utf-8")


def validate_proposal(store: OntologyStore, proposal: dict) -> dict:
    """제안 검증 디스패치: strategyRule 있으면 walk-forward, 없으면 STATIC."""
    from ontoquant.core.action_functions import apply_legs_to_weights

    if proposal.get("strategyRule"):
        return walk_forward_validate(store, proposal)

    close = krw_close_matrix(store)
    if close is None or len(close) < 252:
        raise ValueError("백테스트용 가격 히스토리 부족")
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    cols = list(close.columns)
    fees = np.array([[COST_BP.get(instruments[c]["currency"], 0.001) for c in cols]])
    current = {p["instrumentId"]: float(p.get("weight") or 0.0) for p in store.query("Position")}
    current = {k: v for k, v in current.items() if k in close.columns}
    proposed = apply_legs_to_weights(current, proposal.get("legs") or [])
    proposed = {k: v for k, v in proposed.items() if k in close.columns}

    strat = _sim_window(close, proposed, [], fees)
    base = _sim_window(close, current, [], fees)
    strat_value, base_value = strat.pop("value"), base.pop("value")

    def _var95(value: pd.Series) -> float | None:
        r = value.pct_change().dropna().tail(250)
        return float(-np.quantile(r, 0.05)) if len(r) >= 60 else None

    var_s, var_b = _var95(strat_value), _var95(base_value)
    # PSR: 전략-베이스라인 초과수익의 유의성 (정보 표기 — T가 짧아 차단 게이트로는 부적합)
    active = (strat_value.pct_change() - base_value.pct_change()).dropna()
    psr_active = None
    if len(active) > 30 and float(active.std()) > 0:
        from scipy import stats as sps
        psr_active = round(probabilistic_sharpe(
            float(active.mean() / active.std()), 0.0, len(active),
            float(sps.skew(active)), float(sps.kurtosis(active, fisher=False))), 4)

    metric_set = {
        "mode": "STATIC", "ruleHash": rule_hash({"legs": proposal.get("legs")}),
        "sharpe": strat["sharpe"], "sharpeBaseline": base["sharpe"],
        "mdd": strat["mdd"], "mddBaseline": base["mdd"],
        "turnover": strat["turnover"], "nTrades": strat["nTrades"],
        "psrActive": psr_active,
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
    _write_curve(run["runId"], strat_value, base_value)
    var_delta = (var_s - var_b) if (var_s is not None and var_b is not None) else None
    return {"run": run, "metricSet": metric_set,
            "expectedImpact": {"var95Delta": round(var_delta, 5) if var_delta is not None else None,
                               "betaDelta": None, "hhiDelta": None}}
