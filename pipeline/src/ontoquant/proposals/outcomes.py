"""DECISION_OUTCOME — 승인된 제안의 실현 성과 추적 (결정→결과 되먹임 루프).

승인 시점의 preTradeWeights(반사실)와 legs 적용 비중을 같은 구간에 시뮬레이션해
activeReturn(제안 - 보유지속)을 20/60 거래일 지평으로 측정한다.
비차단 telemetry: 개별 결과는 노이즈 — rollingHitRate(최근 10건)가 모델 건강 지표.
"""
from __future__ import annotations

import pandas as pd

from ontoquant.core.store import OntologyStore
from ontoquant.modeling.objective import record_evaluation
from ontoquant.proposals import backtest as bt

HORIZONS_BD = [20, 60]
ROLLING_WINDOW = 10
HIT_RATE_WARN = 0.4


def _mdd(r: pd.Series) -> float:
    curve = (1 + r).cumprod()
    return float(-(curve / curve.cummax() - 1).min()) if len(r) else 0.0


def measure_outcome(store: OntologyStore, decision: dict, proposal: dict,
                    horizon_bd: int, close: pd.DataFrame) -> dict | None:
    from ontoquant.core.action_functions import apply_legs_to_weights

    snap = decision.get("recommendationSnapshot") or {}
    pre_weights = snap.get("preTradeWeights")
    if not pre_weights:
        return None
    decided = pd.Timestamp(str(decision["decidedAt"])[:10])
    start_pos = close.index.searchsorted(decided) + 1
    if start_pos + horizon_bd > len(close.index):
        return None  # 아직 지평 미도래
    window = close.iloc[start_pos: start_pos + horizon_bd + 1]
    pre = {k: float(v) for k, v in pre_weights.items() if k in window.columns}
    post = apply_legs_to_weights(pre, proposal.get("legs") or [])
    post = {k: v for k, v in post.items() if k in window.columns}

    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    import numpy as np
    fees = np.array([[bt.COST_BP.get(instruments[c]["currency"], 0.001)
                      for c in window.columns]])
    strat = bt._sim_window(window, post, [], fees)
    base = bt._sim_window(window, pre, [], fees)
    r_s = strat["value"].pct_change().dropna()
    r_b = base["value"].pct_change().dropna()
    ret_s = float((1 + r_s).prod() - 1)
    ret_b = float((1 + r_b).prod() - 1)
    return {
        "proposalId": proposal["proposalId"], "decisionId": decision["decisionId"],
        "horizonBd": horizon_bd,
        "ret": round(ret_s, 5), "retBaseline": round(ret_b, 5),
        "activeReturn": round(ret_s - ret_b, 5),
        "mdd": round(_mdd(r_s), 4), "mddBaseline": round(_mdd(r_b), 4),
        "backtestRunId": proposal.get("backtestRunId"),
    }


def _rolling_hit_rate(store: OntologyStore, horizon_bd: int) -> float | None:
    runs = [r for r in store.query("EvaluationRun", where={"runType": "DECISION_OUTCOME"})
            if (r.get("metricSet") or {}).get("horizonBd") == horizon_bd]
    runs.sort(key=lambda r: str(r.get("createdAt", "")))
    recent = runs[-ROLLING_WINDOW:]
    if not recent:
        return None
    hits = sum(1 for r in recent if (r["metricSet"].get("activeReturn") or 0) > 0)
    return round(hits / len(recent), 3)


def run(store: OntologyStore) -> dict:
    close = bt.krw_close_matrix(store)
    if close is None:
        return {"status": "no-data"}
    existing_keys = {r["runId"] for r in store.query("EvaluationRun",
                                                     where={"runType": "DECISION_OUTCOME"})}
    measured, pending = 0, 0
    for decision in store.query("Decision", where={"decision": "APPROVE"}):
        proposal = store.get("RebalanceProposal", decision.get("subjectId") or "")
        if not proposal:
            continue
        model_version = None
        if proposal.get("backtestRunId"):
            run_obj = store.get("EvaluationRun", proposal["backtestRunId"])
            model_version = (run_obj or {}).get("modelVersionId")
        for h in HORIZONS_BD:
            run_key = f"outcome:{decision['decisionId']}:{h}"
            # record_evaluation 이 run_key 로 결정적 runId 를 만들므로 사전 중복 검사
            import hashlib
            rid = f"eval_{hashlib.sha1(run_key.encode()).hexdigest()[:10]}"
            if rid in existing_keys:
                continue
            metric = measure_outcome(store, decision, proposal, h, close)
            if metric is None:
                pending += 1
                continue
            metric["rollingHitRate"] = _rolling_hit_rate(store, h)
            gates = [("activeReturn > 0 (telemetry)", metric["activeReturn"] > 0,
                      f"activeReturn={metric['activeReturn']}")]
            record_evaluation(store, model_version or "rebalance-strategy@1.0.0",
                              "DECISION_OUTCOME", metric,
                              (str(decision["decidedAt"])[:10], str(close.index[-1].date())),
                              gates, run_key=run_key)
            existing_keys.add(rid)
            measured += 1
    warn = None
    hr = _rolling_hit_rate(store, 20)
    if hr is not None and hr < HIT_RATE_WARN:
        warn = f"rollingHitRate20={hr} < {HIT_RATE_WARN} — 전략 재점검 필요"
    return {"status": "ok", "measured": measured, "pending": pending,
            "rollingHitRate20": hr, "warning": warn}
