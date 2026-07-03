"""SRW-SUE — 계절 랜덤워크 기대 대비 표준화 실적 서프라이즈 (Bernard-Thomas 89/90).

  SUE_q = (X_q − X_{q−4}) / σ,  σ = std(계절차분 최근 8개, 최소 4개), ±5 winsorize
  X = operatingIncome (커버리지 최상, KR 잠정실적 관행과 일치; netIncome 은 결측 과다)

분기 증분 도출 (실측 확정된 저장 시맨틱):
  KR: Q1=3개월, H1=Q2 단독 3개월(누적 아님!), Q3=3개월, FY=연간 누적
      → Q4 = FY − (Q1+Q2+Q3). 단 누적형으로 저장된 회사 감지 시(H1>Q3 & H1>1.6×Q1)
        Q2 = H1 − Q1 로 전환. 재합산 오차 >1%×|FY| 면 그 해 Q4 결측.
  US: Q1~Q4 라벨 그대로 3개월치.

knownAt (PIT): [분기말, +100d] 구간의 해당 종목 첫 EARNINGS 이벤트일 (EAR 와 앵커 공유).
  없으면 법정기한 폴백: 분기말+45d (FY 는 +90d — 사업보고서 기한).
  잠정치 공시일에 확정치를 적용하는 것은 PEAD 재현 문헌의 표준 2차 근사.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from ontoquant.core.store import OntologyStore

FIELD = "operatingIncome"
MIN_DIFFS = 4
MAX_DIFFS = 8
WINSOR = 5.0
QUARTER_END = {"Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}


def _quarterly_series(rows: list[dict]) -> dict[tuple[int, int], float]:
    """Fundamental 행들 → {(year, q): 3개월 증분값}."""
    by_label: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        val = r.get(FIELD)
        period = r.get("period") or ""
        if val is None or len(period) < 6:
            continue
        year, label = int(period[:4]), period[4:]
        by_label[label][year] = float(val)
    out: dict[tuple[int, int], float] = {}
    years = set()
    for label in by_label:
        years |= set(by_label[label])
    for y in sorted(years):
        q1 = by_label.get("Q1", {}).get(y)
        h1 = by_label.get("H1", {}).get(y)
        q3 = by_label.get("Q3", {}).get(y)
        fy = by_label.get("FY", {}).get(y)
        # US 는 Q2/Q4 라벨이 직접 존재
        q2_direct = by_label.get("Q2", {}).get(y)
        q4_direct = by_label.get("Q4", {}).get(y)
        if q1 is not None:
            out[(y, 1)] = q1
        if q2_direct is not None:
            out[(y, 2)] = q2_direct
        elif h1 is not None:
            # KR: H1 은 기본적으로 Q2 단독치. 누적형 감지 시 H1−Q1
            if q1 is not None and q3 is not None and h1 > q3 and h1 > 1.6 * abs(q1):
                out[(y, 2)] = h1 - q1
            else:
                out[(y, 2)] = h1
        if q3 is not None:
            out[(y, 3)] = q3
        if q4_direct is not None:
            out[(y, 4)] = q4_direct
        elif fy is not None and all((y, q) in out for q in (1, 2, 3)):
            q4 = fy - (out[(y, 1)] + out[(y, 2)] + out[(y, 3)])
            # 정합성 가드: 재합산 오차가 크면 시맨틱 불일치 → 결측
            if abs(out[(y, 1)] + out[(y, 2)] + out[(y, 3)] + q4 - fy) <= 0.01 * max(abs(fy), 1):
                out[(y, 4)] = q4
    return out


def compute_sue(rows: list[dict]) -> dict[tuple[int, int], float]:
    """회사의 Fundamental 행들 → {(year, q): SUE}. 표본 부족 분기는 없음(NaN 아닌 부재)."""
    q_series = _quarterly_series(rows)
    if not q_series:
        return {}
    keys = sorted(q_series)
    diffs: dict[tuple[int, int], float] = {}
    for (y, q) in keys:
        prev = (y - 1, q)
        if prev in q_series:
            diffs[(y, q)] = q_series[(y, q)] - q_series[prev]
    out: dict[tuple[int, int], float] = {}
    diff_keys = sorted(diffs)
    for i, key in enumerate(diff_keys):
        history = [diffs[k] for k in diff_keys[max(0, i - MAX_DIFFS): i]]
        if len(history) < MIN_DIFFS:
            continue
        sigma = float(np.std(history, ddof=1))
        if sigma < 1e-9:
            continue
        out[key] = float(np.clip(diffs[key] / sigma, -WINSOR, WINSOR))
    return out


def sue_events(store: OntologyStore) -> list[dict]:
    """전 종목 SUE + knownAt 앵커 → [{instrumentId, knownAt, sue, period}]."""
    company_inst = {r.fromPk: r.toPk for r in store.links("companyListedAs")}
    fund_by_company: dict[str, list[dict]] = defaultdict(list)
    for f in store.query("Fundamental"):
        fund_by_company[f["companyId"]].append(f)
    # EARNINGS 이벤트 앵커 (종목별 날짜 목록)
    earnings_dates: dict[str, list[pd.Timestamp]] = defaultdict(list)
    for e in store.query("Event"):
        if e.get("eventType") == "EARNINGS" and e.get("occurredAt"):
            eid = e["eventId"]
            otype = "EarningsEvent"
            for nb in store.neighbors(otype, eid, "eventAffectsInstrument", "out"):
                earnings_dates[nb.pk].append(pd.Timestamp(str(e["occurredAt"])[:10]))
    for v in earnings_dates.values():
        v.sort()

    out: list[dict] = []
    for cid, rows in fund_by_company.items():
        iid = company_inst.get(cid)
        if not iid:
            continue
        # 분기 순서대로 앵커 배정 + 단조 증가 강제 — 직전 분기(예: FY 사업보고서)
        # 공시가 다음 분기 SUE 를 조기 공개해 버리는 오배정 방지 (검증 리뷰 LEAK 3).
        # 최소 간격 +4d: 분기말 직후 이벤트는 그 분기 실적일 수 없다 (삼성식 +7d 잠정은 통과).
        last_anchor: pd.Timestamp | None = None
        for (y, q), sue in sorted(compute_sue(rows).items()):
            m, d = QUARTER_END[f"Q{q}"]
            q_end = pd.Timestamp(year=y, month=m, day=d)
            anchor = None
            for dt in earnings_dates.get(iid, []):
                if (q_end + pd.Timedelta(days=4) <= dt <= q_end + pd.Timedelta(days=100)
                        and (last_anchor is None or dt > last_anchor)):
                    anchor = dt
                    break
            if anchor is None:
                anchor = q_end + pd.Timedelta(days=90 if q == 4 else 45)
                if last_anchor is not None and anchor <= last_anchor:
                    anchor = last_anchor + pd.Timedelta(days=1)
            last_anchor = anchor
            out.append({"instrumentId": iid, "knownAt": anchor,
                        "sue": sue, "period": f"{y}Q{q}"})
    return out
