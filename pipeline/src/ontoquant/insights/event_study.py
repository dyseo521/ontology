"""이벤트 스터디 — 시장모형 CAR 로 이벤트 타입의 가격 영향을 검증.

방법론:
  추정창 [-120, -21] 거래일: r_i = α + β·r_m + ε  (시장모형 OLS)
  이벤트창 [-1, +5]: AR_t = r_i,t − (α + β·r_m,t),  CAR = Σ AR_t
  타입별 집계: carMean, carT (1-sample t), hitRate(CAR<0 비율)

게이트: n ≥ 10 AND |t| ≥ 2.0 → 해당 타입 인사이트 VALIDATED 가능.
결과는 EvaluationRun(EVENT_STUDY) 으로 event-classifier 모델 버전에 바인딩.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ontoquant.compute import returns as ret
from ontoquant.compute.factor_model import load_factor_series
from ontoquant.core.store import OntologyStore
from ontoquant.modeling.objective import active_model, record_evaluation

EST_START, EST_END = -120, -21   # 추정창 (거래일 오프셋)
EVT_START, EVT_END = -1, 5       # 이벤트창
MIN_EST_OBS = 60
GATE_MIN_N = 10
GATE_MIN_T = 2.0
# 이벤트 스터디 제외 타입 (가격 가설이 없는 정기/절차성 공시)
SKIP_TYPES = {"PERIODIC_REPORT", "REG_FD", "DISCLOSURE_OTHER", "NEWS",
              "RATE_SHOCK", "VOL_SPIKE", "CREDIT_SHOCK", "FX_SHOCK", "OIL_SHOCK"}


def compute_car(r_i: pd.Series, r_m: pd.Series, event_date: pd.Timestamp) -> float | None:
    """단일 이벤트 CAR. 데이터 부족 시 None."""
    df = pd.concat([r_i.rename("y"), r_m.rename("m")], axis=1).dropna()
    if df.empty:
        return None
    idx = df.index.searchsorted(event_date)
    if idx >= len(df.index):
        return None
    est = df.iloc[max(0, idx + EST_START): idx + EST_END]
    evt = df.iloc[max(0, idx + EVT_START): idx + EVT_END + 1]
    if len(est) < MIN_EST_OBS or len(evt) < (EVT_END - EVT_START):
        return None
    x = est["m"].to_numpy()
    y = est["y"].to_numpy()
    var = x.var()
    if var <= 0:
        return None
    beta = float(np.cov(y, x, bias=True)[0, 1] / var)
    alpha = float(y.mean() - beta * x.mean())
    ar = evt["y"] - (alpha + beta * evt["m"])
    return float(ar.sum())


def judge(n: int, t_stat: float) -> bool:
    return n >= GATE_MIN_N and abs(t_stat) >= GATE_MIN_T


def run(store: OntologyStore, as_of: str | None = None) -> dict:
    as_of = as_of or str(date.today())
    factors = {f["factorId"]: f for f in store.query("Factor")}
    mkt = {
        "KR": load_factor_series(factors["KR:MKT"]) if "KR:MKT" in factors else None,
        "US": load_factor_series(factors["FF:MKT"]) if "FF:MKT" in factors else None,
    }
    returns_cache: dict[str, pd.Series | None] = {}

    def inst_returns(iid: str) -> pd.Series | None:
        if iid not in returns_cache:
            returns_cache[iid] = ret.load_returns(iid)
        return returns_cache[iid]

    # (eventType, market) → CAR 목록
    cars: dict[tuple[str, str], list[float]] = {}
    event_types = store.schema.interfaces["Event"].implementedBy
    for e in store.query("Event"):
        etype = e.get("eventType")
        market = e.get("market") or ("KR" if str(e["eventId"]).startswith("dart") else "US")
        if etype in SKIP_TYPES or not e.get("occurredAt"):
            continue
        otype = store.get_type_of(e["eventId"], event_types)
        if otype is None:
            continue
        r_m = mkt.get(market)
        if r_m is None:
            continue
        evt_date = pd.Timestamp(str(e["occurredAt"])[:10])
        for nb in store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out"):
            if float(nb.link.props.get("relevance", 0)) < 0.9:
                continue
            r_i = inst_returns(nb.pk)
            if r_i is None:
                continue
            car = compute_car(r_i, r_m, evt_date)
            if car is not None:
                cars.setdefault((etype, market), []).append(car)

    model = active_model(store, "event-classifier") or {"modelVersionId": "event-classifier@1.0.0"}
    summaries: list[dict] = []
    for (etype, market), values in sorted(cars.items()):
        arr = np.asarray(values)
        n = len(arr)
        mean = float(arr.mean())
        std = float(arr.std(ddof=1)) if n > 1 else 0.0
        t_stat = float(mean / (std / np.sqrt(n))) if std > 0 else 0.0
        metric_set = {
            "eventType": etype, "market": market, "n": n,
            "carMean": round(mean, 5), "carStd": round(std, 5),
            "carT": round(t_stat, 2),
            "hitRateNeg": round(float((arr < 0).mean()), 3),
            "window": f"[{EVT_START},+{EVT_END}]",
        }
        gates = [
            (f"n >= {GATE_MIN_N}", n >= GATE_MIN_N, f"n={n}"),
            (f"|t| >= {GATE_MIN_T}", abs(t_stat) >= GATE_MIN_T, f"t={t_stat:.2f}"),
        ]
        record_evaluation(store, model["modelVersionId"], "EVENT_STUDY", metric_set,
                          ("2021-01-01", as_of), gates,
                          run_key=f"event-study:{etype}:{market}:{as_of}")
        summaries.append(metric_set)
    return {"status": "ok", "types": len(summaries),
            "significant": [s for s in summaries if judge(s["n"], s["carT"])]}


def get_type_summary(store: OntologyStore, event_type: str, market: str | None) -> dict | None:
    """최신 EVENT_STUDY EvaluationRun 에서 타입 요약 조회 (event_rules 가 소비)."""
    runs = [
        r for r in store.query("EvaluationRun", where={"runType": "EVENT_STUDY"})
        if r["metricSet"].get("eventType") == event_type
        and (market is None or r["metricSet"].get("market") == market)
    ]
    if not runs:
        return None
    latest = max(runs, key=lambda r: str(r.get("createdAt", "")))
    ms = latest["metricSet"]
    return {"n": ms["n"], "carMean": ms["carMean"], "carT": ms["carT"],
            "hitRateNeg": ms.get("hitRateNeg"), "runId": latest["runId"]}
