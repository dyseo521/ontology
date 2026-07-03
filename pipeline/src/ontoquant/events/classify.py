"""이벤트 분류 — 1차: 결정적 규칙 (DART report_nm / 8-K item), 2차: 임베딩 센트로이드.

eventType 세분류는 이벤트 스터디(Phase 3)의 집계 키가 되므로 안정적이어야 한다.
"""
from __future__ import annotations

import re

# DART report_nm 키워드 → eventType (순서 중요: 먼저 매칭되는 것 우선)
DART_RULES: list[tuple[str, str]] = [
    ("무상증자", "BONUS_ISSUE"),
    ("유상증자", "CAPITAL_INCREASE"),
    ("자기주식취득", "BUYBACK"),
    ("자기주식 취득", "BUYBACK"),
    ("자사주", "BUYBACK"),
    ("자기주식처분", "BUYBACK_DISPOSAL"),
    ("합병", "MERGER"),
    ("분할", "SPINOFF"),
    ("전환사채", "CONVERTIBLE_BOND"),
    ("신주인수권", "CONVERTIBLE_BOND"),
    ("공급계약", "SUPPLY_CONTRACT"),
    ("단일판매", "SUPPLY_CONTRACT"),
    ("소송", "LITIGATION"),
    ("영업정지", "BUSINESS_HALT"),
    ("부도", "DEFAULT"),
    ("영업(잠정)실적", "EARNINGS"),
    ("잠정실적", "EARNINGS"),
    ("실적공시", "EARNINGS"),
    ("연결재무제표기준영업", "EARNINGS"),
    ("배당", "DIVIDEND"),
    ("주식등의대량보유", "MAJOR_HOLDINGS"),
    ("임원ㆍ주요주주", "INSIDER_OWNERSHIP"),
    ("사업보고서", "PERIODIC_REPORT"),
    ("반기보고서", "PERIODIC_REPORT"),
    ("분기보고서", "PERIODIC_REPORT"),
    ("증권발행실적", "PERIODIC_REPORT"),
]

# 8-K item 코드 → eventType
EDGAR_ITEM_RULES: dict[str, str] = {
    "2.02": "EARNINGS",
    "1.01": "MATERIAL_AGREEMENT",
    "2.01": "ACQUISITION",
    "5.02": "EXEC_CHANGE",
    "5.03": "GOVERNANCE",
    "7.01": "REG_FD",
    "8.01": "OTHER_EVENTS",
    "3.01": "LISTING_NOTICE",
    "4.02": "RESTATEMENT",
}

# 이벤트 스터디에서 "가격에 유의미" 후보로 보는 타입 (우선 링크/전파 대상)
PRICE_RELEVANT = {
    "CAPITAL_INCREASE", "BONUS_ISSUE", "BUYBACK", "BUYBACK_DISPOSAL", "MERGER",
    "SPINOFF", "CONVERTIBLE_BOND", "SUPPLY_CONTRACT", "EARNINGS", "DIVIDEND",
    "ACQUISITION", "RESTATEMENT", "DEFAULT", "BUSINESS_HALT", "MAJOR_HOLDINGS",
}


def classify_dart(report_nm: str) -> str:
    for kw, etype in DART_RULES:
        if kw in report_nm:
            return etype
    return "DISCLOSURE_OTHER"


def extract_8k_items(text: str) -> list[str]:
    return re.findall(r"Item\s+(\d+\.\d+)", text or "")


def classify_edgar(form_type: str, summary: str) -> tuple[str, str | None]:
    """(eventType, item코드) 반환."""
    if form_type.startswith("10-"):
        return "PERIODIC_REPORT", None
    items = extract_8k_items(summary)
    for item in items:
        if item in EDGAR_ITEM_RULES and EDGAR_ITEM_RULES[item] != "REG_FD":
            return EDGAR_ITEM_RULES[item], item
    if items:
        return EDGAR_ITEM_RULES.get(items[0], "DISCLOSURE_OTHER"), items[0]
    return "DISCLOSURE_OTHER", None


# 뉴스용 임베딩 센트로이드 (2차 분류) — events/embed.py 의 인코더로 인코딩
NEWS_CENTROIDS: dict[str, str] = {
    "EARNINGS": "quarterly earnings results revenue profit beat miss guidance 실적 발표 영업이익",
    "ACQUISITION": "merger acquisition deal buyout takeover 인수 합병",
    "PRODUCT_LAUNCH": "new product launch unveil release announcement 신제품 출시",
    "LITIGATION": "lawsuit court ruling antitrust regulator fine 소송 규제 벌금",
    "EXEC_CHANGE": "CEO resign appoint executive leadership change 경영진 교체",
    "ANALYST_RATING": "analyst upgrade downgrade price target rating 목표주가",
}
NEWS_CENTROID_THRESHOLD = 0.82  # e5 코사인 기준 (미달 시 NEWS 유지)
