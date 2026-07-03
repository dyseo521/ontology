import json

import pytest

from ontoquant.core.store import LinkRecord, OntologyStore

INSTRUMENTS = [
    {"instrumentId": "KRX:005930", "ticker": "005930", "name": "Samsung Electronics",
     "market": "KRX", "currency": "KRW", "assetClass": "EQUITY", "priceSource": "NAVER"},
    {"instrumentId": "XNAS:AAPL", "ticker": "AAPL", "name": "Apple Inc.",
     "market": "XNAS", "currency": "USD", "assetClass": "EQUITY", "priceSource": "TIINGO"},
]

PORTFOLIO_DOC = {
    "portfolio": {"portfolioId": "main", "name": "테스트", "baseCurrency": "KRW",
                  "riskLimits": {"maxWeightPerName": 0.2, "maxVar95": 0.03, "maxSectorWeight": 0.4}},
    "positions": [
        {"instrumentId": "KRX:005930", "quantity": 10, "avgCostLocal": 70000},
        {"instrumentId": "XNAS:AAPL", "quantity": 5, "avgCostLocal": 180.0},
    ],
}


@pytest.fixture
def store(tmp_path):
    (tmp_path / "writeback").mkdir(parents=True)
    (tmp_path / "writeback" / "portfolio.json").write_text(
        json.dumps(PORTFOLIO_DOC, ensure_ascii=False), encoding="utf-8")
    s = OntologyStore(data_dir=tmp_path)
    s.replace_objects("source", "Instrument", INSTRUMENTS)
    return s.build()


def test_portfolio_adapter(store):
    pf = store.get("Portfolio", "main")
    assert pf["baseCurrency"] == "KRW"
    positions = store.query("Position", where={"portfolioId": "main"})
    assert len(positions) == 2
    nbs = store.neighbors("Portfolio", "main", link_type="portfolioPositions")
    assert {n.pk for n in nbs} == {"main:KRX:005930", "main:XNAS:AAPL"}


def test_layer_merge_property_level(store):
    # computed 계층은 PIPELINE 소유 속성(weight 등)만 기록 — writeback 의 quantity 와 속성 단위 병합
    store.replace_objects("computed", "Position", [
        {"positionId": "main:KRX:005930", "portfolioId": "main",
         "instrumentId": "KRX:005930", "weight": 0.55, "marketValueBase": 700000.0},
    ])
    merged = OntologyStore(data_dir=store.data_dir).build().get("Position", "main:KRX:005930")
    assert merged["quantity"] == 10        # writeback 이 계속 소유
    assert merged["weight"] == 0.55        # computed 가 채움


def test_ownership_enforced(store):
    with pytest.raises(PermissionError):
        store.append_object("computed", "Position", {
            "positionId": "main:KRX:005930", "portfolioId": "main",
            "instrumentId": "KRX:005930", "quantity": 999, "avgCostLocal": 1,
        })
    with pytest.raises(PermissionError):
        store.append_object("writeback", "Position", {
            "positionId": "main:KRX:005930", "portfolioId": "main",
            "instrumentId": "KRX:005930", "weight": 0.9,
        })


def test_event_traversal_to_portfolio(store):
    store.append_object("source", "DisclosureEvent", {
        "eventId": "dart:test1", "eventType": "CAPITAL_INCREASE",
        "occurredAt": "2026-07-01T09:00:00+09:00", "title": "유상증자 결정",
        "market": "KR",
    })
    store.append_link("source", LinkRecord(
        "eventAffectsInstrument", "DisclosureEvent", "dart:test1",
        "Instrument", "KRX:005930", {"relevance": 1.0, "method": "DIRECT"}))

    paths = store.traverse(
        "DisclosureEvent", "dart:test1",
        ["eventAffectsInstrument", "<positionInstrument", "<portfolioPositions"])
    assert len(paths) == 1
    assert [nb.pk for nb in paths[0]] == ["KRX:005930", "main:KRX:005930", "main"]
    # 인터페이스 질의: Event 로 조회해도 잡혀야 함
    assert store.count("Event") == 1


def test_enum_validation(store):
    with pytest.raises(ValueError):
        store.append_object("source", "Instrument", {
            "instrumentId": "X:1", "ticker": "1", "name": "bad",
            "market": "INVALID", "currency": "KRW", "assetClass": "EQUITY",
            "priceSource": "NAVER"})


def test_tombstone_delete(tmp_path):
    (tmp_path / "writeback").mkdir(parents=True)
    s = OntologyStore(data_dir=tmp_path)
    s.replace_objects("source", "Instrument", INSTRUMENTS)
    s.build()
    s.delete_object("source", "Instrument", "X:1")  # 없는 pk 삭제 = no-op
    s.append_object("source", "Instrument", {
        "instrumentId": "X:2", "ticker": "2", "name": "temp", "market": "KRX",
        "currency": "KRW", "assetClass": "EQUITY", "priceSource": "NAVER"})
    s.delete_object("source", "Instrument", "X:2")
    rebuilt = OntologyStore(data_dir=tmp_path).build()
    assert rebuilt.get("Instrument", "X:2") is None
    assert rebuilt.count("Instrument") == 2
