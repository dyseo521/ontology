"""이벤트 전파 — 타입 제약 그래프 순회로 포트폴리오 영향도 산출.

경로 2종:
  DIRECT : Event →(affects, relevance)→ Instrument ←(of)← Position(weight)
  FACTOR : Event →(drives, relevance)→ Factor ←(exposure, |beta|)← Instrument ←← Position(weight)

경로 점수 = relevance × |beta| × weight  (DIRECT 는 beta=1)
포트폴리오 영향도 = severity × Σ 경로 점수

산출: data/computed/impacts.json {eventId: ImpactReport}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ontoquant import config
from ontoquant.core.store import OntologyStore

RECENT_DAYS = 90
MIN_BETA = 0.05
MAX_PATHS = 12


def propagate(store: OntologyStore, event: dict, event_type: str,
              weights: dict[str, tuple[str, float, str]]) -> dict | None:
    """weights: instrumentId → (positionId, weight, label)."""
    paths: list[dict] = []

    for nb in store.neighbors(event_type, event["eventId"], "eventAffectsInstrument", "out"):
        rel = float(nb.link.props.get("relevance", 0.5))
        pos = weights.get(nb.pk)
        if pos is None:
            continue
        pid, w, label = pos
        paths.append({
            "type": "DIRECT", "score": round(rel * w, 6),
            "instrumentId": nb.pk, "positionId": pid, "label": label,
            "nodes": [f"{event_type}:{event['eventId']}", f"Instrument:{nb.pk}",
                      f"Position:{pid}", "Portfolio:main"],
            "detail": f"직접 연관 {rel:.2f} × 비중 {w:.1%}",
        })

    for fnb in store.neighbors(event_type, event["eventId"], "eventDrivesFactor", "out"):
        rel = float(fnb.link.props.get("relevance", 0.5))
        for enb in store.neighbors("Factor", fnb.pk, "exposureFactor", "in"):
            exp = enb.obj
            beta = float(exp.get("beta", 0.0))
            if abs(beta) < MIN_BETA:
                continue
            pos = weights.get(exp["instrumentId"])
            if pos is None:
                continue
            pid, w, label = pos
            paths.append({
                "type": "FACTOR", "score": round(rel * abs(beta) * w, 6),
                "instrumentId": exp["instrumentId"], "positionId": pid, "label": label,
                "factorId": fnb.pk, "beta": beta,
                "nodes": [f"{event_type}:{event['eventId']}", f"Factor:{fnb.pk}",
                          f"Instrument:{exp['instrumentId']}", f"Position:{pid}", "Portfolio:main"],
                "detail": f"팩터 {fnb.obj.get('nameKo') or fnb.pk} β{beta:+.2f} × 비중 {w:.1%}",
            })

    if not paths:
        return None
    paths.sort(key=lambda p: -p["score"])
    by_pos: dict[str, dict] = {}
    for p in paths:
        agg = by_pos.setdefault(p["positionId"], {
            "positionId": p["positionId"], "instrumentId": p["instrumentId"],
            "label": p["label"], "score": 0.0,
        })
        agg["score"] = round(agg["score"] + p["score"], 6)
    structural = round(sum(p["score"] for p in paths), 6)
    severity = float(event.get("severity") or 0.25)
    return {
        "eventId": event["eventId"],
        "structuralScore": structural,
        "portfolioImpactScore": round(severity * structural, 6),
        "severity": severity,
        "topPositions": sorted(by_pos.values(), key=lambda x: -x["score"])[:6],
        "paths": paths[:MAX_PATHS],
    }


def run(store: OntologyStore) -> dict:
    weights: dict[str, tuple[str, float, str]] = {}
    for pos in store.query("Position"):
        inst = store.get("Instrument", pos["instrumentId"]) or {}
        weights[pos["instrumentId"]] = (
            pos["positionId"], float(pos.get("weight") or 0.0),
            inst.get("nameKo") or inst.get("name") or pos["instrumentId"],
        )
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
    event_types = store.schema.interfaces["Event"].implementedBy
    impacts: dict[str, dict] = {}
    for e in store.query("Event"):
        if str(e.get("occurredAt") or "") < cutoff:
            continue
        etype = store.get_type_of(e["eventId"], event_types)
        if not etype:
            continue
        report = propagate(store, e, etype, weights)
        if report:
            impacts[e["eventId"]] = report
    config.COMPUTED_DIR.mkdir(parents=True, exist_ok=True)
    (config.COMPUTED_DIR / "impacts.json").write_text(
        json.dumps(impacts, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "events": len(impacts)}
