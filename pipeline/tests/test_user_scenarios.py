"""사용자 시나리오 E2E — 상황이 주어지면 올바른 인사이트/액션이 발화·차단되는가."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from ontoquant.core.actions import ActionEngine
from ontoquant.core.store import LinkRecord, OntologyStore

NOW = datetime.now(timezone.utc)


def make_store(tmp_path, *, n_equities=3, max_holdings=15) -> OntologyStore:
    (tmp_path / "writeback").mkdir(parents=True, exist_ok=True)
    instruments = [
        {"instrumentId": "KRX:069500", "ticker": "069500", "name": "KOSPI proxy",
         "market": "KRX", "currency": "KRW", "assetClass": "ETF", "sectorId": "BROAD",
         "priceSource": "NAVER", "tradable": False},
        {"instrumentId": "ARCA:SPY", "ticker": "SPY", "name": "SPY",
         "market": "ARCA", "currency": "USD", "assetClass": "ETF", "sectorId": "BROAD",
         "priceSource": "TIINGO", "tradable": True},
    ]
    positions = [{"instrumentId": "ARCA:SPY", "quantity": 5, "avgCostLocal": 500.0}]
    for i in range(max(n_equities, 16)):
        iid = f"KRX:{i:06d}"
        instruments.append({
            "instrumentId": iid, "ticker": f"{i:06d}", "name": f"EQ{i}",
            "nameKo": f"종목{i}", "market": "KRX", "currency": "KRW",
            "assetClass": "EQUITY", "sectorId": "IT" if i % 2 == 0 else "FIN",
            "priceSource": "NAVER", "tradable": True,
        })
        if i < n_equities:
            positions.append({"instrumentId": iid, "quantity": 10, "avgCostLocal": 10000})
    doc = {
        "portfolio": {"portfolioId": "main", "name": "t", "baseCurrency": "KRW",
                      "riskLimits": {"maxWeightPerName": 0.15, "maxVar95": 0.03,
                                     "maxSectorWeight": 0.30, "maxHoldings": max_holdings}},
        "positions": positions,
    }
    (tmp_path / "writeback" / "portfolio.json").write_text(json.dumps(doc), encoding="utf-8")
    s = OntologyStore(data_dir=tmp_path)
    s.replace_objects("source", "Instrument", instruments)
    s.replace_objects("source", "Sector", [
        {"sectorId": "IT", "name": "IT", "nameKo": "정보기술"},
        {"sectorId": "FIN", "name": "Fin", "nameKo": "금융"},
        {"sectorId": "BROAD", "name": "Broad", "nameKo": "시장지수"},
    ])
    s.replace_links("source", "instrumentInSector", [
        LinkRecord("instrumentInSector", "Instrument", i["instrumentId"], "Sector", i["sectorId"])
        for i in instruments
    ])
    return s.build()


# ── 시나리오 1: 지수는 매매할 수 없다 ─────────────────────────────

def test_index_cannot_be_traded(tmp_path):
    store = make_store(tmp_path)
    r = ActionEngine(store, actor="t").submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:069500",
        "quantity": 10, "avgCostLocal": 30000})
    assert r["ok"] is False
    assert any("지수" in f for f in r["failures"])


def test_index_cannot_be_in_proposal(tmp_path):
    store = make_store(tmp_path)
    r = ActionEngine(store, actor="t").submit("proposeRebalance", {
        "portfolioId": "main", "title": "t",
        "legs": [{"instrumentId": "KRX:069500", "side": "BUY", "targetWeightDelta": 0.02}],
        "rationale": "지수 매수는 차단되어야 한다는 시나리오 테스트"})
    assert r["ok"] is False
    assert any("지수" in f for f in r["failures"])


# ── 시나리오 2: 개별주 15종목 한도 ────────────────────────────────

def test_holdings_cap_blocks_16th_equity(tmp_path):
    store = make_store(tmp_path, n_equities=15, max_holdings=15)
    engine = ActionEngine(store, actor="t")
    r = engine.submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:000015",
        "quantity": 10, "avgCostLocal": 10000})
    assert r["ok"] is False
    assert any("보유 한도" in f for f in r["failures"])
    # 기존 보유 수량 변경은 허용
    r2 = engine.submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:000001", "quantity": 20})
    assert r2["ok"] is True


def test_etf_not_counted_in_holdings_cap(tmp_path):
    store = make_store(tmp_path, n_equities=15, max_holdings=15)
    r = ActionEngine(store, actor="t").submit("editPosition", {
        "portfolioId": "main", "instrumentId": "ARCA:SPY", "quantity": 9})
    assert r["ok"] is True


def test_proposal_new_entry_respects_cap(tmp_path):
    from ontoquant.core.action_functions import legs_within_holdings_limit
    store = make_store(tmp_path, n_equities=15, max_holdings=15)
    assert legs_within_holdings_limit(store, [
        {"instrumentId": "KRX:000015", "targetWeightDelta": 0.02}]) is False
    assert legs_within_holdings_limit(store, [
        {"instrumentId": "KRX:000001", "targetWeightDelta": 0.02}]) is True   # 기보유
    store2 = make_store(tmp_path / "b", n_equities=14, max_holdings=15)
    assert legs_within_holdings_limit(store2, [
        {"instrumentId": "KRX:000015", "targetWeightDelta": 0.02}]) is True   # 여유 1


# ── 시나리오 3: 섹터 쏠림 → 인사이트 + 권장 대응 ──────────────────

def test_sector_concentration_fires_with_action(tmp_path):
    from ontoquant.insights.sector_rules import sector_concentration
    store = make_store(tmp_path, n_equities=4)
    store.replace_objects("computed", "Position", [
        {"positionId": "main:KRX:000000", "portfolioId": "main",
         "instrumentId": "KRX:000000", "weight": 0.25},
        {"positionId": "main:KRX:000002", "portfolioId": "main",
         "instrumentId": "KRX:000002", "weight": 0.15},   # IT 합계 40% > 30%
        {"positionId": "main:KRX:000001", "portfolioId": "main",
         "instrumentId": "KRX:000001", "weight": 0.10},
    ])
    store = OntologyStore(data_dir=store.data_dir).build()
    insights, links = sector_concentration(store, "2026-07-03")
    assert len(insights) == 1
    ins = insights[0]
    assert ins["sectorId"] == "IT" and ins["validationStatus"] == "VALIDATED"
    legs = ins["recommendedAction"]["paramsPreset"]["legs"]
    assert all(l["side"] == "SELL" for l in legs)
    assert abs(sum(l["targetWeightDelta"] for l in legs) + 0.10) < 0.01  # 초과분 10%p 감축


# ── 시나리오 4: 변동성 급등 → 현금 확보 인사이트 ──────────────────

def test_vol_spike_triggers_cash_allocation(tmp_path):
    from ontoquant.insights.sector_rules import cash_allocation
    store = make_store(tmp_path)
    store.append_object("source", "MacroEvent", {
        "eventId": "macro:VIXCLS:test", "eventType": "VOL_SPIKE",
        "occurredAt": (NOW - timedelta(days=1)).isoformat(timespec="seconds"),
        "title": "변동성 급등", "seriesId": "VIXCLS", "value": 40.0, "zScore": 3.1,
        "severity": 0.8,
    })
    store.replace_objects("computed", "RiskMetric", [
        {"metricId": "POSITION:main:KRX:000000:CONTRIB_VAR", "scopeType": "POSITION",
         "scopeId": "main:KRX:000000", "metricType": "CONTRIB_VAR",
         "value": 0.01, "asOfDate": "2026-07-03"},
    ])
    store = OntologyStore(data_dir=store.data_dir).build()
    insights, links = cash_allocation(store, "2026-07-03")
    assert len(insights) == 1
    assert insights[0]["insightType"] == "CASH_ALLOCATION"
    assert "현금" in insights[0]["recommendedAction"]["label"]
    assert any(l.linkType == "insightFromEvent" for l in links)


# ── 시나리오 5: 부정 뉴스 흐름 → 확인 권고 (미검증 배지) ──────────

def test_negative_news_flow_fires_sentiment_shift(tmp_path):
    from ontoquant.insights.sector_rules import news_sentiment_shift
    store = make_store(tmp_path)
    store.replace_objects("computed", "Position", [
        {"positionId": "main:KRX:000000", "portfolioId": "main",
         "instrumentId": "KRX:000000", "weight": 0.2},
    ])
    store = OntologyStore(data_dir=store.data_dir).build()
    for i in range(3):
        eid = f"naver:test{i}"
        store.append_object("source", "NewsEvent", {
            "eventId": eid, "eventType": "NEWS",
            "occurredAt": (NOW - timedelta(days=i)).isoformat(timespec="seconds"),
            "title": f"악재 {i}", "feedSource": "NAVER_NEWS",
            "sentiment": -0.7, "sentimentLabel": "NEGATIVE", "severity": 0.5,
        })
        store.append_link("source", LinkRecord(
            "eventAffectsInstrument", "NewsEvent", eid, "Instrument", "KRX:000000",
            {"relevance": 0.9, "method": "DIRECT"}))
    insights, _ = news_sentiment_shift(store, "2026-07-03")
    assert len(insights) == 1
    assert insights[0]["validationStatus"] == "UNVALIDATED"
    assert "부정" in insights[0]["title"] or "부정" in insights[0]["narrative"]
