"""TRADE_SIGNAL 인사이트 — v2 보드(알파 근거)를 확신도와 함께 표면화.

발화: conviction >= 0.5 그리고 (강도 백분위 >= 0.9 또는 '가장 강함' 표기).
최대 3건. 검증 배지 이중 게이트:
  ① 신호 체계(결합 IC NW-t >= 2, 어느 지평이든)가 감사를 통과했고
  ② 이 신호 근거의 절반 이상이 검증된 알파일 때만 VALIDATED.
현재 체계가 미통과면 전부 UNVALIDATED (정직 우선).
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
        reasons = ", ".join(
            f"{e['label']}{'(검증됨)' if e.get('validated') else ''}"
            for e in row.get("evidence", []))
        action = None
        if is_buy or held:  # 비보유 종목의 매도 신호는 정보만
            action = {
                "label": f"{label} {side_ko} {STEP * 100:.0f}%p 검토",
                "actionApiName": "proposeRebalance",
                "paramsPreset": {
                    "title": f"{label} {side_ko} 신호 대응",
                    "legs": [{"instrumentId": row["instrumentId"],
                              "side": "BUY" if is_buy else "SELL",
                              "targetWeightDelta": STEP if is_buy else -STEP,
                              "reason": f"신호 근거: {reasons} ({note})"}],
                    "rationale": (f"{label} 에 {note} 수준의 {side_ko} 신호. "
                                  f"근거: {reasons}. 확신도 {row['conviction']:.2f}."),
                },
            }
        iid_ins = f"ins_signal_{row['instrumentId'].replace(':', '_')}_{as_of}"
        insights.append({
            "insightId": iid_ins, "insightType": "TRADE_SIGNAL",
            "title": f"{side_ko} 신호: {label}" + (f" · {note}" if note else ""),
            "narrative": (f"근거가 {label} 에 {'긍정' if is_buy else '부정'} 방향으로 "
                          f"모였습니다: {reasons}. 확신도 {row['conviction']:.2f} "
                          f"(과거 대비 강도 {row['strength'] * 100:.0f}점, "
                          f"검증된 근거 {row['evidenceShare'] * 100:.0f}%, "
                          f"근거 방향 일치 {row.get('agreement', 0) * 100:.0f}%)."
                          + ("" if held or not is_buy else " 현재 비보유 종목입니다.")),
            "severity": round(min(1.0, abs(row["signal"]) / 2), 3),
            "confidence": row["conviction"],
            "validationStatus": "VALIDATED" if validated else "UNVALIDATED",
            "validationSummary": ("체계 감사 통과 + 근거 과반이 검증된 알파" if validated else
                                  ("신호 체계의 예측력이 아직 감사를 통과하지 못함"
                                   if not system_validated else "검증된 알파 근거 부족")),
            "recommendedAction": action,
            "createdAt": now, "asOfDate": as_of,
        })
        links.append(LinkRecord("insightAboutInstrument", "Insight", iid_ins,
                                "Instrument", row["instrumentId"]))
    return insights, links
