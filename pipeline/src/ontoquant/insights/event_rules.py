"""EVENT_IMPACT 인사이트 — 전파 영향도 상위 이벤트를 인사이트로 승격.

검증: 이벤트 스터디(insights/event_study.py, Phase 3)의 타입별 CAR 요약이 있으면
게이트(n>=10, |t|>=2)를 적용해 VALIDATED/UNVALIDATED/REJECTED 를 판정한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ontoquant import config
from ontoquant.core.store import LinkRecord, OntologyStore

IMPACT_MIN = 0.005     # 포트폴리오 영향도 최소값
RECENT_DAYS = 7
MAX_INSIGHTS = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _car_summary(store: OntologyStore, event_type: str, market: str | None) -> dict | None:
    try:
        from ontoquant.insights.event_study import get_type_summary
    except ImportError:
        return None
    return get_type_summary(store, event_type, market)


def build(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    impacts_path = config.COMPUTED_DIR / "impacts.json"
    if not impacts_path.exists():
        return [], []
    impacts: dict[str, dict] = json.loads(impacts_path.read_text(encoding="utf-8"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
    event_types = store.schema.interfaces["Event"].implementedBy

    candidates: list[tuple[dict, dict, str]] = []
    for eid, report in impacts.items():
        if report["portfolioImpactScore"] < IMPACT_MIN:
            continue
        event = store.get("Event", eid)
        if event is None or str(event.get("occurredAt") or "") < cutoff:
            continue
        etype_obj = store.get_type_of(eid, event_types)
        if etype_obj:
            candidates.append((event, report, etype_obj))
    candidates.sort(key=lambda c: -c[1]["portfolioImpactScore"])

    insights: list[dict] = []
    links: list[LinkRecord] = []
    for event, report, etype_obj in candidates[:MAX_INSIGHTS]:
        eid = event["eventId"]
        top = report["topPositions"][:3]
        targets = ", ".join(f"{t['label']}({t['score'] * 100:.2f})" for t in top)
        car = _car_summary(store, event["eventType"], event.get("market"))
        if car and car["n"] >= 10 and abs(car["carT"]) >= 2.0:
            status = "VALIDATED"
            summary = f"CAR {car['carMean'] * 100:+.1f}% t={car['carT']:.1f} n={car['n']}"
            eval_run_id = car.get("runId")
        elif car and car["n"] >= 10:
            status = "UNVALIDATED"
            summary = f"유의성 미달 (CAR {car['carMean'] * 100:+.1f}% t={car['carT']:.1f} n={car['n']})"
            eval_run_id = car.get("runId")
        else:
            status = "UNVALIDATED"
            summary = f"표본 부족 (n={car['n'] if car else 0} < 10)"
            eval_run_id = car.get("runId") if car else None

        car_note = ""
        if car and car["n"] >= 5:
            car_note = (f" 과거 동일 유형({event['eventType']}) 이벤트 {car['n']}건의 "
                        f"평균 CAR[-1,+5]는 {car['carMean'] * 100:+.1f}% 였습니다.")
        iid = f"ins_event_{eid.replace(':', '_')}"
        insights.append({
            "insightId": iid, "insightType": "EVENT_IMPACT",
            "title": f"이벤트 전파: {event['title'][:60]}",
            "narrative": (f"{event['title']} — 전파 경로 상위: {targets}. "
                          f"포트폴리오 영향도 {report['portfolioImpactScore'] * 100:.2f}.{car_note}"),
            "severity": min(1.0, report["portfolioImpactScore"] * 10),
            "confidence": round(min(1.0, (car["n"] / 30) if car else 0.1), 2),
            "validationStatus": status,
            "validationSummary": summary,
            "evaluationRunId": eval_run_id,
            "createdAt": _now(), "asOfDate": as_of,
        })
        links.append(LinkRecord("insightFromEvent", "Insight", iid, etype_obj, eid))
        for t in top:
            links.append(LinkRecord("insightAboutInstrument", "Insight", iid,
                                    "Instrument", t["instrumentId"]))
    return insights, links
