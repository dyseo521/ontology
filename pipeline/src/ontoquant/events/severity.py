"""이벤트 심각도 (0~1) — 타입 가중치 기반, Phase 3에서 과거 CAR 크기로 보정."""
from __future__ import annotations

TYPE_WEIGHTS: dict[str, float] = {
    "DEFAULT": 1.0, "BUSINESS_HALT": 0.95, "RESTATEMENT": 0.9,
    "CAPITAL_INCREASE": 0.85, "MERGER": 0.8, "ACQUISITION": 0.75, "SPINOFF": 0.7,
    "EARNINGS": 0.7, "CONVERTIBLE_BOND": 0.65, "BUYBACK": 0.6,
    "BUYBACK_DISPOSAL": 0.55, "SUPPLY_CONTRACT": 0.55, "LITIGATION": 0.55,
    "DIVIDEND": 0.45, "MAJOR_HOLDINGS": 0.45, "EXEC_CHANGE": 0.4,
    "MATERIAL_AGREEMENT": 0.45, "INSIDER_OWNERSHIP": 0.35,
    "GOVERNANCE": 0.3, "LISTING_NOTICE": 0.5, "OTHER_EVENTS": 0.3,
    "ANALYST_RATING": 0.35, "PRODUCT_LAUNCH": 0.4,
    "PERIODIC_REPORT": 0.15, "REG_FD": 0.2, "DISCLOSURE_OTHER": 0.2, "NEWS": 0.25,
}


def base_severity(event_type: str) -> float:
    return TYPE_WEIGHTS.get(event_type, 0.25)


def macro_severity(z_score: float) -> float:
    return min(1.0, abs(z_score) / 4.0)


def adjust_with_car(base: float, car_mean_abs: float | None,
                    n: int = 0, min_n: int = 10) -> float:
    """과거 동일 타입 CAR 평균 절대값으로 보정 — PIT 통계 기준(누출 방지).
    표본 부족(n < min_n)이면 근거 없음으로 보고 base 유지."""
    if car_mean_abs is None or n < min_n:
        return base
    return round(min(1.0, base * (0.6 + min(car_mean_abs / 0.03, 1.4))), 3)
