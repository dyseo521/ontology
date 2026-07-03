"""인사이트 규칙 — 결정적(rule-based) 인사이트 생성.

Phase 1: LIMIT_BREACH(한도 위반), CONCENTRATION(집중도)
Phase 2/3에서 EVENT_IMPACT(이벤트 스터디 검증 포함)가 추가된다.

결정적 규칙의 validationStatus 는 VALIDATED (통계적 주장이 아니라 사실 판정).
통계적 인사이트(EVENT_IMPACT)는 이벤트 스터디 게이트를 통과해야 VALIDATED.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ontoquant.core.store import LinkRecord, OntologyStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def limit_breach_insights(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    insights, links = [], []
    metric_names = {
        "VAR_95_1D": "1일 VaR(95%)", "VOL_30D": "30일 변동성",
        "HHI": "집중도(HHI)", "MDD_1Y": "1년 최대낙폭",
    }
    for m in store.query("RiskMetric", where={"limitBreached": True}):
        name = metric_names.get(m["metricType"], m["metricType"])
        iid = f"ins_limit_{m['metricId'].replace(':', '_')}_{as_of}"
        insights.append({
            "insightId": iid, "insightType": "LIMIT_BREACH",
            "title": f"리스크 한도 위반: {name}",
            "narrative": (f"{name} 이(가) {m['value']:.4f} 로 설정 한도 {m['limitValue']:.4f} 를 "
                          f"초과했습니다. 감축 리밸런싱 제안 생성을 검토하세요."),
            "severity": min(1.0, float(m["value"]) / float(m["limitValue"])) if m.get("limitValue") else 0.8,
            "confidence": 1.0,
            "validationStatus": "VALIDATED",
            "validationSummary": "결정적 규칙 (한도 위반 사실)",
            "createdAt": _now(), "asOfDate": as_of,
        })
    return insights, links


def concentration_insights(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    insights, links = [], []
    portfolio = store.query("Portfolio")[0]
    max_w = (portfolio.get("riskLimits") or {}).get("maxWeightPerName")
    if not max_w:
        return insights, links
    for pos in store.query("Position"):
        w = pos.get("weight")
        if w is None or w <= max_w:
            continue
        inst = store.get("Instrument", pos["instrumentId"]) or {}
        label = inst.get("nameKo") or inst.get("name") or pos["instrumentId"]
        iid = f"ins_conc_{pos['positionId'].replace(':', '_')}_{as_of}"
        insights.append({
            "insightId": iid, "insightType": "CONCENTRATION",
            "title": f"종목 집중: {label} 비중 {w * 100:.1f}%",
            "narrative": (f"{label} 비중이 {w * 100:.1f}% 로 종목당 한도 {max_w * 100:.0f}% 를 "
                          f"초과했습니다. 부분 매도로 분산을 회복하는 것을 검토하세요."),
            "severity": min(1.0, w / max_w - 0.5),
            "confidence": 1.0,
            "validationStatus": "VALIDATED",
            "validationSummary": "결정적 규칙 (비중 한도 사실)",
            "createdAt": _now(), "asOfDate": as_of,
        })
        links.append(LinkRecord("insightAboutInstrument", "Insight", iid,
                                "Instrument", pos["instrumentId"]))
    return insights, links


def run(store: OntologyStore, as_of: str, extra: tuple[list[dict], list[LinkRecord]] | None = None) -> dict:
    """모든 규칙 실행 → Insight 스냅샷 + 링크 교체. extra 로 이벤트 인사이트 병합."""
    from ontoquant.insights import sector_rules

    all_insights: list[dict] = []
    about_links: list[LinkRecord] = []
    event_links: list[LinkRecord] = []
    for fn in (limit_breach_insights, concentration_insights):
        ins, links = fn(store, as_of)
        all_insights.extend(ins)
        about_links.extend(links)
    ins, links = sector_rules.build(store, as_of)
    all_insights.extend(ins)
    for l in links:
        (event_links if l.linkType == "insightFromEvent" else about_links).append(l)
    if extra:
        ins, links = extra
        all_insights.extend(ins)
        for l in links:
            (event_links if l.linkType == "insightFromEvent" else about_links).append(l)

    store.replace_objects("computed", "Insight", all_insights)
    store.replace_links("computed", "insightAboutInstrument", about_links)
    store.replace_links("computed", "insightFromEvent", event_links)
    return {"insights": len(all_insights)}
