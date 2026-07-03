"""시드 — universe.yaml → Instrument/Factor 오브젝트, portfolio.json, 초기 ModelVersion.

idempotent: source 계층은 스냅샷 교체, portfolio.json 은 없을 때만 생성 (사용자 편집 보호).
실행: python -m ontoquant.seed
"""
from __future__ import annotations

import json

import yaml

from ontoquant import config
from ontoquant.core.audit import now_iso
from ontoquant.core.store import OntologyStore

INITIAL_MODEL_VERSIONS = [
    {
        "modelVersionId": "factor-model@1.0.0",
        "modelId": "factor-model",
        "version": "1.0.0",
        "stage": "PRODUCTION",
        "params": {"window": 252, "minObs": 120, "hacLags": 5,
                   "groups": ["US_STYLE", "US_MACRO", "KR_CORE"]},
        "description": "롤링 OLS 팩터 모델 (분리 회귀: US 스타일 / US 매크로 / KR 코어)",
    },
    {
        "modelVersionId": "event-classifier@1.0.0",
        "modelId": "event-classifier",
        "version": "1.0.0",
        "stage": "PRODUCTION",
        "params": {"embedModel": "intfloat/multilingual-e5-small", "linkThreshold": 0.55},
        "description": "규칙(공시유형/8-K item) 1차 + 임베딩 센트로이드 2차 분류",
    },
    {
        "modelVersionId": "rebalance-strategy@1.0.0",
        "modelId": "rebalance-strategy",
        "version": "1.0.0",
        "stage": "STAGING",
        "params": {"severityMin": 0.7, "carMax": -0.01, "weightStep": 0.02,
                   "costBpKr": 10, "costBpUs": 5},
        "description": "이벤트 기반 감축 규칙 — 게이트 2회 통과 후 PRODUCTION 승격 대상",
    },
]

DEFAULT_PORTFOLIO = {
    "portfolio": {
        "portfolioId": "main",
        "name": "샘플 KR+US 혼합 포트폴리오",
        "baseCurrency": "KRW",
        "benchmark": "ARCA:SPY",
        "riskLimits": {"maxWeightPerName": 0.20, "maxVar95": 0.03, "maxSectorWeight": 0.45},
    },
    "positions": [
        {"instrumentId": "KRX:005930", "quantity": 300, "avgCostLocal": 72000, "openedAt": "2025-03-10"},
        {"instrumentId": "KRX:000660", "quantity": 30, "avgCostLocal": 178000, "openedAt": "2025-05-02"},
        {"instrumentId": "KRX:035420", "quantity": 40, "avgCostLocal": 196000, "openedAt": "2025-02-14"},
        {"instrumentId": "KRX:005380", "quantity": 30, "avgCostLocal": 232000, "openedAt": "2025-06-20"},
        {"instrumentId": "KRX:035720", "quantity": 100, "avgCostLocal": 47500, "openedAt": "2025-04-08"},
        {"instrumentId": "KRX:068270", "quantity": 30, "avgCostLocal": 176000, "openedAt": "2025-07-11"},
        {"instrumentId": "KRX:069500", "quantity": 200, "avgCostLocal": 35800, "openedAt": "2025-01-06"},
        {"instrumentId": "XNAS:AAPL", "quantity": 30, "avgCostLocal": 186.5, "openedAt": "2025-02-03"},
        {"instrumentId": "XNAS:MSFT", "quantity": 15, "avgCostLocal": 392.0, "openedAt": "2025-03-17"},
        {"instrumentId": "XNAS:NVDA", "quantity": 24, "avgCostLocal": 114.0, "openedAt": "2025-05-27"},
        {"instrumentId": "XNAS:GOOGL", "quantity": 20, "avgCostLocal": 161.0, "openedAt": "2025-04-21"},
        {"instrumentId": "XNAS:TSLA", "quantity": 12, "avgCostLocal": 228.0, "openedAt": "2025-06-09"},
        {"instrumentId": "XNYS:JPM", "quantity": 15, "avgCostLocal": 197.5, "openedAt": "2025-01-27"},
        {"instrumentId": "ARCA:SPY", "quantity": 10, "avgCostLocal": 522.0, "openedAt": "2025-01-06"},
        {"instrumentId": "XNAS:QQQ", "quantity": 10, "avgCostLocal": 448.0, "openedAt": "2025-02-24"},
    ],
}


def run(force_portfolio: bool = False) -> None:
    universe = yaml.safe_load((config.REFERENCE_DIR / "universe.yaml").read_text(encoding="utf-8"))
    store = OntologyStore()

    store.replace_objects("source", "Instrument", universe["instruments"])
    store.replace_objects("source", "Factor", universe["factors"])
    print(f"seed: Instrument {len(universe['instruments'])}건, Factor {len(universe['factors'])}건")

    # ModelVersion 은 이력이므로 없는 것만 추가
    store.build()
    existing = {m["modelVersionId"] for m in store.query("ModelVersion")}
    for mv in INITIAL_MODEL_VERSIONS:
        if mv["modelVersionId"] not in existing:
            store.append_object("computed", "ModelVersion", {**mv, "createdAt": now_iso()})
            print(f"seed: ModelVersion {mv['modelVersionId']} ({mv['stage']})")

    pf_path = config.WRITEBACK_DIR / "portfolio.json"
    if force_portfolio or not pf_path.exists():
        pf_path.parent.mkdir(parents=True, exist_ok=True)
        pf_path.write_text(json.dumps(DEFAULT_PORTFOLIO, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"seed: portfolio.json 생성 (포지션 {len(DEFAULT_PORTFOLIO['positions'])}건)")
    else:
        print("seed: portfolio.json 존재 — 건너뜀")


if __name__ == "__main__":
    run()
