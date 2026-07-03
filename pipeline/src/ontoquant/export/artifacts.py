"""정적 대시보드 산출물 — dashboard/public/data/*.json

Next.js 정적 export 가 빌드 타임에 fs 로 읽는 유일한 데이터 표면.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.core.audit import read_log
from ontoquant.core.store import OntologyStore
from ontoquant.ingest import tsio

EXPOSURE_EDGE_T = 2.0  # 시장 팩터 외에는 |t| >= 2 인 익스포저만 그래프 엣지로
MARKET_FACTORS = {"FF:MKT", "KR:MKT"}
RECENT_EVENT_DAYS = 90
GRAPH_EVENT_CAP = 12   # 그래프에는 영향도 상위 이벤트만 (피드에는 전체)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # 표시 계층 규칙: 엠대시 금지 (과거 저장 데이터 안전망 — 원장은 건드리지 않음)
    path.write_text(text.replace("—", "·"), encoding="utf-8")


def _node(object_type: str, pk: str, label: str, props: dict) -> dict:
    return {"id": f"{object_type}:{pk}", "objectType": object_type, "pk": pk,
            "label": label, "props": props}


def export_graph(store: OntologyStore) -> dict:
    nodes, edges = [], []
    portfolio = store.query("Portfolio")[0]
    pf_id = portfolio["portfolioId"]
    nodes.append(_node("Portfolio", pf_id, portfolio.get("name", pf_id), {
        "totalValueBase": portfolio.get("totalValueBase"),
    }))
    for pos in store.query("Position", where={"portfolioId": pf_id}):
        if pos.get("quantity") is None:
            continue
        inst = store.get("Instrument", pos["instrumentId"]) or {}
        nodes.append(_node("Position", pos["positionId"],
                           inst.get("nameKo") or inst.get("name") or pos["instrumentId"], {
            "weight": pos.get("weight"), "marketValueBase": pos.get("marketValueBase"),
            "instrumentId": pos["instrumentId"], "sectorId": inst.get("sectorId"),
        }))
        edges.append({"source": f"Portfolio:{pf_id}", "target": f"Position:{pos['positionId']}",
                      "linkType": "portfolioPositions", "props": {}})
        edges.append({"source": f"Position:{pos['positionId']}",
                      "target": f"Instrument:{pos['instrumentId']}",
                      "linkType": "positionInstrument", "props": {}})
    for inst in store.query("Instrument"):
        nodes.append(_node("Instrument", inst["instrumentId"],
                           inst.get("nameKo") or inst["name"], {
            "ticker": inst["ticker"], "market": inst["market"],
            "sectorId": inst.get("sectorId"), "currency": inst["currency"],
        }))
    for sector in store.query("Sector"):
        nodes.append(_node("Sector", sector["sectorId"],
                           sector.get("nameKo") or sector["name"], {
            "colorToken": sector.get("colorToken"),
        }))
    for rec in store.links("instrumentInSector"):
        edges.append({"source": f"Instrument:{rec.fromPk}", "target": f"Sector:{rec.toPk}",
                      "linkType": "instrumentInSector", "props": {}})
    used_factors = set()
    for exp in store.query("FactorExposure"):
        fid = exp["factorId"]
        significant = fid in MARKET_FACTORS or abs(exp.get("tStat") or 0) >= EXPOSURE_EDGE_T
        if not significant:
            continue
        used_factors.add(fid)
        edges.append({
            "source": f"Instrument:{exp['instrumentId']}", "target": f"Factor:{fid}",
            "linkType": "exposure",
            "props": {"beta": exp["beta"], "tStat": exp.get("tStat"), "stale": exp.get("stale")},
        })
    # 이벤트가 참조하는 팩터도 노드로 포함 (eventDrivesFactor)
    for rec in store.links("eventDrivesFactor"):
        used_factors.add(rec.toPk)
    for factor in store.query("Factor"):
        if factor["factorId"] in used_factors:
            nodes.append(_node("Factor", factor["factorId"],
                               factor.get("nameKo") or factor["name"], {
                "factorType": factor["factorType"],
            }))

    # 이벤트: 최근 7일 × 영향도 상위 N 만 (그래프 다이어트 — 나머지는 이벤트 피드에서)
    impacts_for_graph = {}
    impacts_path_g = config.COMPUTED_DIR / "impacts.json"
    if impacts_path_g.exists():
        impacts_for_graph = json.loads(impacts_path_g.read_text(encoding="utf-8"))
    cutoff = (pd.Timestamp.utcnow() - pd.Timedelta(days=7)).isoformat()
    recent_events = [e for e in store.query("Event") if str(e.get("occurredAt", "")) >= cutoff]
    recent_events.sort(key=lambda e: -(impacts_for_graph.get(e["eventId"], {})
                                       .get("portfolioImpactScore") or 0))
    recent_events = recent_events[:GRAPH_EVENT_CAP]
    event_types = {t: True for t in store.schema.interfaces["Event"].implementedBy}
    for ev in recent_events:
        etype = store.get_type_of(ev["eventId"], event_types.keys())
        nodes.append(_node(etype or "Event", ev["eventId"], ev["title"][:48], {
            "eventType": ev.get("eventType"), "severity": ev.get("severity"),
            "occurredAt": ev.get("occurredAt"), "sentiment": ev.get("sentiment"),
            "impactScore": impacts_for_graph.get(ev["eventId"], {}).get("portfolioImpactScore"),
        }))
    node_ids = {n["id"] for n in nodes}
    for link_type in ("eventAffectsInstrument", "eventDrivesFactor", "eventAffectsSector",
                      "insightFromEvent", "insightAboutInstrument"):
        for rec in store.links(link_type):
            src, tgt = f"{rec.fromType}:{rec.fromPk}", f"{rec.toType}:{rec.toPk}"
            if src in node_ids and tgt in node_ids:
                edges.append({"source": src, "target": tgt, "linkType": link_type,
                              "props": rec.props})
    return {"nodes": nodes, "edges": edges}


def export_all(store: OntologyStore, statuses: dict | None = None) -> dict:
    out = config.EXPORT_DIR
    portfolio = store.query("Portfolio")[0]
    pf_id = portfolio["portfolioId"]
    positions = store.query("Position", where={"portfolioId": pf_id})
    instruments = {i["instrumentId"]: i for i in store.query("Instrument")}
    as_of = None

    sectors = {s["sectorId"]: s for s in store.query("Sector")}

    # portfolio.json — 병합 완료된 최종 뷰
    pos_view = []
    for pos in sorted(positions, key=lambda p: -(p.get("marketValueBase") or 0)):
        inst = instruments.get(pos["instrumentId"], {})
        sec = sectors.get(inst.get("sectorId") or "", {})
        pos_view.append({**pos, "instrument": {
            "name": inst.get("name"), "nameKo": inst.get("nameKo"),
            "ticker": inst.get("ticker"), "market": inst.get("market"),
            "sectorId": inst.get("sectorId"),
            "sector": sec.get("nameKo") or inst.get("sectorId"),
            "currency": inst.get("currency"),
        }})
    _write(out / "portfolio.json", {"portfolio": portfolio, "positions": pos_view})

    # risk metrics (최신) — portfolio.json 과 분리해 홈 타일에서 소비
    metrics = store.query("RiskMetric")
    _write(out / "risk_metrics.json", metrics)

    # risk_series.json
    series_path = config.COMPUTED_DIR / "risk_series.parquet"
    if series_path.exists():
        df = pd.read_parquet(series_path)
        as_of = str(pd.to_datetime(df["date"]).max().date())
        _write(out / "risk_series.json", {
            "dates": [str(d.date()) for d in pd.to_datetime(df["date"])],
            "totalValueBase": [round(float(v), 2) for v in df["totalValueBase"]],
            "drawdown": [None if pd.isna(v) else round(float(v), 6) for v in df["drawdown"]],
            "var95": [None if pd.isna(v) else round(float(v), 6) for v in df["var95"]],
            "vol30": [None if pd.isna(v) else round(float(v), 6) for v in df["vol30"]],
        })

    # prices/{id}.json — 종목 상세 차트 (1년)
    for iid, inst in instruments.items():
        df = tsio.read_ts(tsio.price_path(iid))
        if df is None or df.empty:
            continue
        tail = df.tail(260)
        _write(out / "prices" / f"{tsio.sanitize(iid)}.json", {
            "instrumentId": iid,
            "dates": [str(d.date()) for d in tail["date"]],
            "close": [round(float(v), 4) for v in tail["close"]],
        })

    # exposures.json — 종목×팩터 베타 행렬 + 포트폴리오 익스포저
    exposures = store.query("FactorExposure")
    by_inst: dict[str, dict] = {}
    for e in exposures:
        by_inst.setdefault(e["instrumentId"], {})[e["factorId"]] = {
            "beta": e["beta"], "tStat": e.get("tStat"), "r2": e.get("r2"),
            "stale": e.get("stale", False),
        }
    weights = {p["instrumentId"]: p.get("weight") or 0.0 for p in positions}
    port_exp: dict[str, float] = {}
    for iid, facs in by_inst.items():
        w = weights.get(iid, 0.0)
        for fid, v in facs.items():
            port_exp[fid] = port_exp.get(fid, 0.0) + w * v["beta"]
    _write(out / "exposures.json", {
        "instruments": [
            {"instrumentId": iid,
             "name": (instruments.get(iid, {}).get("nameKo") or instruments.get(iid, {}).get("name")),
             "weight": weights.get(iid, 0.0),
             "exposures": facs}
            for iid, facs in sorted(by_inst.items())
        ],
        "portfolio": {k: round(v, 4) for k, v in sorted(port_exp.items())},
    })

    # graph / events / insights / proposals / decisions / models
    _write(out / "graph.json", export_graph(store))
    events = sorted(store.query("Event"), key=lambda e: str(e.get("occurredAt", "")), reverse=True)
    impacts_path = config.COMPUTED_DIR / "impacts.json"
    impacts = json.loads(impacts_path.read_text(encoding="utf-8")) if impacts_path.exists() else {}
    event_types = store.schema.interfaces["Event"].implementedBy
    event_instruments: dict[str, list[str]] = {}
    for rec in store.links("eventAffectsInstrument"):
        event_instruments.setdefault(rec.fromPk, []).append(rec.toPk)
    _write(out / "events.json", [
        {**e, "objectType": store.get_type_of(e["eventId"], event_types),
         "instrumentIds": event_instruments.get(e["eventId"], []),
         "impact": impacts.get(e["eventId"])}
        for e in events[:400]
    ])
    _write(out / "insights.json", sorted(
        store.query("Insight"), key=lambda i: (str(i.get("asOfDate", "")), i.get("severity") or 0),
        reverse=True))

    proposals = store.query("RebalanceProposal")
    eval_runs = {r["runId"]: r for r in store.query("EvaluationRun")}
    _write(out / "proposals.json", [
        {**p, "backtest": eval_runs.get(p.get("backtestRunId"))}
        for p in sorted(proposals, key=lambda p: str(p.get("createdAt", "")), reverse=True)
    ])
    decisions = store.query("Decision", order_by="decidedAt")
    _write(out / "decisions.json", {"decisions": decisions, "actionLog": read_log(limit=200)})

    # sectors.json — 섹터별 비중/손실기여/이벤트/인사이트 집계
    from ontoquant.insights.sector_rules import sector_weights
    totals, members = sector_weights(store)
    contrib = {m["scopeId"]: m["value"] for m in store.query(
        "RiskMetric", where={"metricType": "CONTRIB_VAR"})}
    cutoff7 = (pd.Timestamp.utcnow() - pd.Timedelta(days=7)).isoformat()
    inst_sector = {r.fromPk: r.toPk for r in store.links("instrumentInSector")}
    event_types_l = store.schema.interfaces["Event"].implementedBy
    sec_events: dict[str, int] = {}
    for e in store.query("Event"):
        if str(e.get("occurredAt", "")) < cutoff7:
            continue
        otype = store.get_type_of(e["eventId"], event_types_l)
        if not otype:
            continue
        sids = {inst_sector.get(nb.pk) for nb in
                store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out")}
        sids |= {nb.pk for nb in store.neighbors(otype, e["eventId"], "eventAffectsSector", "out")}
        for sid in filter(None, sids):
            sec_events[sid] = sec_events.get(sid, 0) + 1
    sector_insights: dict[str, list] = {}
    for i in store.query("Insight"):
        if i.get("sectorId"):
            sector_insights.setdefault(i["sectorId"], []).append(i["insightId"])
    _write(out / "sectors.json", [
        {
            "sectorId": s["sectorId"], "name": s["name"], "nameKo": s.get("nameKo"),
            "colorToken": s.get("colorToken"),
            "weight": round(totals.get(s["sectorId"], 0.0), 4),
            "members": [
                {"instrumentId": iid,
                 "name": (instruments.get(iid, {}).get("nameKo") or instruments.get(iid, {}).get("name")),
                 "weight": round(w, 4),
                 "contribVar": contrib.get(f"{pf_id}:{iid}")}
                for iid, w in sorted(members.get(s["sectorId"], []), key=lambda x: -x[1])
            ],
            "contribVar": round(sum(contrib.get(f"{pf_id}:{iid}", 0) or 0
                                    for iid, _ in members.get(s["sectorId"], [])), 5),
            "recentEvents": sec_events.get(s["sectorId"], 0),
            "insightIds": sector_insights.get(s["sectorId"], []),
        }
        for s in sorted(store.query("Sector"), key=lambda s: -totals.get(s["sectorId"], 0))
    ])

    _write(out / "scenarios.json", store.query("Scenario", order_by="createdAt"))

    # 백테스트 equity curve 복사
    bt_src = config.COMPUTED_DIR / "backtests"
    if bt_src.is_dir():
        for f in bt_src.glob("*.json"):
            (out / "backtests").mkdir(parents=True, exist_ok=True)
            (out / "backtests" / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    models = store.query("ModelVersion")
    runs_by_model: dict[str, list] = {}
    for r in sorted(eval_runs.values(), key=lambda r: str(r.get("createdAt", "")), reverse=True):
        runs_by_model.setdefault(r["modelVersionId"], []).append(r)
    _write(out / "models.json", [
        {**m, "evaluationRuns": runs_by_model.get(m["modelVersionId"], [])[:30]}
        for m in models
    ])

    # meta.json (+ 데이터 품질 요약)
    quality_path = config.COMPUTED_DIR / "quality.json"
    quality_summary = None
    if quality_path.exists():
        q = json.loads(quality_path.read_text(encoding="utf-8"))
        quality_summary = {"asOf": q.get("asOf"), **q.get("summary", {}),
                           "flags": q.get("flags", [])[:10]}
    _write(out / "meta.json", {
        "asOf": as_of,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": statuses or {},
        "counts": {t: store.count(t) for t in sorted(store.schema.objectTypes)},
        "dataQuality": quality_summary,
    })
    return {"asOf": as_of, "exported": True}
