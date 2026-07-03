"""자동 리밸런싱 제안 — 파이프라인도 kinetic layer(ActionEngine)를 통해 제안한다.

트리거: 비중 한도 초과(CONCENTRATION) 또는 VaR 한도 위반(LIMIT_BREACH).
생성된 제안은 proposeRebalance 액션 → 백테스트 검증 → PENDING (사람 결재 대기).
중복 방지: 동일 asOfDate 에 열린(PENDING/DRAFT) 제안이 있으면 스킵.
"""
from __future__ import annotations

from ontoquant.core.actions import ActionEngine
from ontoquant.core.store import OntologyStore

PROXY_ORDER = ["KRX:069500", "ARCA:SPY", "XNAS:QQQ"]  # 감축분 이동 대상 (지수 ETF, 한도 여유 내 배분)
HEADROOM_BUFFER = 0.005


def build_reduction_legs(store: OntologyStore) -> tuple[list[dict], list[str], str]:
    """한도 위반 기반 감축 legs + 근거 인사이트 id."""
    portfolio = store.query("Portfolio")[0]
    limits = portfolio.get("riskLimits") or {}
    max_w = limits.get("maxWeightPerName")
    legs: list[dict] = []
    insight_ids: list[str] = []
    reasons: list[str] = []
    freed = 0.0
    if max_w:
        for pos in sorted(store.query("Position"), key=lambda p: -(p.get("weight") or 0)):
            w = pos.get("weight")
            if w is None or w <= max_w:
                continue
            delta = round(max_w - w, 4)  # 음수 (감축)
            inst = store.get("Instrument", pos["instrumentId"]) or {}
            legs.append({
                "instrumentId": pos["instrumentId"], "side": "SELL",
                "targetWeightDelta": delta,
                "reason": f"비중 {w * 100:.1f}% → 한도 {max_w * 100:.0f}%",
            })
            freed += -delta
            reasons.append(f"{inst.get('nameKo') or pos['instrumentId']} {w * 100:.1f}%")
    for ins in store.query("Insight", where={"insightType": "CONCENTRATION"}):
        insight_ids.append(ins["insightId"])
    for ins in store.query("Insight", where={"insightType": "LIMIT_BREACH"}):
        insight_ids.append(ins["insightId"])
    if legs and freed > 0.005 and max_w:
        # 감축분을 지수 ETF 들에 한도 여유(headroom) 내로 배분 — 새 위반을 만들지 않는다
        weights = {p["instrumentId"]: float(p.get("weight") or 0.0) for p in store.query("Position")}
        remaining = freed
        for proxy in PROXY_ORDER:
            if remaining <= 0.001:
                break
            headroom = max_w - weights.get(proxy, 0.0) - HEADROOM_BUFFER
            alloc = round(min(remaining, max(0.0, headroom)), 4)
            if alloc <= 0.001:
                continue
            legs.append({
                "instrumentId": proxy, "side": "BUY",
                "targetWeightDelta": alloc,
                "reason": f"감축분 분산 (한도 여유 {headroom * 100:.1f}%p 내)",
            })
            remaining = round(remaining - alloc, 4)
        # 잔여분은 현금 보유 (leg 없음 = 현금)
    rationale = (f"리스크 한도 위반 해소: {', '.join(reasons)} 종목을 한도까지 감축하고 "
                 f"{freed * 100:.1f}%p 를 지수 ETF 로 분산합니다. "
                 f"근거 인사이트 {len(insight_ids)}건 (한도 위반/집중도).")
    return legs, insight_ids, rationale


def run(store: OntologyStore) -> dict:
    as_of = str(store.query("RiskMetric", limit=1)[0]["asOfDate"]) if store.count("RiskMetric") else None
    open_props = [p for p in store.query("RebalanceProposal")
                  if p.get("status") in ("DRAFT", "PENDING") and p.get("asOfDate") == as_of]
    if open_props:
        return {"status": "skipped (open proposal exists)", "open": len(open_props)}
    legs, insight_ids, rationale = build_reduction_legs(store)
    if not legs:
        return {"status": "no-trigger"}
    engine = ActionEngine(store, actor="pipeline")
    result = engine.submit("proposeRebalance", {
        "portfolioId": "main",
        "title": f"한도 위반 해소 리밸런싱 ({as_of})",
        "legs": legs, "rationale": rationale, "insightIds": insight_ids,
    })
    if not result["ok"]:
        return {"status": "rejected", "failures": result["failures"]}
    return {"status": "ok", "proposalId": result["created"].get("RebalanceProposal"),
            "legs": len(legs)}
