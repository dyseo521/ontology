"""시그널 감사 — 과거 시그널을 PIT 로 재구성해 "실제로 유용했는가"를 채점.

1) 히스토리: 최근 N년 영업일마다 signal_on_date 를 그 날짜 기준 PIT 로 계산
   (미래 정보 없음 — engine 의 m/severity/검증 판정 전부 t 시점).
2) 감사 지표:
   - IC (information coefficient): 일별 spearman(시그널, 다음날 진입 5일 수익률)
   - 적중률: |시그널| 상위 25% 발화의 방향 적중 비율
   - 연도별 분해 (국면 안정성)
3) 소스 유효성: 이벤트 단위로 "예측 방향 × 실제 5일 시장조정 수익률" 정렬 평균을
   유형·소스별로 검정 — 예측력 없는 소스를 식별한다 (모든 기사가 유용하지 않다).

결과는 EvaluationRun(SIGNAL_AUDIT / SOURCE_VALIDITY) 으로 signal-model 에 바인딩.
감사는 게이트가 아니라 성적표다 — 나쁘면 나쁜 대로 표시한다.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sps

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.store import OntologyStore
from ontoquant.insights.event_study import load_cars
from ontoquant.modeling.objective import active_model, record_evaluation
from ontoquant.signals import engine

HISTORY_YEARS = 4          # 가용 원장(2021-07~) 전체 — "몇 년 만의 신호" 표기 근거
FWD_BD = 5
STRAT_HOLD_BD = 5
STRAT_STEP = 0.02
STRAT_PCTL = 0.75          # 강신호 문턱: 직전 252일 |신호| 백분위 (PIT)
HISTORY_PATHS = {
    "all": config.COMPUTED_DIR / "signal_history.parquet",
    "validatedOnly": config.COMPUTED_DIR / "signal_history_validated.parquet",
}
BOARD_PATH = config.COMPUTED_DIR / "signals_today.json"
TOP_Q = 0.75


def _close_matrix(store: OntologyStore) -> pd.DataFrame:
    cols = {}
    for inst in store.query("Instrument"):
        s = ret.load_close(inst["instrumentId"])
        if s is not None:
            cols[inst["instrumentId"]] = s
    return pd.DataFrame(cols).sort_index()


def build_history(store: OntologyStore, close: pd.DataFrame,
                  years: int = HISTORY_YEARS, variant: str = "all") -> pd.DataFrame:
    """일별 시그널 히스토리 (long: date, instrumentId, signal). 날짜 증분 캐시.

    variant: "all"(전체 기여) / "validatedOnly"(PIT 검증 유형만 — v1.1 후보)
    """
    path = HISTORY_PATHS[variant]
    bdays = close.index
    start = bdays[-1] - pd.DateOffset(years=years)
    days = bdays[bdays >= start]

    existing = pd.read_parquet(path) if path.exists() else None
    done_dates = set(pd.to_datetime(existing["date"]).unique()) if existing is not None else set()
    todo = [d for d in days if d not in done_dates]
    if todo:
        events = engine.collect_events(store)
        pit = engine.PitStats(load_cars())
        rows = []
        for t in todo:
            sig = engine.signal_on_date(events, pit, t, bdays,
                                        validated_only=(variant == "validatedOnly"))
            for iid, v in sig.items():
                rows.append({"date": t, "instrumentId": iid,
                             "signal": round(v["signal"], 7)})
        add = pd.DataFrame(rows, columns=["date", "instrumentId", "signal"])
        merged = pd.concat([existing, add], ignore_index=True) if existing is not None else add
        merged["date"] = pd.to_datetime(merged["date"]).astype("datetime64[ns]")
        merged = merged.drop_duplicates(["date", "instrumentId"], keep="last").sort_values("date")
        path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path, index=False)
        return merged
    return existing if existing is not None else pd.DataFrame(columns=["date", "instrumentId", "signal"])


def _forward_returns(close: pd.DataFrame, horizon: int = FWD_BD) -> pd.DataFrame:
    """t 시그널 → t+1 진입, t+1+h 청산 수익률 (체결 지연 1일 반영)."""
    entry = close.shift(-1)
    exit_ = close.shift(-1 - horizon)
    return exit_ / entry - 1


def audit_signals(store: OntologyStore, history: pd.DataFrame,
                  close: pd.DataFrame, as_of: str, variant: str = "all") -> dict:
    if history.empty:
        return {"status": "no-signals"}
    fwd = _forward_returns(close)
    hist = history.copy()
    hist["fwd"] = [
        fwd.at[d, i] if (d in fwd.index and i in fwd.columns) else np.nan
        for d, i in zip(hist["date"], hist["instrumentId"])
    ]
    hist = hist.dropna(subset=["fwd"])
    if len(hist) < 50:
        return {"status": "insufficient", "n": int(len(hist))}

    # 일별 IC (해당일 발화 종목 3개 이상일 때)
    ics = []
    for d, g in hist.groupby("date"):
        if len(g) >= 3 and g["signal"].nunique() > 1:
            ic = sps.spearmanr(g["signal"], g["fwd"]).statistic
            if not np.isnan(ic):
                ics.append(ic)
    ic_arr = np.array(ics)
    mean_ic = float(ic_arr.mean()) if len(ic_arr) else 0.0
    ic_t = float(mean_ic / (ic_arr.std(ddof=1) / np.sqrt(len(ic_arr)))) \
        if len(ic_arr) > 2 and ic_arr.std(ddof=1) > 0 else 0.0

    # 강신호 적중률 (|signal| 상위 25%)
    thresh = hist["signal"].abs().quantile(TOP_Q)
    strong = hist[hist["signal"].abs() >= thresh]
    hit_rate = float((np.sign(strong["signal"]) == np.sign(strong["fwd"])).mean()) if len(strong) else None
    strong_mean_aligned = float((np.sign(strong["signal"]) * strong["fwd"]).mean()) if len(strong) else None

    by_year = {}
    for y, g in hist.groupby(hist["date"].dt.year):
        sg = g[g["signal"].abs() >= thresh]
        by_year[str(y)] = {
            "n": int(len(g)),
            "hitRate": round(float((np.sign(sg["signal"]) == np.sign(sg["fwd"])).mean()), 3) if len(sg) else None,
            "meanAligned": round(float((np.sign(sg["signal"]) * sg["fwd"]).mean()), 5) if len(sg) else None,
        }

    metric_set = {
        "variant": variant,
        "nObs": int(len(hist)), "nDays": int(len(ic_arr)),
        "meanIC": round(mean_ic, 4), "icTstat": round(ic_t, 2),
        "hitRateStrong": round(hit_rate, 3) if hit_rate is not None else None,
        "meanAlignedStrong": round(strong_mean_aligned, 5) if strong_mean_aligned is not None else None,
        "byYear": by_year, "horizonBd": FWD_BD,
    }
    gates = [
        ("meanIC > 0", mean_ic > 0, f"IC={metric_set['meanIC']}"),
        ("icTstat >= 2 (유의)", ic_t >= 2.0, f"t={metric_set['icTstat']}"),
    ]
    model = active_model(store, "signal-model") or {"modelVersionId": "signal-model@1.0.0"}
    record_evaluation(store, model["modelVersionId"], "SIGNAL_AUDIT", metric_set,
                      (str(hist["date"].min().date()), str(hist["date"].max().date())),
                      gates, run_key=f"signal-audit:{variant}:{as_of}")
    return metric_set


def source_validity(store: OntologyStore, close: pd.DataFrame, as_of: str) -> dict:
    """유형·소스별 예측력: 예측 방향 × 실제 5일 시장조정 수익률의 정렬 평균."""
    from ontoquant.compute.factor_model import load_factor_series

    factors = {f["factorId"]: f for f in store.query("Factor")}
    mkt = {"KR": load_factor_series(factors.get("KR:MKT", {})) if "KR:MKT" in factors else None,
           "US": load_factor_series(factors.get("FF:MKT", {})) if "FF:MKT" in factors else None}
    fwd = _forward_returns(close)
    pit = engine.PitStats(load_cars())
    events = engine.collect_events(store)
    bdays = close.index

    samples: dict[str, list[float]] = {}
    for e in events:
        if e.date not in fwd.index:
            continue
        if e.is_news:
            if e.sentiment is None or abs(e.sentiment) < 0.25:
                continue
            direction = np.sign(e.sentiment)
            key = f"NEWS:{e.market}"
        else:
            stats = pit.stats(e.eventType, e.market, e.date)
            if stats is None or stats["carMean"] == 0:
                continue
            direction = np.sign(stats["carMean"])
            key = f"{e.eventType}:{e.market}"
        r_m = mkt.get(e.market)
        pos = bdays.searchsorted(e.date, side="right")
        if pos + FWD_BD >= len(bdays):
            continue
        mkt_fwd = 0.0
        if r_m is not None:
            seg = r_m.reindex(bdays[pos: pos + FWD_BD]).dropna()
            mkt_fwd = float((1 + seg).prod() - 1) if len(seg) else 0.0
        iid = e.instruments[0][0]
        if iid not in fwd.columns:
            continue
        raw = fwd.at[e.date, iid]
        if pd.isna(raw):
            continue
        samples.setdefault(key, []).append(float(direction) * (float(raw) - mkt_fwd))

    groups = []
    for key, vals in samples.items():
        arr = np.array(vals)
        n = len(arr)
        if n < 10:
            continue
        mean = float(arr.mean())
        t = float(mean / (arr.std(ddof=1) / np.sqrt(n))) if arr.std(ddof=1) > 0 else 0.0
        groups.append({"source": key, "n": n, "meanAligned": round(mean, 5),
                       "t": round(t, 2), "useful": bool(t >= 2.0)})
    groups.sort(key=lambda g: -g["t"])
    useful = [g["source"] for g in groups if g["useful"]]
    useless = [g["source"] for g in groups if g["t"] < 0.5]
    metric_set = {"groups": groups, "usefulSources": useful, "weakSources": useless,
                  "horizonBd": FWD_BD}
    model = active_model(store, "signal-model") or {"modelVersionId": "signal-model@1.0.0"}
    record_evaluation(store, model["modelVersionId"], "SOURCE_VALIDITY", metric_set,
                      ("2021-07-01", as_of),
                      [("useful sources >= 1", len(useful) >= 1, f"{len(useful)}개 유형 유효")],
                      run_key=f"source-validity:{as_of}")
    return metric_set


def strategy_backtest(store: OntologyStore, history: pd.DataFrame, as_of: str) -> dict:
    """'이 신호를 따라 매매했다면' — 강신호 ±2%p 틸트(5일 보유) vs 균등보유.

    결과론 배제 장치:
    - 신호 자체가 PIT (engine)
    - 강신호 문턱 = 각 시점의 '직전 252일' |신호| 백분위 (미래 분포를 모름)
    - 규칙(±2%p, 5일, 75백분위)은 사전 고정 — ruleHash 로 시도 장부에 기록
    """
    from ontoquant.proposals import backtest as bt
    from ontoquant.modeling.objective import rule_hash

    close = bt.krw_close_matrix(store, lookback=1010)  # ~4년
    if close is None or history.empty:
        return {"status": "no-data"}
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    cols = [c for c in close.columns
            if instruments.get(c, {}).get("tradable", True) is not False]
    close = close[cols]
    fees = np.array([[bt.COST_BP.get(instruments[c]["currency"], 0.001) for c in cols]])
    base_w = {c: 1.0 / len(cols) for c in cols}

    hist = history[history["instrumentId"].isin(cols)].copy()
    hist["absSig"] = hist["signal"].abs()
    # PIT 문턱: 날짜별 직전 252일 |신호| 분포의 75백분위
    daily_max = hist.groupby("date")["absSig"].max().sort_index()
    thresholds = daily_max.rolling(252, min_periods=60).quantile(STRAT_PCTL).shift(1)

    overrides = []
    n_tilts = 0
    for _, row in hist.iterrows():
        th = thresholds.get(row["date"])
        if th is None or pd.isna(th) or row["absSig"] < th:
            continue
        pos = close.index.searchsorted(row["date"])
        if pos >= len(close.index) - 1:
            continue
        end = close.index[min(pos + STRAT_HOLD_BD, len(close.index) - 1)]
        step = STRAT_STEP if row["signal"] > 0 else -STRAT_STEP
        overrides.append((row["date"], end, row["instrumentId"], step))
        n_tilts += 1

    strat = bt._sim_window(close, base_w, overrides, fees)
    base = bt._sim_window(close, base_w, [], fees)
    strat_v, base_v = strat.pop("value"), base.pop("value")
    active = (strat_v.pct_change() - base_v.pct_change()).dropna()
    metric_set = {
        "mode": "SIGNAL_FOLLOW", "ruleHash": rule_hash(
            {"step": STRAT_STEP, "holdBd": STRAT_HOLD_BD, "pctl": STRAT_PCTL}),
        "nTilts": n_tilts,
        "sharpe": strat["sharpe"], "sharpeBaseline": base["sharpe"],
        "mdd": strat["mdd"], "mddBaseline": base["mdd"],
        "totalReturn": round(float(strat_v.iloc[-1] / strat_v.iloc[0] - 1), 4),
        "totalReturnBaseline": round(float(base_v.iloc[-1] / base_v.iloc[0] - 1), 4),
        "activeReturnAnnual": round(float(active.mean() * 252), 4),
    }
    gates = [
        ("sharpe > baseline", strat["sharpe"] > base["sharpe"],
         f"{strat['sharpe']} vs {base['sharpe']}"),
        ("totalReturn > baseline", metric_set["totalReturn"] > metric_set["totalReturnBaseline"],
         f"{metric_set['totalReturn']} vs {metric_set['totalReturnBaseline']}"),
    ]
    model = active_model(store, "signal-model") or {"modelVersionId": "signal-model@1.0.0"}
    run_obj = record_evaluation(store, model["modelVersionId"], "SIGNAL_AUDIT", metric_set,
                                (str(close.index[0].date()), str(close.index[-1].date())),
                                gates, run_key=f"signal-strategy:{as_of}")
    bt._write_curve(run_obj["runId"], strat_v, base_v)
    metric_set["curveRunId"] = run_obj["runId"]
    return metric_set


def _strength_note(wks: int | None, history_days: int) -> str | None:
    """직관 표기: 주 → 년 스케일 자동 전환."""
    if wks is None:
        if history_days < 60:
            return None
        yrs = history_days / 252
        return f"관측 {yrs:.0f}년 내 가장 강한 신호" if yrs >= 1.5 \
            else f"관측 {max(1, int(history_days / 5))}주 내 가장 강한 신호"
    if wks >= 104:
        return f"약 {wks / 52:.0f}년 만에 가장 강한 신호"
    if wks >= 8:
        return f"{wks}주 만에 가장 강한 신호"
    return None


def todays_board(store: OntologyStore, history: pd.DataFrame, close: pd.DataFrame) -> list[dict]:
    """오늘의 시그널 보드 — 확신도/직관 표기 포함 (export·인사이트 소비)."""
    if close.empty:
        return []
    t = close.index[-1]
    events = engine.collect_events(store)
    pit = engine.PitStats(load_cars())
    today = engine.signal_on_date(events, pit, t, close.index)
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    held = {p["instrumentId"] for p in store.query("Position") if p.get("quantity")}
    board = []
    for iid, v in today.items():
        inst = instruments.get(iid)
        if not inst:
            continue
        h = history[history["instrumentId"] == iid].set_index("date")["signal"].abs()
        conv = engine.conviction_of(v["signal"], v["contribs"], h.to_numpy())
        wks = engine.weeks_since_stronger(abs(v["signal"]), h.iloc[:-1] if len(h) else h)
        span_days = int((h.index.max() - h.index.min()).days * 252 / 365) if len(h) > 1 else 0
        note = _strength_note(wks, span_days)
        top_contribs = sorted(v["contribs"], key=lambda c: -abs(c["contribution"]))[:3]
        board.append({
            "instrumentId": iid,
            "name": inst.get("nameKo") or inst["name"], "ticker": inst["ticker"],
            "held": iid in held, "tradable": inst.get("tradable", True) is not False,
            "direction": "BUY" if v["signal"] > 0 else "SELL",
            "signal": round(v["signal"], 5),
            "expected5d": round(v["signal"] * 100, 2),
            **conv,
            "strengthNote": note,
            "evidence": [{"eventId": c["eventId"], "eventType": c["eventType"],
                          "validated": c["validated"]} for c in top_contribs],
        })
    board.sort(key=lambda b: -abs(b["signal"]) * b["conviction"] if b["conviction"] else 0)
    return board


def run(store: OntologyStore, as_of: str | None = None) -> dict:
    as_of = as_of or str(date.today())
    close = _close_matrix(store)
    if close.empty:
        return {"status": "no-prices"}
    # 두 변형을 같은 잣대로 감사 — Modeling Objective 방식의 후보 비교
    history_all = build_history(store, close, variant="all")
    history_val = build_history(store, close, variant="validatedOnly")
    audit_all = audit_signals(store, history_all, close, as_of, variant="all")
    audit_val = audit_signals(store, history_val, close, as_of, variant="validatedOnly")
    strategy = strategy_backtest(store, history_all, as_of)
    validity = source_validity(store, close, as_of)
    board = todays_board(store, history_all, close)
    BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOARD_PATH.write_text(json.dumps({
        "asOf": as_of, "board": board,
        "audit": {"all": audit_all if audit_all.get("meanIC") is not None else None,
                  "validatedOnly": audit_val if audit_val.get("meanIC") is not None else None},
        "strategy": strategy if strategy.get("sharpe") is not None else None,
        "sourceValidity": {"useful": validity.get("usefulSources", []),
                           "weak": validity.get("weakSources", [])},
    }, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "historyRows": int(len(history_all)), "boardSignals": len(board),
            "icAll": audit_all.get("meanIC"), "icValidatedOnly": audit_val.get("meanIC"),
            "strategySharpe": strategy.get("sharpe"),
            "strategyBaseline": strategy.get("sharpeBaseline"),
            "nTilts": strategy.get("nTilts"),
            "usefulSources": len(validity.get("usefulSources", []))}
