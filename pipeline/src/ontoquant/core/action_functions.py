"""functionRule 구현 + submission criteria 헬퍼.

규칙 함수 시그니처: fn(store, ctx) — 쓰기는 반드시 ctx["batch"] 에 스테이징.
(예외: EvaluationRun 기록은 평가 이력이므로 즉시 기록되어도 무해)
"""
from __future__ import annotations

from ontoquant.core.actions import AttrView, register_function
from ontoquant.core.store import LinkRecord, OntologyStore


def _raw(obj) -> dict:
    return obj.raw() if isinstance(obj, AttrView) else (obj or {})


# ---------------------------------------------------------------- 헬퍼

def evaluation_passed(store: OntologyStore, run_id) -> bool:
    if not run_id:
        return False
    run = store.get("EvaluationRun", run_id)
    return bool(run and run.get("passedGates"))


def passed_eval_count_helper(store: OntologyStore, mv_id) -> int:
    from ontoquant.modeling.objective import passed_eval_count
    return passed_eval_count(store, mv_id)


def passed_wf_count_helper(store: OntologyStore, model_id) -> int:
    from ontoquant.modeling.objective import passed_wf_count
    return passed_wf_count(store, model_id)


def all_instruments_exist(store: OntologyStore, legs) -> bool:
    legs = legs or []
    return all(store.get("Instrument", l.get("instrumentId")) is not None for l in legs)


def abs_weight_delta_sum(legs) -> float:
    return sum(abs(float(l.get("targetWeightDelta", 0))) for l in (legs or []))


def _current_weights(store: OntologyStore) -> dict[str, float]:
    return {p["instrumentId"]: float(p.get("weight") or 0.0) for p in store.query("Position")}


def apply_legs_to_weights(weights: dict[str, float], legs: list[dict]) -> dict[str, float]:
    out = dict(weights)
    for leg in legs:
        iid = leg["instrumentId"]
        out[iid] = max(0.0, out.get(iid, 0.0) + float(leg.get("targetWeightDelta", 0)))
    return out


def would_breach_limits(store: OntologyStore, proposal) -> bool:
    """제안 적용 시 비중/VaR 한도 위반 여부 (승인 차단용)."""
    p = _raw(proposal)
    portfolio = store.query("Portfolio")[0]
    limits = portfolio.get("riskLimits") or {}
    new_w = apply_legs_to_weights(_current_weights(store), p.get("legs") or [])
    max_w = limits.get("maxWeightPerName")
    if max_w:
        for iid, w in new_w.items():
            cur = _current_weights(store).get(iid, 0.0)
            # 이미 한도를 넘던 종목은 "악화"만 차단 (감축 제안이 스스로 막히지 않도록)
            if w > max_w and w > cur + 1e-9:
                return True
    max_var = limits.get("maxVar95")
    exp = p.get("expectedImpact") or {}
    if max_var and exp.get("var95Delta") is not None:
        cur_var = next((m["value"] for m in store.query(
            "RiskMetric", where={"metricType": "VAR_95_1D", "scopeType": "PORTFOLIO"})), None)
        if cur_var is not None and cur_var + exp["var95Delta"] > max_var * 1.25:
            return True
    return False


# ---------------------------------------------------------------- 규칙 함수

@register_function("apply_position_edit")
def apply_position_edit(store: OntologyStore, ctx: dict) -> None:
    params = ctx["params"]
    doc = store.read_portfolio_doc()
    positions = doc.get("positions", [])
    iid, qty = params["instrumentId"], float(params["quantity"])
    existing = next((p for p in positions if p["instrumentId"] == iid), None)
    if qty == 0:
        if existing:
            positions.remove(existing)
    elif existing:
        existing["quantity"] = qty
        if params.get("avgCostLocal") is not None:
            existing["avgCostLocal"] = float(params["avgCostLocal"])
    else:
        if params.get("avgCostLocal") is None:
            raise ValueError("신규 포지션은 avgCostLocal 이 필요합니다")
        positions.append({"instrumentId": iid, "quantity": qty,
                          "avgCostLocal": float(params["avgCostLocal"])})
    doc["positions"] = positions
    ctx["batch"].set_portfolio(doc)


@register_function("apply_risk_limit_edit")
def apply_risk_limit_edit(store: OntologyStore, ctx: dict) -> None:
    params = ctx["params"]
    doc = store.read_portfolio_doc()
    limits = doc["portfolio"].setdefault("riskLimits", {})
    for key in ("maxWeightPerName", "maxVar95", "maxSectorWeight"):
        if params.get(key) is not None:
            limits[key] = float(params[key])
    ctx["batch"].set_portfolio(doc)


@register_function("validate_proposal_backtest")
def validate_proposal_backtest(store: OntologyStore, ctx: dict) -> None:
    """proposeRebalance 규칙 — 백테스트 실행 → EvaluationRun → 제안 PENDING 전환."""
    from ontoquant.proposals import backtest

    proposal = dict(ctx.get("rebalanceProposal") or {})
    result = backtest.validate_proposal(store, proposal)
    run = result["run"]
    updated = {
        **proposal,
        "status": "PENDING",
        "backtestRunId": run["runId"],
        "expectedImpact": result.get("expectedImpact"),
    }
    ctx["batch"].upsert("writeback", "RebalanceProposal", updated)
    ctx["batch"].link("writeback", LinkRecord(
        "proposalValidatedBy", "RebalanceProposal", proposal["proposalId"],
        "EvaluationRun", run["runId"]))
    ctx["rebalanceProposal"] = updated


@register_function("apply_proposal_to_portfolio")
def apply_proposal_to_portfolio(store: OntologyStore, ctx: dict) -> None:
    """승인된 제안의 legs 를 수량으로 환산해 portfolio.json 에 반영."""
    proposal = _raw(ctx.get("proposal"))
    portfolio = store.query("Portfolio")[0]
    total = float(portfolio.get("totalValueBase") or 0)
    if total <= 0:
        raise ValueError("포트폴리오 평가액이 없어 수량 환산 불가 (compute 스테이지 필요)")
    from ontoquant.compute.returns import load_usdkrw
    fx = load_usdkrw()
    fx_last = float(fx.dropna().iloc[-1]) if fx is not None else 1400.0

    doc = store.read_portfolio_doc()
    positions = {p["instrumentId"]: p for p in doc.get("positions", [])}
    for leg in proposal.get("legs", []):
        iid = leg["instrumentId"]
        inst = store.get("Instrument", iid)
        pos_obj = store.get("Position", f"{doc['portfolio']['portfolioId']}:{iid}")
        price = (pos_obj or {}).get("lastPriceLocal")
        if not inst or not price:
            raise ValueError(f"{iid}: 가격 정보 없음")
        price_krw = float(price) * (fx_last if inst["currency"] == "USD" else 1.0)
        delta_qty = float(leg["targetWeightDelta"]) * total / price_krw
        delta_qty = round(delta_qty) if inst["currency"] == "KRW" else round(delta_qty, 2)
        cur = positions.get(iid)
        if cur is None:
            if delta_qty > 0:
                positions[iid] = {"instrumentId": iid, "quantity": delta_qty,
                                  "avgCostLocal": float(price)}
        else:
            new_qty = max(0.0, float(cur["quantity"]) + delta_qty)
            if new_qty == 0:
                positions.pop(iid)
            else:
                cur["quantity"] = new_qty
    doc["positions"] = list(positions.values())
    ctx["batch"].set_portfolio(doc)
    updated = {**proposal, "status": "EXECUTED"}
    ctx["batch"].upsert("writeback", "RebalanceProposal", updated)


@register_function("promote_model_version")
def promote_model_version(store: OntologyStore, ctx: dict) -> None:
    model = _raw(ctx.get("model"))
    for mv in store.query("ModelVersion", where={"modelId": model["modelId"], "stage": "PRODUCTION"}):
        ctx["batch"].upsert("writeback", "ModelVersion", {**mv, "stage": "ARCHIVED"})
    ctx["batch"].upsert("writeback", "ModelVersion", {**model, "stage": "PRODUCTION"})
