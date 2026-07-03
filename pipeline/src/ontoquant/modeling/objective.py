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
