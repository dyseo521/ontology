"""TRADE_SIGNAL 인사이트 — 오늘의 강한 매수/매도 신호를 확신도와 함께 표면화.

발화 조건: conviction >= 0.5 그리고 (강도 백분위 >= 0.9 또는 '가장 강함' 표기 존재).
최대 3건 (신호 희석 방지). 검증 배지는 근거 비율로:
  evidenceShare >= 0.5 → VALIDATED (검증된 유형이 근거의 절반 이상)
  아니면 UNVALIDATED.
결과론 방지: 신호·확신도 전부 PIT (signals/engine 참조).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ontoquant import config
from ontoquant.core.store import LinkRecord, OntologyStore

CONVICTION_MIN = 0.5
STRENGTH_MIN = 0.9
MAX_SIGNAL_INSIGHTS = 3
STEP = 0.02


def build(store: OntologyStore, as_of: str) -> tuple[list[dict], list[LinkRecord]]:
    board_path = config.COMPUTED_DIR / "signals_today.json"
    if not board_path.exists():
        return [], []
    doc = json.loads(board_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    event_types = store.schema.interfaces["Event"].implementedBy
    # 신호 체계 자체가 감사(IC 유의성)를 통과했는가 — 통과 전엔 어떤 신호도 VALIDATED 불가
    audits = doc.get("audit") or {}
    system_validated = any(
        a and (a.get("meanIC") or 0) > 0 and (a.get("icTstat") or 0) >= 2.0
        for a in audits.values()
    )

    insights, links = [], []
    picked = 0
    for row in doc.get("board", []):
        if picked >= MAX_SIGNAL_INSIGHTS:
            break
        if not row.get("tradable"):
            continue
        if (row.get("conviction") or 0) < CONVICTION_MIN:
            continue
        if (row.get("strength") or 0) < STRENGTH_MIN and not row.get("strengthNote"):
            continue
        picked += 1
        is_buy = row["direction"] == "BUY"
        side_ko = "매수" if is_buy else "매도"
        label = f"{row['name']}({row['ticker']})"
        note = row.get("strengthNote") or f"과거 대비 상위 {(1 - row['strength']) * 100:.0f}%"
        validated = system_validated and (row.get("evidenceShare") or 0) >= 0.5
        held = row.get("held")
        action = None
        if is_buy or held:  # 비보유 종목의 매도 신호는 대응 액션 없음 (정보만)
            action = {
                "label": f"{label} {side_ko} {STEP * 100:.0f}%p 검토",
                "actionApiName": "proposeRebalance",
                "paramsPreset": {
                    "title": f"{label} {side_ko} 신호 대응",
                    "legs": [{"instrumentId": row["instrumentId"],
                              "side": "BUY" if is_buy else "SELL",
                              "targetWeightDelta": STEP if is_buy else -STEP,
                              "reason": f"온톨로지 신호 ({note})"}],
                    "rationale": (f"{label} 에 {note} 수준의 {side_ko} 신호. "
                                  f"확신도 {row['conviction']:.2f}, 근거 중 검증 유형 "
                                  f"{row['evidenceShare'] * 100:.0f}%."),
                },
            }
        iid_ins = f"ins_signal_{row['instrumentId'].replace(':', '_')}_{as_of}"
        insights.append({
            "insightId": iid_ins, "insightType": "TRADE_SIGNAL",
            "title": f"{side_ko} 신호: {label} · {note}",
            "narrative": (f"최근 5영업일 이벤트들이 {label} 에 "
                          f"{'긍정' if is_buy else '부정'} 방향으로 모였습니다 "
                          f"(5일 기대 효과 {row['expected5d']:+.1f}%). "
                          f"확신도 {row['conviction']:.2f}: 과거 대비 강도 "
                          f"{row['strength'] * 100:.0f}점, 검증된 유형 근거 "
                          f"{row['evidenceShare'] * 100:.0f}%."
                          + ("" if row.get("held") or not is_buy else " 현재 비보유 종목입니다.")),
            "severity": round(min(1.0, abs(row["signal"]) * 30), 3),
            "confidence": row["conviction"],
            "validationStatus": "VALIDATED" if validated else "UNVALIDATED",
            "validationSummary": ("근거의 " + f"{row['evidenceShare'] * 100:.0f}% 가 통계 검증된 유형"
                                  if validated else
                                  ("신호 체계의 예측력이 아직 감사를 통과하지 못함"
                                   if not system_validated else "검증된 유형 근거 부족")),
            "recommendedAction": action,
            "createdAt": now, "asOfDate": as_of,
        })
        links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins,
                                "Instrument", row["instrumentId"]))
        for ev in row.get("evidence", [])[:3]:
            etype_obj = store.get_type_of(ev["eventId"], event_types)
            if etype_obj:
                links.append(LinkRecord("insightFromEvent", "Insight", iid_ins,
                                        etype_obj, ev["eventId"]))
    return insights, links
