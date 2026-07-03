"""섹터/현금/감성/재무 인사이트 — 상황 진단 + 구체 대응 1문장 + 실행 프리셋.

원칙:
- 결정적 사실(비중/한도/재무 수치/VIX z)은 VALIDATED, 통계적 주장(감성 신호)은
  UNVALIDATED 로 시작해 사후 성과로 검증을 쌓는다.
- recommendedAction 은 대시보드 표시용 label + MCP 실행 프리셋(paramsPreset).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ontoquant.core.store import LinkRecord, OntologyStore

CLUSTER_MIN_EVENTS = 3
CLUSTER_WINDOW_DAYS = 7
SENTIMENT_SHIFT_MIN_NEWS = 3
SENTIMENT_SHIFT_THRESHOLD = -0.4
VIX_Z_MIN = 2.0
MARGIN_SHIFT_PP = 0.05     # 영업이익률 ±5%p
REVENUE_SWING = 0.15       # 매출 YoY ±15%


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sector_weights(store: OntologyStore) -> tuple[dict[str, float], dict[str, list[tuple[str, float]]]]:
    """섹터별 비중 합 + 멤버 (instrumentId, weight) 목록."""
    inst_sector = {r.fromPk: r.toPk for r in store.links("instrumentInSector")}
    totals: dict[str, float] = defaultdict(float)
    members: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for pos in store.query("Position"):
        w = float(pos.get("weight") or 0.0)
        sid = inst_sector.get(pos["instrumentId"])
        if sid and w > 0:
            totals[sid] += w
            members[sid].append((pos["instrumentId"], w))
    return dict(totals), dict(members)


def sector_concentration(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    insights, links = [], []
    portfolio = store.query("Portfolio")[0]
    max_sw = (portfolio.get("riskLimits") or {}).get("maxSectorWeight")
    if not max_sw:
        return insights, links
    totals, members = sector_weights(store)
    for sid, w in totals.items():
        if sid == "BROAD" or w <= max_sw:
            continue
        sector = store.get("Sector", sid) or {}
        name = sector.get("nameKo") or sid
        over = w - max_sw
        legs = [
            {"instrumentId": iid, "side": "SELL",
             "targetWeightDelta": round(-over * mw / w, 4),
             "reason": f"{name} 섹터 비중 축소"}
            for iid, mw in sorted(members.get(sid, []), key=lambda x: -x[1])
        ]
        iid_ins = f"ins_secconc_{sid}_{as_of}"
        insights.append({
            "insightId": iid_ins, "insightType": "SECTOR_CONCENTRATION",
            "sectorId": sid,
            "title": f"{name} 섹터 쏠림 {w * 100:.0f}%",
            "narrative": (f"{name} 섹터가 포트폴리오의 {w * 100:.0f}%를 차지합니다. "
                          f"한도는 {max_sw * 100:.0f}%입니다. "
                          f"{over * 100:.1f}%p를 다른 섹터로 옮기는 것을 검토하세요."),
            "severity": min(1.0, w / max_sw - 0.6),
            "confidence": 1.0, "validationStatus": "VALIDATED",
            "validationSummary": "보유 비중 집계 사실",
            "recommendedAction": {
                "label": f"{name} 비중 {over * 100:.1f}%p 줄이기",
                "actionApiName": "proposeRebalance",
                "paramsPreset": {"title": f"{name} 섹터 쏠림 해소",
                                 "legs": legs,
                                 "rationale": f"{name} 섹터 {w * 100:.0f}% → 한도 {max_sw * 100:.0f}% 이내로 축소"},
            },
            "createdAt": _now(), "asOfDate": as_of,
        })
        for iid, _ in members.get(sid, [])[:5]:
            links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins,
                                    "Instrument", iid))
    return insights, links


def sector_event_cluster(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    """한 섹터에 7일 내 위험 이벤트가 몰리면 경고. 근거 = PIT CAR 악재 타입 or 부정 감성."""
    from ontoquant.insights.event_study import get_type_summary

    insights, links = [], []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CLUSTER_WINDOW_DAYS)).isoformat()
    inst_sector = {r.fromPk: r.toPk for r in store.links("instrumentInSector")}
    held = {p["instrumentId"] for p in store.query("Position") if (p.get("weight") or 0) > 0}
    event_types = store.schema.interfaces["Event"].implementedBy

    by_sector: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    car_cache: dict[tuple[str, str], dict | None] = {}
    for e in store.query("Event"):
        if str(e.get("occurredAt") or "") < cutoff or (e.get("severity") or 0) < 0.4:
            continue
        market = e.get("market") or "KR"
        key = (e["eventType"], market)
        if key not in car_cache:
            car_cache[key] = get_type_summary(store, e["eventType"], market)
        stats = car_cache[key]
        bad_type = bool(stats and stats["n"] >= 10 and stats["carMean"] < -0.005)
        bad_sent = (e.get("sentiment") or 0) < -0.5
        if not (bad_type or bad_sent):
            continue
        otype = store.get_type_of(e["eventId"], event_types)
        if not otype:
            continue
        sids = {inst_sector.get(nb.pk) for nb in
                store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out")}
        sids |= {nb.pk for nb in
                 store.neighbors(otype, e["eventId"], "eventAffectsSector", "out")}
        for sid in filter(None, sids):
            by_sector[sid].append((e, otype))

    # 신호 희석 방지: 이벤트 수 상위 2개 섹터만 (여러 섹터 동시 발화 시 핵심만)
    ranked = sorted(by_sector.items(), key=lambda kv: -len(kv[1]))[:2]
    for sid, events in ranked:
        if len(events) < CLUSTER_MIN_EVENTS:
            continue
        if len({e["eventId"].split(":")[0] + (e.get("tickerHint") or "") for e, _ in events}) < 2:
            continue  # 단일 출처 반복이면 군집으로 보지 않는다
        sector = store.get("Sector", sid) or {}
        name = sector.get("nameKo") or sid
        exposed = [i for i, s in inst_sector.items() if s == sid and i in held]
        if not exposed:
            continue
        iid_ins = f"ins_seccluster_{sid}_{as_of}"
        titles = " · ".join(e["title"][:24] for e, _ in events[:3])
        insights.append({
            "insightId": iid_ins, "insightType": "SECTOR_EVENT_CLUSTER",
            "sectorId": sid,
            "title": f"{name} 섹터에 위험 신호 {len(events)}건",
            "narrative": (f"최근 {CLUSTER_WINDOW_DAYS}일간 {name} 섹터에서 가격에 부정적이었던 "
                          f"유형의 이벤트가 {len(events)}건 발생했습니다 ({titles}). "
                          f"보유 {len(exposed)}종목의 노출 축소를 검토하세요."),
            "severity": min(1.0, 0.4 + 0.1 * len(events)),
            "confidence": 0.7, "validationStatus": "VALIDATED",
            "validationSummary": "과거 검증된 악재 유형의 군집 (PIT CAR 근거)",
            "recommendedAction": {
                "label": f"{name} 섹터 노출 축소 검토",
                "actionApiName": "proposeRebalance",
                "paramsPreset": {"title": f"{name} 섹터 위험 신호 대응",
                                 "legs": [{"instrumentId": i, "side": "SELL",
                                           "targetWeightDelta": -0.02,
                                           "reason": "섹터 위험 이벤트 군집"} for i in exposed[:3]],
                                 "rationale": f"{name} 섹터 위험 이벤트 {len(events)}건 군집 대응"},
            },
            "createdAt": _now(), "asOfDate": as_of,
        })
        for e, otype in events[:4]:
            links.append(LinkRecord("insightFromEvent", "Insight", iid_ins, otype, e["eventId"]))
        for i in exposed[:5]:
            links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins, "Instrument", i))
    return insights, links


def cash_allocation(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    """변동성 급등(VIX z>=2, 5일 내) 또는 VaR 한도 초과 → 현금 확대 제안."""
    insights, links = [], []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    vix_events = [e for e in store.query("MacroEvent", where={"eventType": "VOL_SPIKE"})
                  if str(e.get("occurredAt") or "") >= cutoff
                  and (e.get("zScore") or 0) >= VIX_Z_MIN]
    var_breach = next((m for m in store.query("RiskMetric",
                                              where={"metricType": "VAR_95_1D", "limitBreached": True})), None)
    if not vix_events and var_breach is None:
        return insights, links

    contrib = sorted(store.query("RiskMetric", where={"metricType": "CONTRIB_VAR"}),
                     key=lambda m: -m["value"])[:3]
    top_ids = [store.get("Position", m["scopeId"]) for m in contrib]
    legs = [{"instrumentId": p["instrumentId"], "side": "SELL", "targetWeightDelta": -0.02,
             "reason": "손실 기여 상위 종목 축소 (현금 확보)"}
            for p in top_ids if p]
    trigger = (f"변동성 지수가 {vix_events[0]['zScore']:+.1f} 표준편차 급등"
               if vix_events else "하루 예상 손실이 설정 한도 초과")
    iid_ins = f"ins_cash_{as_of}"
    insights.append({
        "insightId": iid_ins, "insightType": "CASH_ALLOCATION",
        "title": "현금 비중 확대 검토",
        "narrative": (f"{trigger} 상태입니다. 손실 기여가 큰 종목부터 "
                      f"{len(legs) * 2}%p 줄여 현금을 확보하는 것을 검토하세요."),
        "severity": 0.75, "confidence": 1.0,
        "validationStatus": "VALIDATED",
        "validationSummary": "변동성/한도 지표 사실",
        "recommendedAction": {
            "label": f"현금 {len(legs) * 2}%p 확보",
            "actionApiName": "proposeRebalance",
            "paramsPreset": {"title": "변동성 급등 대응 현금 확보", "legs": legs,
                             "rationale": f"{trigger} — 손실 기여 상위 축소로 현금 확보"},
        },
        "createdAt": _now(), "asOfDate": as_of,
    })
    for e in vix_events[:2]:
        links.append(LinkRecord("insightFromEvent", "Insight", iid_ins, "MacroEvent", e["eventId"]))
    return insights, links


def news_sentiment_shift(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    """보유 종목의 7일 뉴스 감성 평균 급락 → 확인 권고 (통계 신호, UNVALIDATED 시작)."""
    insights, links = [], []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    held = {p["instrumentId"]: p for p in store.query("Position") if (p.get("weight") or 0) > 0}
    by_inst: dict[str, list[dict]] = defaultdict(list)
    for e in store.query("NewsEvent"):
        if str(e.get("occurredAt") or "") < cutoff or e.get("sentiment") is None:
            continue
        for nb in store.neighbors("NewsEvent", e["eventId"], "eventAffectsInstrument", "out"):
            if nb.pk in held:
                by_inst[nb.pk].append(e)
    for iid, events in by_inst.items():
        if len(events) < SENTIMENT_SHIFT_MIN_NEWS:
            continue
        avg = sum(e["sentiment"] for e in events) / len(events)
        if avg > SENTIMENT_SHIFT_THRESHOLD:
            continue
        inst = store.get("Instrument", iid) or {}
        label = inst.get("nameKo") or inst.get("name") or iid
        iid_ins = f"ins_senti_{iid.replace(':', '_')}_{as_of}"
        insights.append({
            "insightId": iid_ins, "insightType": "NEWS_SENTIMENT_SHIFT",
            "title": f"{label} 뉴스 흐름 부정적",
            "narrative": (f"최근 7일 {label} 관련 뉴스 {len(events)}건의 평균 감성이 "
                          f"{avg:+.2f}로 부정적입니다. 새 공시가 있는지 확인하고 "
                          f"비중 축소 여부를 검토하세요."),
            "severity": min(1.0, abs(avg)),
            "confidence": round(min(1.0, len(events) / 10), 2),
            "validationStatus": "UNVALIDATED",
            "validationSummary": "감성 신호는 사후 성과로 검증을 쌓는 중",
            "recommendedAction": {"label": f"{label} 공시·뉴스 확인",
                                  "actionApiName": None, "paramsPreset": None},
            "createdAt": _now(), "asOfDate": as_of,
        })
        links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins, "Instrument", iid))
        for e in sorted(events, key=lambda x: x["sentiment"])[:3]:
            links.append(LinkRecord("insightFromEvent", "Insight", iid_ins, "NewsEvent", e["eventId"]))
    return insights, links


def fundamental_shift(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    """보유 종목의 최신 분기 재무 급변 (YoY 동일 라벨 비교) → 사실 기반 인사이트."""
    insights, links = [], []
    held = {p["instrumentId"] for p in store.query("Position") if (p.get("weight") or 0) > 0}
    company_inst = {r.fromPk: r.toPk for r in store.links("companyListedAs")}
    by_company: dict[str, list[dict]] = defaultdict(list)
    for f in store.query("Fundamental"):
        by_company[f["companyId"]].append(f)
    candidates = []
    for cid, rows in by_company.items():
        inst_id = company_inst.get(cid)
        if inst_id not in held:
            continue
        rows.sort(key=lambda r: r["period"])
        latest = rows[-1]
        label_suffix = latest["period"][4:]
        prior = next((r for r in reversed(rows[:-1])
                      if r["period"] == f"{int(latest['period'][:4]) - 1}{label_suffix}"), None)
        if not prior:
            continue
        notes, score, signs = [], 0.0, []
        rev0, rev1 = prior.get("revenue"), latest.get("revenue")
        op0, op1 = prior.get("operatingIncome"), latest.get("operatingIncome")
        if rev0 and rev1:
            growth = rev1 / rev0 - 1
            if abs(growth) >= REVENUE_SWING:
                notes.append(f"매출이 1년 전 같은 분기보다 {growth * 100:+.0f}%")
                score = max(score, abs(growth))
                signs.append(growth)
        if rev0 and rev1 and op0 is not None and op1 is not None and rev0 > 0 and rev1 > 0:
            margin_delta = op1 / rev1 - op0 / rev0
            if abs(margin_delta) >= MARGIN_SHIFT_PP:
                notes.append(f"영업이익률이 {margin_delta * 100:+.1f}%p 변화")
                score = max(score, abs(margin_delta) * 3)
                signs.append(margin_delta)
        if notes:
            candidates.append((score, inst_id, latest, notes, sum(signs)))

    # 신호 희석 방지: 변화 크기 상위 3건만
    for score, inst_id, latest, notes, sign_sum in sorted(candidates, reverse=True)[:3]:
        inst = store.get("Instrument", inst_id) or {}
        label = inst.get("nameKo") or inst.get("name") or inst_id
        direction = "개선" if sign_sum > 0 else "악화"
        iid_ins = f"ins_fund_{inst_id.replace(':', '_')}_{latest['period']}"
        insights.append({
            "insightId": iid_ins, "insightType": "FUNDAMENTAL_SHIFT",
            "title": f"{label} 실적 체질 {direction} ({latest['period']})",
            "narrative": (f"{label}의 {latest['period']} 재무: " + ", ".join(notes) +
                          ". 비중 조정 근거로 검토하세요."),
            "severity": round(min(1.0, 0.3 + score), 3), "confidence": 1.0,
            "validationStatus": "VALIDATED",
            "validationSummary": "공시 재무 수치 사실 (YoY 동일 분기 비교)",
            "createdAt": _now(), "asOfDate": as_of,
        })
        links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins, "Instrument", inst_id))
    return insights, links


ALL_RULES = (sector_concentration, sector_event_cluster, cash_allocation,
             news_sentiment_shift, fundamental_shift)


def build(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    insights, links = [], []
    for fn in ALL_RULES:
        ins, lk = fn(store, as_of)
        insights.extend(ins)
        links.extend(lk)
    return insights, links
