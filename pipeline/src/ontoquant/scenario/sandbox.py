"""ScenarioSandbox — 온톨로지 fork/sandbox.

fork    : data/scenarios/{id}/ 오버레이 생성 (copy-on-write — 변경분만 기록)
apply   : 오버레이 store 위에서 ActionEngine 실행 (원본 무변경)
recompute + diff : 가격 고정, 가중치 변경분만 재계산 → baseline 대비 메트릭 diff
commit  : 오버레이 portfolio.json/객체를 본 writeback 에 병합
discard : 상태만 DISCARDED (오버레이는 감사용으로 보존)
"""
from __future__ import annotations

import json
import shutil

import numpy as np

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.actions import ActionEngine
from ontoquant.core.audit import new_id, now_iso
from ontoquant.core.store import OntologyStore


def _scenario_dir(scenario_id: str):
    return config.SCENARIOS_DIR / scenario_id


def overlay_store(scenario_id: str) -> OntologyStore:
    d = _scenario_dir(scenario_id)
    if not d.is_dir():
        raise FileNotFoundError(f"시나리오 없음: {scenario_id}")
    return OntologyStore(overlay_dir=d).build()


def fork(name: str, actor: str = "user") -> str:
    store = OntologyStore().build()
    scenario_id = new_id("scn")
    d = _scenario_dir(scenario_id)
    d.mkdir(parents=True, exist_ok=True)
    as_of = None
    metrics = store.query("RiskMetric", limit=1)
    if metrics:
        as_of = metrics[0]["asOfDate"]
    store.append_object("writeback", "Scenario", {
        "scenarioId": scenario_id, "name": name,
        "baseDate": as_of or now_iso()[:10],
        "status": "OPEN", "appliedActionIds": [],
        "createdAt": now_iso(), "createdBy": actor,
    })
    return scenario_id


def apply_action(scenario_id: str, action_api_name: str, params: dict,
                 actor: str = "user") -> dict:
    store = overlay_store(scenario_id)
    engine = ActionEngine(store, actor=actor)
    result = engine.submit(action_api_name, params)
    if result.get("ok"):
        main = OntologyStore().build()
        scn = main.get("Scenario", scenario_id) or {}
        applied = list(scn.get("appliedActionIds") or []) + [result["actionLogId"]]
        main.append_object("writeback", "Scenario", {**scn, "appliedActionIds": applied})
    return result


def _portfolio_metrics(store: OntologyStore) -> tuple[dict, dict[str, float]]:
    """오버레이/베이스 공통 — 현재 수량 기준 KRW 히스토리로 핵심 메트릭 계산."""
    history = ret.portfolio_history(store)
    if history is None or history.empty:
        return {}, {}
    port_ret = ret.portfolio_returns(history)
    total = float(history["TOTAL"].iloc[-1])
    weights: dict[str, float] = {}
    for pos in store.query("Position"):
        pid = pos["positionId"]
        if pid in history.columns and total > 0:
            weights[pos["instrumentId"]] = float(history[pid].iloc[-1]) / total
    tail = port_ret.tail(250)
    curve = history["TOTAL"].tail(252)
    metrics = {
        "VAR_95_1D": float(-np.quantile(tail, 0.05)) if len(tail) >= 60 else None,
        "VOL_30D": float(port_ret.tail(30).std() * np.sqrt(252)) if len(port_ret) >= 30 else None,
        "MDD_1Y": float(-(curve / curve.cummax() - 1.0).min()),
        "HHI": float(sum(w * w for w in weights.values())),
        "TOTAL_VALUE": total,
    }
    return metrics, weights


def compare(scenario_id: str) -> dict:
    base_store = OntologyStore().build()
    scn_store = overlay_store(scenario_id)
    base_m, base_w = _portfolio_metrics(base_store)
    scn_m, scn_w = _portfolio_metrics(scn_store)

    metrics_diff = {}
    for k in ("VAR_95_1D", "VOL_30D", "MDD_1Y", "HHI"):
        b, s = base_m.get(k), scn_m.get(k)
        metrics_diff[k] = {
            "base": round(b, 6) if b is not None else None,
            "scenario": round(s, 6) if s is not None else None,
            "delta": round(s - b, 6) if (b is not None and s is not None) else None,
        }
    base_pos = {p["instrumentId"]: p for p in base_store.query("Position")}
    scn_pos = {p["instrumentId"]: p for p in scn_store.query("Position")}
    changed = []
    for iid in sorted(set(base_pos) | set(scn_pos)):
        bq = float(base_pos.get(iid, {}).get("quantity") or 0)
        sq = float(scn_pos.get(iid, {}).get("quantity") or 0)
        if abs(bq - sq) > 1e-9:
            changed.append({"positionId": f"main:{iid}", "field": "quantity",
                            "base": bq, "scenario": sq})
    diff = {
        "metrics": metrics_diff,
        "positions": {
            "added": sorted(set(scn_pos) - set(base_pos)),
            "removed": sorted(set(base_pos) - set(scn_pos)),
            "changed": changed,
        },
        "exposures": {
            iid: {"base": round(base_w.get(iid, 0), 4), "scenario": round(scn_w.get(iid, 0), 4),
                  "delta": round(scn_w.get(iid, 0) - base_w.get(iid, 0), 4)}
            for iid in sorted(set(base_w) | set(scn_w))
            if abs(scn_w.get(iid, 0) - base_w.get(iid, 0)) > 0.001
        },
    }
    (_scenario_dir(scenario_id) / "diff.json").write_text(
        json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    scn = base_store.get("Scenario", scenario_id) or {}
    base_store.append_object("writeback", "Scenario", {**scn, "diffSummary": diff})
    return diff


def commit(scenario_id: str, actor: str = "user") -> dict:
    d = _scenario_dir(scenario_id)
    main = OntologyStore().build()
    scn = main.get("Scenario", scenario_id)
    if not scn or scn.get("status") != "OPEN":
        raise ValueError(f"OPEN 상태의 시나리오만 커밋 가능: {scenario_id}")
    merged = []
    overlay_pf = d / "portfolio.json"
    if overlay_pf.exists():
        main.write_portfolio_doc(json.loads(overlay_pf.read_text(encoding="utf-8")))
        merged.append("portfolio.json")
    for sub in ("objects", "links"):
        src_dir = d / sub
        if not src_dir.is_dir():
            continue
        for f in src_dir.glob("*.jsonl"):
            dest = config.WRITEBACK_DIR / sub / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "a", encoding="utf-8") as out, open(f, encoding="utf-8") as src:
                out.write(src.read())
            merged.append(f"{sub}/{f.name}")
    main = OntologyStore().build()
    scn = main.get("Scenario", scenario_id) or scn
    main.append_object("writeback", "Scenario", {**scn, "status": "COMMITTED"})
    return {"ok": True, "merged": merged}


def discard(scenario_id: str) -> dict:
    main = OntologyStore().build()
    scn = main.get("Scenario", scenario_id)
    if not scn:
        raise FileNotFoundError(scenario_id)
    main.append_object("writeback", "Scenario", {**scn, "status": "DISCARDED"})
    return {"ok": True}


def purge(scenario_id: str) -> None:
    """감사 보존이 불필요한 경우에만 물리 삭제."""
    shutil.rmtree(_scenario_dir(scenario_id), ignore_errors=True)
