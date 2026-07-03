"""시그널 v2 일일 실행 + 감사 — 알파×지평 IC 성적표, 전략 시뮬, 보드.

지평 (5, 20, 60): 각 지평의 적격 알파(HORIZON_ALPHAS)만 결합.
검정: Newey-West t (겹침 h일 창 자기상관 보정).
전략: |Z_comb| ≥ PIT 문턱(직전 252일 풀링 75백분위) 상위 5종목 ±2%p 틸트, h일 보유.
모든 계산 PIT. 성적이 나쁘면 나쁜 대로 기록한다 (감사는 성적표).
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.store import OntologyStore
from ontoquant.insights.event_study import load_cars
from ontoquant.modeling.objective import active_model, count_trials, record_evaluation, rule_hash
from ontoquant.modeling.deflated_sharpe import deflated_sharpe
from ontoquant.signals import alphas, combine

HORIZONS = (5, 20, 60)
BOARD_HORIZON = 20
TILT = 0.02
MAX_TILTS_PER_DAY = 5
THRESH_PCTL = 0.75
HISTORY_PATH = config.COMPUTED_DIR / "signal_history_v2.parquet"
BOARD_PATH = config.COMPUTED_DIR / "signals_today.json"
ALPHA_LABELS = {
    "pead_sue": "실적 서프라이즈(SUE)", "pead_ear": "발표창 반응(EAR)",
    "insider": "내부자 매수", "news_fresh": "신선 뉴스", "news_stale": "재탕 뉴스 반전",
    "str_reversal": "단기 반전", "momentum": "12-1 모멘텀",
    "flag_buyback": "자사주 취득", "flag_issuance": "증자/CB",
}


def _close_matrix(store: OntologyStore) -> pd.DataFrame:
    cols = {}
    for inst in store.query("Instrument"):
        s = ret.load_close(inst["instrumentId"])
        if s is not None:
            cols[inst["instrumentId"]] = s
    return pd.DataFrame(cols).sort_index()


def _strategy_sim(store: OntologyStore, z_comb: pd.DataFrame, h: int,
                  as_of: str) -> dict:
    """Z_comb 추종 전략 vs 균등보유 (KRW 환산, 거래비용, PIT 문턱)."""
    from ontoquant.proposals import backtest as bt

    close_krw = bt.krw_close_matrix(store, lookback=len(z_comb.index))
    if close_krw is None:
        return {"status": "no-data"}
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    cols = [c for c in close_krw.columns
            if instruments.get(c, {}).get("tradable", True) is not False]
    close_krw = close_krw[cols]
    fees = np.array([[bt.COST_BP.get(instruments[c]["currency"], 0.001) for c in cols]])
    base_w = {c: 1.0 / len(cols) for c in cols}

    abs_z = z_comb[ [c for c in cols if c in z_comb.columns] ].abs()
    if not (abs_z.to_numpy() > 0).any():
        return {"status": "no-signals"}
    # PIT 문턱: 직전 252일 "일별 최대 |z|" 시계열의 75백분위 (t−1 까지만)
    daily_max = abs_z.max(axis=1)
    thresh = daily_max.rolling(252, min_periods=60).quantile(THRESH_PCTL).shift(1)

    overrides, n_tilts = [], 0
    for t in z_comb.index:
        th = thresh.get(t)
        if th is None or pd.isna(th):
            continue
        row = z_comb.loc[t].dropna()
        row = row[row.abs() >= th]
        if row.empty:
            continue
        pos = close_krw.index.searchsorted(t)
        # 체결은 t+1 종가 — z(t) 가 close(t) 로 만들어지므로 당일 체결은 누출
        # (검증 에이전트 LEAK 1: 특히 반전 알파가 종가 노이즈를 공짜로 수확)
        if pos + 1 >= len(close_krw.index) - 1:
            continue
        entry = close_krw.index[pos + 1]
        end = close_krw.index[min(pos + 1 + h, len(close_krw.index) - 1)]
        for iid, zval in row.abs().sort_values(ascending=False).head(MAX_TILTS_PER_DAY).items():
            if iid not in cols:
                continue
            step = TILT if z_comb.at[t, iid] > 0 else -TILT
            overrides.append((entry, end, iid, step))
            n_tilts += 1

    strat = bt._sim_window(close_krw, base_w, overrides, fees)
    base = bt._sim_window(close_krw, base_w, [], fees)
    strat_v, base_v = strat.pop("value"), base.pop("value")
    active = (strat_v.pct_change() - base_v.pct_change()).dropna()
    hist_n, hist_srs = count_trials(store, "signal-model")
    # DSR 은 초과수익(전략−베이스라인)에 적용 — 절대수익은 시장 베타가 지배해
    # 균등보유도 통과해 버리는 무의미한 검정이 된다
    dsr = deflated_sharpe(active, hist_srs)
    metrics = {
        "nTilts": n_tilts,
        "sharpe": strat["sharpe"], "sharpeBaseline": base["sharpe"],
        "mdd": strat["mdd"], "mddBaseline": base["mdd"],
        "totalReturn": round(float(strat_v.iloc[-1] / strat_v.iloc[0] - 1), 4),
        "totalReturnBaseline": round(float(base_v.iloc[-1] / base_v.iloc[0] - 1), 4),
        "activeReturnAnnual": round(float(active.mean() * 252), 4),
        "dsr": dsr["dsr"], "nTrialsHistory": hist_n,
    }
    return {"metrics": metrics, "strat_v": strat_v, "base_v": base_v}


def _conviction(z_val: float, contribs: dict[str, float],
                validated_alphas: set[str], hist_abs: np.ndarray,
                weights_row: pd.Series) -> dict:
    strength = float((hist_abs < abs(z_val)).mean()) if len(hist_abs) >= 20 else 0.0
    total = sum(abs(v) for v in contribs.values()) or 1.0
    evidence = sum(abs(v) for k, v in contribs.items() if k in validated_alphas) / total
    agree = sum(abs(v) for v in contribs.values() if np.sign(v) == np.sign(z_val)) / total
    return {"strength": round(strength, 3), "evidenceShare": round(evidence, 3),
            "agreement": round(agree, 3),
            "conviction": round(0.4 * strength + 0.3 * evidence + 0.3 * agree, 3)}


def run(store: OntologyStore, as_of: str | None = None) -> dict:
    as_of = as_of or str(date.today())
    close = _close_matrix(store)
    if close.empty:
        return {"status": "no-prices"}
    cars = load_cars(complete_only=False)
    raw = alphas.build_all(store, close, cars)
    z_all = {k: alphas.zscore_xs(v) for k, v in raw.items()}

    ic_table: list[dict] = []
    audits: dict[str, dict] = {}
    strategies: dict[str, dict] = {}
    z_combs: dict[int, pd.DataFrame] = {}
    weights_by_h: dict[int, pd.DataFrame] = {}
    validated_by_h: dict[int, set[str]] = {}
    model = active_model(store, "signal-model") or {"modelVersionId": "signal-model@2.0.0"}

    for h in HORIZONS:
        fwd = combine.forward_returns(close, h)
        eligible = {k: z_all[k] for k in alphas.HORIZON_ALPHAS[h] if k in z_all}
        ics = {k: combine.daily_ic(zk, fwd) for k, zk in eligible.items()}
        validated: set[str] = set()
        for k, ic in ics.items():
            mean_ic, nw_t, n = combine.newey_west_t(ic, h)
            ic_table.append({"alpha": k, "label": ALPHA_LABELS.get(k, k), "horizon": h,
                             "meanIC": round(mean_ic, 4), "nwT": round(nw_t, 2),
                             "nDays": n})
            if nw_t >= 2.0:
                validated.add(k)
        validated_by_h[h] = validated
        weights = combine.expanding_weights(ics, close.index, h)
        z_comb = combine.combine(eligible, weights)
        z_combs[h], weights_by_h[h] = z_comb, weights

        ic_c = combine.daily_ic(z_comb, fwd)
        mean_c, t_c, n_c = combine.newey_west_t(ic_c, h)
        sim = _strategy_sim(store, z_comb, h, as_of)
        strat_metrics = sim.get("metrics", {})
        audits[f"v2@{h}"] = {"meanIC": round(mean_c, 4), "icTstat": round(t_c, 2),
                             "nDays": n_c, **strat_metrics}
        metric_set = {
            "variant": f"v2@{h}", "ruleHash": rule_hash(
                {"v": 2, "h": h, "alphas": alphas.HORIZON_ALPHAS[h],
                 "lambda": combine.LAMBDA, "tilt": TILT, "pctl": THRESH_PCTL}),
            "meanIC": round(mean_c, 4), "icNwT": round(t_c, 2), "nDays": n_c,
            "validatedAlphas": sorted(validated), **strat_metrics,
        }
        gates = [
            (f"IC NW-t >= 2 (h={h})", t_c >= 2.0, f"t={t_c:.2f}"),
            ("strategy sharpe > baseline",
             (strat_metrics.get("sharpe") or 0) > (strat_metrics.get("sharpeBaseline") or 0),
             f"{strat_metrics.get('sharpe')} vs {strat_metrics.get('sharpeBaseline')}"),
            ("dsr >= 0.95", (strat_metrics.get("dsr") or 0) >= 0.95,
             f"dsr={strat_metrics.get('dsr')}"),
        ]
        run_obj = record_evaluation(store, model["modelVersionId"], "SIGNAL_AUDIT",
                                    metric_set,
                                    (str(close.index[0].date()), str(close.index[-1].date())),
                                    gates, run_key=f"signal-v2:{h}:{as_of}")
        if "strat_v" in sim:
            from ontoquant.proposals.backtest import _write_curve
            _write_curve(run_obj["runId"], sim["strat_v"], sim["base_v"])
            audits[f"v2@{h}"]["curveRunId"] = run_obj["runId"]
        strategies[f"v2@{h}"] = strat_metrics

    # 메타라벨링 shadow 평가 (h=20) — ML 은 방향이 아니라 신뢰도만. 게이트 통과 전 승수 미적용
    from ontoquant.signals import meta
    if meta.available():
        try:
            fwd20 = combine.forward_returns(close, BOARD_HORIZON)
            markets = {i["instrumentId"]: ("KR" if i.get("market") == "KRX" else "US")
                       for i in store.query("Instrument")}
            ds = meta.build_dataset(z_all, z_combs[BOARD_HORIZON], fwd20, None, markets)
            mres = meta.purged_walkforward_eval(ds, BOARD_HORIZON)
            if mres:
                record_evaluation(store, model["modelVersionId"], "META_LABEL",
                                  {**mres, "mode": "shadow", "horizon": BOARD_HORIZON},
                                  (str(close.index[0].date()), str(close.index[-1].date())),
                                  [("OOS 적중 개선 t >= 2", bool(mres.get("passes")),
                                    f"lift={mres.get('lift')} t={mres.get('liftT')}")],
                                  run_key=f"meta-label:{as_of}")
                audits["metaLabel"] = mres
        except Exception:  # noqa: BLE001 — shadow 평가 실패가 본 감사를 막지 않게
            pass

    # 히스토리 저장 (combined 만, long)
    hist_rows = []
    for h, zc in z_combs.items():
        stacked = zc.where(zc.abs() > 1e-9).stack()
        for (d, iid), v in stacked.items():
            hist_rows.append({"date": d, "instrumentId": iid,
                              "alpha": f"combined@{h}", "value": round(float(v), 5)})
    if hist_rows:
        pd.DataFrame(hist_rows).to_parquet(HISTORY_PATH, index=False)

    # 오늘의 보드 (기준 지평 20d)
    zc = z_combs[BOARD_HORIZON]
    weights = weights_by_h[BOARD_HORIZON]
    t_last = zc.index[-1]
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    held = {p["instrumentId"] for p in store.query("Position") if p.get("quantity")}
    board = []
    w_row = weights.iloc[-1]
    for iid in zc.columns:
        z_val = float(zc.at[t_last, iid]) if pd.notna(zc.at[t_last, iid]) else 0.0
        if abs(z_val) < 0.2:
            continue
        inst = instruments.get(iid)
        if not inst:
            continue
        contribs = {k: float(w_row.get(k, 0.0) * (z_all[k].at[t_last, iid] or 0.0))
                    for k in alphas.HORIZON_ALPHAS[BOARD_HORIZON]
                    if k in z_all and pd.notna(z_all[k].at[t_last, iid])}
        hist = zc[iid].abs().dropna()
        hist = hist[hist > 1e-9]
        conv = _conviction(z_val, contribs, validated_by_h[BOARD_HORIZON],
                           hist.iloc[:-1].to_numpy() if len(hist) else np.array([]), w_row)
        # "N주/년 만에 가장 강함" 표기
        from ontoquant.signals.audit import _strength_note
        from ontoquant.signals.engine import weeks_since_stronger
        wks = weeks_since_stronger(abs(z_val), hist.iloc[:-1] if len(hist) else hist)
        span_days = int((hist.index.max() - hist.index.min()).days * 252 / 365) if len(hist) > 1 else 0
        note = _strength_note(wks, span_days)
        top_alphas = sorted(contribs.items(), key=lambda kv: -abs(kv[1]))[:3]
        board.append({
            "instrumentId": iid,
            "name": inst.get("nameKo") or inst["name"], "ticker": inst["ticker"],
            "held": iid in held, "tradable": inst.get("tradable", True) is not False,
            "direction": "BUY" if z_val > 0 else "SELL",
            "signal": round(z_val, 3),
            "expected5d": round(float(z_combs[5].at[t_last, iid] or 0.0), 3)
                if iid in z_combs[5].columns and pd.notna(z_combs[5].at[t_last, iid]) else 0.0,
            "expected20d": round(z_val, 3),
            **conv,
            "strengthNote": note,
            "evidence": [{"alpha": k, "label": ALPHA_LABELS.get(k, k),
                          "contribution": round(v, 4),
                          "validated": k in validated_by_h[BOARD_HORIZON]}
                         for k, v in top_alphas if abs(v) > 1e-6],
        })
    board.sort(key=lambda b: -abs(b["signal"]) * (b["conviction"] or 0.1))

    BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOARD_PATH.write_text(json.dumps({
        "asOf": as_of, "modelVersion": model["modelVersionId"], "board": board,
        "audit": audits,
        "icTable": sorted(ic_table, key=lambda r: (r["horizon"], -abs(r["nwT"]))),
        "strategy": {**strategies.get("v2@20", {}),
                     "curveRunId": audits.get("v2@20", {}).get("curveRunId")},
    }, ensure_ascii=False), encoding="utf-8")

    best = max(audits.values(), key=lambda a: a.get("icTstat") or 0)
    return {"status": "ok", "boardSignals": len(board),
            "bestIcT": best.get("icTstat"), "bestIC": best.get("meanIC"),
            "validated20d": sorted(validated_by_h[BOARD_HORIZON]),
            "strategy20dSharpe": strategies.get("v2@20", {}).get("sharpe"),
            "baseline": strategies.get("v2@20", {}).get("sharpeBaseline")}
