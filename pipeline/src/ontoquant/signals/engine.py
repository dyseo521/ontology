"""[DEPRECATED · 비교 참조용] v1 시그널. 신규 경로는 signals/audit_v2 (+alphas/combine).

감사 IC≈0 으로 signal-model@1.0.0 은 ARCHIVED. 실패 원인: 유형별 과거 평균 CAR 는
"발표 시점 시장이 이미 반영한 반응"이라 미래 예측자가 아니다 (notes/ 부검 참조).
PitStats 등 유틸은 v2 가 재사용하므로 파일 유지, 4주 병행 후 제거 예정.

온톨로지 매수/매도 시그널 — 명확한 공식, 전 구간 Point-in-Time.

시그널 (종목 i, 날짜 t — 단위: 5일 기대 초과수익률 근사):

  s_i(t) = Σ_{e ∈ E_i(t)}  relevance_e × severity_e × m_e(t) × decay(t − t_e)

  E_i(t)   : t−5영업일 ~ t 에 발생해 i 에 연결된 이벤트 (직접 링크 ρ≥0.9,
             섹터 경유는 ρ×0.5)
  m_e(t)   : 이벤트의 기대 효과.
             공시류 = 그 시점까지 알려진 동일 유형 PIT CAR 평균 (n≥10 일 때만, 아니면 0)
             뉴스   = κ_news(0.01) × sentiment  (감성 부호 × 사전 스케일)
  decay    : 1 − age/6  (발생일 1.0 → 5영업일 후 0.17)

확신도 (0~1):

  conviction = 0.6 × strength + 0.4 × evidenceShare
  strength      : |s_i(t)| 의 과거 3년(발화일만) 백분위 — "과거 대비 얼마나 큰가"
  evidenceShare : 기여분 중 '검증된 유형'(PIT 기준 n≥10, |tBmp|≥2) 비율 — "근거가 얼마나 단단한가"

직관 표기: weeksSinceStronger = 이보다 강한 신호가 마지막으로 있었던 시점까지의 주 수
  → "N주 만에 가장 강한 매도 신호". 히스토리 전체보다 크면 "관측 기간 내 최강".

결과론 방지: m_e, severity, 검증 판정 전부 t 시점 PIT. 미래 정보 없음.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ontoquant.core.store import OntologyStore

WINDOW_BD = 5
NEWS_KAPPA = 0.01          # 감성 1.0 ≈ 1% 기대 효과 (사전 고정 — 감사로 사후 평가)
SECTOR_DAMP = 0.5
MIN_N = 10
VALIDATED_T = 2.0
SIGNAL_FLOOR = 1e-5        # 이보다 작으면 무신호


@dataclass
class EventLite:
    """시그널 계산에 필요한 최소 필드 (히스토리 재구성 시 반복 조회 방지)."""
    eventId: str
    eventType: str
    market: str
    date: pd.Timestamp
    severity: float
    sentiment: float | None
    is_news: bool
    instruments: list[tuple[str, float]] = field(default_factory=list)  # (iid, relevance)


class PitStats:
    """(type, market) 별 knownAt 정렬 prefix — mean/scar 통계의 O(log n) PIT 조회."""

    def __init__(self, cars: pd.DataFrame | None):
        self._g: dict[tuple[str, str], dict] = {}
        if cars is None or cars.empty:
            return
        cars = cars.dropna(subset=["car"])  # EAR 만 확정된 반쪽 행 방어
        for (etype, market), g in cars.groupby(["eventType", "market"]):
            g = g.sort_values("knownAt")
            scar = g["scar"].to_numpy()
            self._g[(etype, market)] = {
                "known": g["knownAt"].to_numpy(),
                "car_cum": np.cumsum(g["car"].to_numpy()),
                "scar_cum": np.cumsum(scar),
                "scar2_cum": np.cumsum(scar * scar),
            }

    def stats(self, etype: str, market: str, as_of: pd.Timestamp) -> dict | None:
        g = self._g.get((etype, market))
        if g is None:
            return None
        n = int(np.searchsorted(g["known"], np.datetime64(as_of), side="right"))
        if n < MIN_N:
            return None
        mean_car = float(g["car_cum"][n - 1] / n)
        mean_scar = float(g["scar_cum"][n - 1] / n)
        var_scar = max(float(g["scar2_cum"][n - 1] / n) - mean_scar ** 2, 1e-12)
        t_stat = float(mean_scar / np.sqrt(var_scar / n))
        return {"n": n, "carMean": mean_car, "tBmp": t_stat,
                "validated": bool(abs(t_stat) >= VALIDATED_T)}


def collect_events(store: OntologyStore) -> list[EventLite]:
    """전체 이벤트를 시그널 계산용 경량 구조로 (링크 포함) 1회 로드."""
    event_types = store.schema.interfaces["Event"].implementedBy
    inst_sector = {r.fromPk: r.toPk for r in store.links("instrumentInSector")}
    sector_members: dict[str, list[str]] = defaultdict(list)
    for iid, sid in inst_sector.items():
        sector_members[sid].append(iid)

    direct: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in store.links("eventAffectsInstrument"):
        rel = float(r.props.get("relevance", 0.5))
        if rel >= 0.9:
            direct[r.fromPk].append((r.toPk, rel))
    via_sector: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in store.links("eventAffectsSector"):
        rel = float(r.props.get("relevance", 0.5)) * SECTOR_DAMP
        for iid in sector_members.get(r.toPk, []):
            via_sector[r.fromPk].append((iid, rel))

    out: list[EventLite] = []
    for e in store.query("Event"):
        if not e.get("occurredAt") or e.get("severity") is None:
            continue
        eid = e["eventId"]
        links = list(direct.get(eid, []))
        seen = {iid for iid, _ in links}
        links += [(iid, rel) for iid, rel in via_sector.get(eid, []) if iid not in seen]
        if not links:
            continue
        otype = store.get_type_of(eid, event_types)
        out.append(EventLite(
            eventId=eid, eventType=e["eventType"],
            market=e.get("market") or ("KR" if eid.startswith(("dart", "naver", "press")) else "US"),
            date=pd.Timestamp(str(e["occurredAt"])[:10]),
            severity=float(e["severity"]),
            sentiment=e.get("sentiment"),
            is_news=(otype == "NewsEvent"),
            instruments=links,
        ))
    out.sort(key=lambda x: x.date)
    return out


def signal_on_date(events: list[EventLite], pit: PitStats, t: pd.Timestamp,
                   bdays: pd.DatetimeIndex, validated_only: bool = False) -> dict[str, dict]:
    """날짜 t 의 종목별 시그널 + 기여 내역. 반환: iid → {signal, contribs[]}.

    validated_only=True: t 시점 PIT 기준으로 통계 검증된 유형(|tBmp|>=2)의 기여만 —
    signal-model v1.1 변형. 판정이 PIT 라 결과론이 아니다.
    """
    pos = bdays.searchsorted(t, side="right")
    window_start = bdays[max(0, pos - WINDOW_BD - 1)]
    result: dict[str, dict] = {}
    # events 는 날짜 정렬 — 이진 탐색으로 창 절단
    dates = [e.date for e in events]
    lo = int(np.searchsorted(pd.DatetimeIndex(dates), window_start, side="left"))
    hi = int(np.searchsorted(pd.DatetimeIndex(dates), t, side="right"))
    for e in events[lo:hi]:
        age = max(0, pos - 1 - int(bdays.searchsorted(e.date, side="right")) + 1)
        decay = max(0.0, 1.0 - age / (WINDOW_BD + 1))
        if decay <= 0:
            continue
        if e.is_news:
            if e.sentiment is None:
                continue
            m, validated = NEWS_KAPPA * float(e.sentiment), False
        else:
            stats = pit.stats(e.eventType, e.market, t)
            if stats is None:
                continue
            m, validated = stats["carMean"], stats["validated"]
        if m == 0 or (validated_only and not validated):
            continue
        for iid, rel in e.instruments:
            contrib = rel * e.severity * m * decay
            slot = result.setdefault(iid, {"signal": 0.0, "contribs": []})
            slot["signal"] += contrib
            slot["contribs"].append({
                "eventId": e.eventId, "eventType": e.eventType,
                "contribution": contrib, "validated": validated,
            })
    return {iid: v for iid, v in result.items() if abs(v["signal"]) >= SIGNAL_FLOOR}


def conviction_of(signal: float, contribs: list[dict],
                  history_abs: np.ndarray) -> dict:
    """확신도 분해 — 공식은 모듈 docstring 참조."""
    strength = float((history_abs < abs(signal)).mean()) if len(history_abs) >= 20 else 0.0
    total = sum(abs(c["contribution"]) for c in contribs) or 1.0
    evidence = sum(abs(c["contribution"]) for c in contribs if c["validated"]) / total
    return {
        "strength": round(strength, 3),
        "evidenceShare": round(evidence, 3),
        "conviction": round(0.6 * strength + 0.4 * evidence, 3),
    }


def weeks_since_stronger(current_abs: float, history: pd.Series) -> int | None:
    """이보다 강한 신호가 마지막으로 나온 뒤 몇 주가 지났나. 전 구간에 없으면 None(=관측 내 최강)."""
    stronger = history[history >= current_abs]
    if stronger.empty:
        return None
    return int((history.index[-1] - stronger.index[-1]).days // 7)
