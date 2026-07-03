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
    {
        "modelVersionId": "signal-model@1.0.0",
        "modelId": "signal-model",
        "version": "1.0.0",
        "stage": "ARCHIVED",
        "params": {"windowBd": 5, "newsKappa": 0.01},
        "description": "[감사 실패로 보관] v1 — 유형 평균 CAR(동시대 반응)을 예측자로 오용, IC≈0",
    },
    {
        "modelVersionId": "signal-model@2.0.0",
        "modelId": "signal-model",
        "version": "2.0.0",
        "stage": "STAGING",
        "params": {"alphas": "PEAD-SUE/EAR·insider(BUY,기회적)·news(fresh+/stale−)·reversal·momentum·flags",
                   "combine": "shrunk-IC z-가중 (λ=0.5)", "horizons": [5, 20, 60],
                   "citations": "Bernard-Thomas89, Brandt08, CMP12, Tetlock07-11, Jegadeesh90, JT93, Grinold-Kahn"},
        "description": "문헌 검증 알파 결합 — 표류(drift)만 신호로, 반응(reaction) 사용 금지",
    },
]

# v3: 개별 주식 최대 15종목(maxHoldings, ETF 제외). 코스피 지수(069500)는 거래 불가라
# 포트폴리오에서 제외. 삼성전자/SK하이닉스는 비보유(매수 후보로는 가능).
# 비보유 tradable 종목들이 '폭넓은 제안'의 신규 편입 후보 풀이 된다.
DEFAULT_PORTFOLIO = {
    "portfolio": {
        "portfolioId": "main",
        "name": "KR+US 섹터 분산 포트폴리오",
        "baseCurrency": "KRW",
        "benchmark": "ARCA:SPY",
        "riskLimits": {"maxWeightPerName": 0.15, "maxVar95": 0.03,
                       "maxSectorWeight": 0.30, "maxHoldings": 15},
    },
    "positions": [
        # ── KR 개별주 9 ──
        {"instrumentId": "KRX:035420", "quantity": 40, "avgCostLocal": 196000, "openedAt": "2025-02-14"},
        {"instrumentId": "KRX:035720", "quantity": 100, "avgCostLocal": 47500, "openedAt": "2025-04-08"},
        {"instrumentId": "KRX:005380", "quantity": 30, "avgCostLocal": 232000, "openedAt": "2025-06-20"},
        {"instrumentId": "KRX:068270", "quantity": 30, "avgCostLocal": 176000, "openedAt": "2025-07-11"},
        {"instrumentId": "KRX:105560", "quantity": 100, "avgCostLocal": None, "openedAt": "2026-07-03"},
        {"instrumentId": "KRX:005490", "quantity": 25, "avgCostLocal": None, "openedAt": "2026-07-03"},
        {"instrumentId": "KRX:096770", "quantity": 60, "avgCostLocal": None, "openedAt": "2026-07-03"},
        {"instrumentId": "KRX:015760", "quantity": 250, "avgCostLocal": None, "openedAt": "2026-07-03"},
        {"instrumentId": "KRX:271560", "quantity": 60, "avgCostLocal": None, "openedAt": "2026-07-03"},
        # ── US 개별주 6 ──
        {"instrumentId": "XNAS:AAPL", "quantity": 20, "avgCostLocal": 186.5, "openedAt": "2025-02-03"},
        {"instrumentId": "XNAS:MSFT", "quantity": 10, "avgCostLocal": 392.0, "openedAt": "2025-03-17"},
        {"instrumentId": "XNAS:NVDA", "quantity": 15, "avgCostLocal": 114.0, "openedAt": "2025-05-27"},
        {"instrumentId": "XNAS:GOOGL", "quantity": 15, "avgCostLocal": 161.0, "openedAt": "2025-04-21"},
        {"instrumentId": "XNYS:JPM", "quantity": 12, "avgCostLocal": 197.5, "openedAt": "2025-01-27"},
        {"instrumentId": "XNYS:JNJ", "quantity": 15, "avgCostLocal": None, "openedAt": "2026-07-03"},
        # ── 지수 ETF (maxHoldings 미포함) ──
        {"instrumentId": "ARCA:SPY", "quantity": 10, "avgCostLocal": 522.0, "openedAt": "2025-01-06"},
        {"instrumentId": "XNAS:QQQ", "quantity": 8, "avgCostLocal": 448.0, "openedAt": "2025-02-24"},
    ],
}


def run(force_portfolio: bool = False) -> None:
    universe = yaml.safe_load((config.REFERENCE_DIR / "universe.yaml").read_text(encoding="utf-8"))
    store = OntologyStore()

    store.replace_objects("source", "Sector", universe.get("sectors", []))
    for inst in universe["instruments"]:
        inst.setdefault("tradable", True)  # 명시 없으면 매매 가능
    store.replace_objects("source", "Instrument", universe["instruments"])
    store.replace_objects("source", "Factor", universe["factors"])
    from ontoquant.core.store import LinkRecord
    sector_links = [
        LinkRecord("instrumentInSector", "Instrument", inst["instrumentId"],
                   "Sector", inst["sectorId"])
        for inst in universe["instruments"] if inst.get("sectorId")
    ]
    store.replace_links("source", "instrumentInSector", sector_links)
    print(f"seed: Sector {len(universe.get('sectors', []))}건, "
          f"Instrument {len(universe['instruments'])}건, Factor {len(universe['factors'])}건")

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


def set_position_costs() -> int:
    """avgCostLocal 이 null 인 포지션에 최근 종가를 취득단가로 기록 (신규 편입 가정).
    가격 백필 후 1회 실행: python -c "from ontoquant import seed; seed.set_position_costs()"
    """
    import json as _json

    from ontoquant.compute.returns import load_close

    pf_path = config.WRITEBACK_DIR / "portfolio.json"
    doc = _json.loads(pf_path.read_text(encoding="utf-8"))
    filled = 0
    for pos in doc.get("positions", []):
        if pos.get("avgCostLocal") is None:
            close = load_close(pos["instrumentId"], prefer_adj=False)
            if close is not None and len(close):
                pos["avgCostLocal"] = round(float(close.iloc[-1]), 2)
                filled += 1
    if filled:
        pf_path.write_text(_json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"seed: 취득단가 {filled}건 채움")
    return filled


if __name__ == "__main__":
    run()
