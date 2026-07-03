import json

import pytest

from ontoquant.core.actions import ActionEngine
from ontoquant.core.store import OntologyStore

INSTRUMENTS = [
    {"instrumentId": "KRX:005930", "ticker": "005930", "name": "Samsung Electronics",
     "market": "KRX", "currency": "KRW", "assetClass": "EQUITY", "priceSource": "NAVER"},
]

PORTFOLIO_DOC = {
    "portfolio": {"portfolioId": "main", "name": "테스트", "baseCurrency": "KRW",
                  "riskLimits": {"maxWeightPerName": 0.2, "maxVar95": 0.03, "maxSectorWeight": 0.4}},
    "positions": [{"instrumentId": "KRX:005930", "quantity": 10, "avgCostLocal": 70000}],
}


@pytest.fixture
def store(tmp_path):
    (tmp_path / "writeback").mkdir(parents=True)
    (tmp_path / "writeback" / "portfolio.json").write_text(
        json.dumps(PORTFOLIO_DOC, ensure_ascii=False), encoding="utf-8")
    s = OntologyStore(data_dir=tmp_path)
    s.replace_objects("source", "Instrument", INSTRUMENTS)
    return s.build()


def test_criteria_rejection_with_failure_message(store):
    engine = ActionEngine(store, actor="tester")
    result = engine.submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:005930", "quantity": -5})
    assert result["ok"] is False
    assert any("음수" in f for f in result["failures"])
    # 거부도 감사 로그에 남는다
    log = (store.data_dir / "writeback" / "action_log.jsonl").read_text()
    assert "REJECTED_CRITERIA" in log


def test_unknown_instrument_rejected(store):
    engine = ActionEngine(store, actor="tester")
    result = engine.submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:999999", "quantity": 5, "avgCostLocal": 1})
    assert result["ok"] is False
    assert any("유니버스" in f for f in result["failures"])


def test_edit_position_writeback(store):
    engine = ActionEngine(store, actor="tester")
    result = engine.submit("editPosition", {
        "portfolioId": "main", "instrumentId": "KRX:005930", "quantity": 25})
    assert result["ok"] is True
    doc = json.loads((store.data_dir / "writeback" / "portfolio.json").read_text())
    assert doc["positions"][0]["quantity"] == 25
    log_lines = [json.loads(l) for l in
                 (store.data_dir / "writeback" / "action_log.jsonl").read_text().splitlines()]
    assert log_lines[-1]["status"] == "SUBMITTED"
    assert log_lines[-1]["actor"] == "tester"


def test_new_position_requires_cost(store):
    engine = ActionEngine(store, actor="tester")
    store.append_object("source", "Instrument", {
        "instrumentId": "KRX:000660", "ticker": "000660", "name": "SK hynix",
        "market": "KRX", "currency": "KRW", "assetClass": "EQUITY", "priceSource": "NAVER"})
    with pytest.raises(ValueError, match="avgCostLocal"):
        engine.submit("editPosition", {
            "portfolioId": "main", "instrumentId": "KRX:000660", "quantity": 5})
    # 실패 시 portfolio.json 은 변경되지 않아야 한다 (스테이징 롤백)
    doc = json.loads((store.data_dir / "writeback" / "portfolio.json").read_text())
    assert len(doc["positions"]) == 1


def test_set_risk_limit(store):
    engine = ActionEngine(store, actor="tester")
    result = engine.submit("setRiskLimit", {
        "portfolioId": "main", "maxVar95": 0.05, "reason": "변동성 국면 조정"})
    assert result["ok"] is True
    doc = json.loads((store.data_dir / "writeback" / "portfolio.json").read_text())
    assert doc["portfolio"]["riskLimits"]["maxVar95"] == 0.05
    # 범위 밖 값은 거부
    bad = engine.submit("setRiskLimit", {"portfolioId": "main", "maxVar95": 0.9, "reason": "test"})
    assert bad["ok"] is False


def test_approve_requires_pending(store):
    engine = ActionEngine(store, actor="tester")
    store.append_object("writeback", "RebalanceProposal", {
        "proposalId": "prop_x", "title": "t", "status": "DRAFT",
        "rationale": "r" * 25, "createdAt": "2026-07-03T00:00:00+00:00",
        "createdBy": "tester", "asOfDate": "2026-07-03",
        "legs": [{"instrumentId": "KRX:005930", "side": "SELL", "targetWeightDelta": -0.02}],
    })
    result = engine.submit("approveProposal", {
        "proposalId": "prop_x", "decision": "APPROVE", "reason": "충분히 검토했습니다"})
    assert result["ok"] is False
    assert any("PENDING" in f for f in result["failures"])
