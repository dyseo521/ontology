"""Modeling Objective 패턴 — ModelVersion / EvaluationRun / 게이트 / 승격.

- EvaluationRun 은 append-only 이력 (MetricSet 이 모델 버전 + 데이터 범위에 바인딩)
- 게이트 실패는 파이프라인을 멈추지 않고 stale 플래그로 전파
"""
from __future__ import annotations

import hashlib
from datetime import date

from ontoquant.core.audit import now_iso
from ontoquant.core.store import LinkRecord, OntologyStore


def production_model(store: OntologyStore, model_id: str) -> dict | None:
    rows = store.query("ModelVersion", where={"modelId": model_id, "stage": "PRODUCTION"})
    return rows[0] if rows else None


def active_model(store: OntologyStore, model_id: str) -> dict | None:
    """PRODUCTION 우선, 없으면 최신 STAGING."""
    prod = production_model(store, model_id)
    if prod:
        return prod
    rows = store.query("ModelVersion", where={"modelId": model_id, "stage": "STAGING"},
                       order_by="createdAt")
    return rows[0] if rows else None


def record_evaluation(
    store: OntologyStore,
    model_version_id: str,
    run_type: str,
    metric_set: dict,
    dataset_range: tuple[date | str, date | str],
    gates: list[tuple[str, bool, str]],
    run_key: str | None = None,
) -> dict:
    """EvaluationRun 생성 + modelEvaluations 링크. run_key 로 결정적 runId 생성."""
    key = run_key or f"{model_version_id}:{run_type}:{dataset_range[1]}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:10]
    run = {
        "runId": f"eval_{digest}",
        "modelVersionId": model_version_id,
        "runType": run_type,
        "metricSet": metric_set,
        "datasetRange": {"start": str(dataset_range[0]), "end": str(dataset_range[1])},
        "passedGates": all(passed for _, passed, _ in gates),
        "gateResults": [{"gate": g, "passed": p, "detail": d} for g, p, d in gates],
        "createdAt": now_iso(),
    }
    store.append_object("computed", "EvaluationRun", run)
    store.append_link("computed", LinkRecord(
        "modelEvaluations", "ModelVersion", model_version_id, "EvaluationRun", run["runId"]))
    return run


def passed_eval_count(store: OntologyStore, model_version_id: str) -> int:
    return len(store.query("EvaluationRun",
                           where={"modelVersionId": model_version_id, "passedGates": True}))


def rule_hash(rule: dict | None) -> str:
    """전략 규칙의 canonical hash — 시도 장부의 키 (지울 수 없는 다중 시도 카운팅)."""
    import hashlib
    import json
    canonical = json.dumps(rule or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode()).hexdigest()[:10]


def count_trials(store: OntologyStore, model_id: str = "rebalance-strategy",
                 ) -> tuple[int, list[float]]:
    """이력상 서로 다른 ruleHash 시도 수 + 각 시도의 per-period Sharpe 목록.

    EvaluationRun 이 append-only 이므로 시도를 지우거나 빼먹을 수 없다
    (Harvey-Liu-Zhu: 발견의 유의성은 시도 수만큼 할인).
    """
    seen: dict[str, float | None] = {}
    for r in store.query("EvaluationRun"):
        ms = r.get("metricSet") or {}
        rh = ms.get("ruleHash")
        if not rh or not str(r.get("modelVersionId", "")).startswith(model_id):
            continue
        sr = ms.get("oosSharpe") if "oosSharpe" in ms else ms.get("sharpe")
        if rh not in seen:
            seen[rh] = (sr / (252 ** 0.5)) if isinstance(sr, (int, float)) else None
    srs = [v for v in seen.values() if v is not None]
    return len(seen), srs


def passed_wf_count(store: OntologyStore, model_id: str) -> int:
    """게이트를 통과한 WALK_FORWARD run 수 (전략 승격 요건)."""
    return len([
        r for r in store.query("EvaluationRun", where={"runType": "WALK_FORWARD",
                                                       "passedGates": True})
        if str(r.get("modelVersionId", "")).startswith(model_id)
    ])
