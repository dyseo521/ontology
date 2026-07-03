"""이벤트 스터디 — Point-in-Time CAR 원장 + BMP 표준화 검정 (+ KP 보정).

방법론 (MacKinlay 1997; Boehmer-Musumeci-Poulsen 1991; Kolari-Pynnönen 2010):
  추정창 [-120,-21]: 시장모형 r_i = α + β·r_m + ε
  이벤트창 [-1,+5]:  CAR = Σ AR,  SCAR = CAR / s(CAR)  (BMP 예측오차 보정 분산)
  타입 검정: t_BMP = mean(SCAR)/(std(SCAR)/√n), 달력 겹침 시 KP 스칼라 보정

PIT 규율 (누출 방지의 핵심):
  event_cars.parquet 에 knownAt(=이벤트일+6영업일) 기록.
  모든 조회는 knownAt <= as_of 필터 — 백테스트는 시뮬레이션 날짜를,
  라이브는 오늘(as_of=None)을 넘긴다. 같은 함수, 같은 추정기.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ontoquant import config
from ontoquant.compute import returns as ret
from ontoquant.compute.factor_model import load_factor_series
from ontoquant.core.store import OntologyStore
from ontoquant.modeling.objective import active_model, record_evaluation

EST_START, EST_END = -120, -21   # 추정창 (거래일 오프셋)
EVT_START, EVT_END = -1, 5       # 이벤트창 (검정용 CAR)
EAR_START, EAR_END = -1, 1       # 발표창 (EAR — Brandt et al 2008, 예측자)
KNOWN_LAG_BD = 6                 # CAR 완결 시차 (이벤트일 + 6 영업일)
MIN_EST_OBS = 60
GATE_MIN_N = 10
GATE_MIN_T = 2.0
CARS_PATH = config.COMPUTED_DIR / "event_cars.parquet"
# 이벤트 스터디 제외 타입 (가격 가설이 없는 정기/절차성 공시)
SKIP_TYPES = {"PERIODIC_REPORT", "REG_FD", "DISCLOSURE_OTHER", "NEWS",
              "RATE_SHOCK", "VOL_SPIKE", "CREDIT_SHOCK", "FX_SHOCK", "OIL_SHOCK"}


def compute_car(r_i: pd.Series, r_m: pd.Series, event_date: pd.Timestamp) -> dict | None:
    """단일 이벤트 다중 창 CAR + BMP 표준화. 데이터 부족 시 None.

    추정창(α, β, 잔차분산)은 1회 계산하고 이벤트창을 두 번 적용:
      car/scar: [-1,+5] (검정·심각도용, +6bd 확정)
      ear/sear: [-1,+1] (발표창 초과수익 — 예측자, Brandt et al 2008, +2bd 확정)
    반환: {car, scar, evtEndCar, ear, sear, evtEndEar, estN, residStd}
    (ear 창이 짧아 데이터 경계에서 ear 만 확정될 수 있음 — car 는 None 가능)
    """
    df = pd.concat([r_i.rename("y"), r_m.rename("m")], axis=1).dropna()
    if df.empty:
        return None
    idx = df.index.searchsorted(event_date)
    if idx >= len(df.index):
        return None
    # 가격 히스토리 시작 이전 이벤트 방지: 추정창이 음수 인덱스로 넘어가면
    # iloc 슬라이스가 엉뚱한 구간을 잡는다 (2015년 이벤트가 2021년 가격으로 계산되는 버그)
    if idx + EST_START < 0:
        return None
    est = df.iloc[idx + EST_START: idx + EST_END]
    if len(est) < MIN_EST_OBS:
        return None
    x, y = est["m"].to_numpy(), est["y"].to_numpy()
    var_m = x.var()
    if var_m <= 0:
        return None
    beta = float(np.cov(y, x, bias=True)[0, 1] / var_m)
    alpha = float(y.mean() - beta * x.mean())
    resid = y - (alpha + beta * x)
    s2 = float(resid.var(ddof=2)) if len(resid) > 2 else float(resid.var())
    M = len(est)
    m_dev_est = float(((x - x.mean()) ** 2).sum())

    def _window(start: int, end: int) -> tuple[float, float, pd.Timestamp] | None:
        evt = df.iloc[max(0, idx + start): idx + end + 1]
        # 전체 창 필수: 우측(라이브 엣지) 절단을 허용하면 불완전 CAR 가
        # done=car.notna() 판정에 걸려 영구 동결된다 (검증 리뷰 BUG 4)
        if len(evt) < (end - start + 1):
            return None
        ar = evt["y"] - (alpha + beta * evt["m"])
        total = float(ar.sum())
        # BMP 예측오차 보정 분산 (Campbell-Lo-MacKinlay §4.4.3) — 창 길이 L 별 재계산
        L = len(evt)
        m_dev_evt = float(((evt["m"] - x.mean()) ** 2).sum())
        var_w = s2 * (L + L * L / M + m_dev_evt / max(m_dev_est, 1e-12))
        return total, float(total / np.sqrt(max(var_w, 1e-12))), evt.index[-1]

    ear_res = _window(EAR_START, EAR_END)
    car_res = _window(EVT_START, EVT_END)
    if ear_res is None and car_res is None:
        return None
    return {
        "car": car_res[0] if car_res else None,
        "scar": car_res[1] if car_res else None,
        "evtEndCar": car_res[2] if car_res else None,
        "ear": ear_res[0] if ear_res else None,
        "sear": ear_res[1] if ear_res else None,
        "evtEndEar": ear_res[2] if ear_res else None,
        "estN": M, "residStd": float(np.sqrt(s2)),
    }


LEDGER_COLUMNS = ["eventId", "eventType", "market", "instrumentId", "eventDate",
                  "knownAt", "car", "scar", "earKnownAt", "ear", "sear",
                  "estN", "residStd"]


def compute_event_cars(store: OntologyStore) -> pd.DataFrame:
    """이벤트별 CAR 원장 증분 갱신 (idempotent).

    완결 판정은 car(장창) 기준 — ear 만 확정된 반쪽 행은 다음 실행에서
    재계산되어 last-wins 로 교체된다 (라이브 엣지에서 EAR 가 4일 먼저 확정됨).
    """
    existing = pd.read_parquet(CARS_PATH) if CARS_PATH.exists() else pd.DataFrame(
        columns=LEDGER_COLUMNS)
    for col in LEDGER_COLUMNS:  # 구버전 parquet 호환
        if col not in existing.columns:
            existing[col] = pd.NA
    done = set(existing.loc[existing["car"].notna(), "eventId"]) if len(existing) else set()

    factors = {f["factorId"]: f for f in store.query("Factor")}
    mkt = {
        "KR": load_factor_series(factors["KR:MKT"]) if "KR:MKT" in factors else None,
        "US": load_factor_series(factors["FF:MKT"]) if "FF:MKT" in factors else None,
    }
    returns_cache: dict[str, pd.Series | None] = {}
    event_types = store.schema.interfaces["Event"].implementedBy
    rows = []
    for e in store.query("Event"):
        eid = e["eventId"]
        etype = e.get("eventType")
        if eid in done or etype in SKIP_TYPES or not e.get("occurredAt"):
            continue
        otype = store.get_type_of(eid, event_types)
        if otype is None:
            continue
        market = e.get("market") or ("KR" if eid.startswith(("dart", "naver", "press")) else "US")
        r_m = mkt.get(market)
        if r_m is None:
            continue
        evt_date = pd.Timestamp(str(e["occurredAt"])[:10])
        for nb in store.neighbors(otype, eid, "eventAffectsInstrument", "out"):
            if float(nb.link.props.get("relevance", 0)) < 0.9:
                continue
            if nb.pk not in returns_cache:
                returns_cache[nb.pk] = ret.load_returns(nb.pk)
            r_i = returns_cache[nb.pk]
            if r_i is None:
                continue
            res = compute_car(r_i, r_m, evt_date)
            if res is None:
                continue

            def _known(evt_end) -> pd.Timestamp | None:
                """창 종료 다음 거래일. 아직 없으면 None (이른 knownAt 박제 방지)."""
                if evt_end is None:
                    return None
                k = r_m.index.searchsorted(evt_end) + 1
                return r_m.index[k] if k < len(r_m.index) else None

            known_car = _known(res["evtEndCar"])
            known_ear = _known(res["evtEndEar"])
            if known_car is None and known_ear is None:
                continue
            rows.append({
                "eventId": eid, "eventType": etype, "market": market,
                "instrumentId": nb.pk, "eventDate": evt_date,
                "knownAt": known_car,
                "car": res["car"] if known_car is not None else None,
                "scar": res["scar"] if known_car is not None else None,
                "earKnownAt": known_ear,
                "ear": res["ear"] if known_ear is not None else None,
                "sear": res["sear"] if known_ear is not None else None,
                "estN": res["estN"], "residStd": res["residStd"],
            })
            break  # 이벤트당 대표 종목 1개 (직접 링크 첫 번째)
    if rows:
        add = pd.DataFrame(rows)
        merged = pd.concat([existing, add], ignore_index=True)
        merged = merged.drop_duplicates(["eventId"], keep="last")
        for c in ("eventDate", "knownAt", "earKnownAt"):
            merged[c] = pd.to_datetime(merged[c]).astype("datetime64[ns]")
        CARS_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(CARS_PATH, index=False)
        return merged
    return existing


def load_cars(complete_only: bool = True) -> pd.DataFrame | None:
    """원장 로드. complete_only=True 면 car(장창) 확정 행만 — 검정/PIT 통계 소비자용.
    EAR 알파는 complete_only=False 로 로드해 earKnownAt 기준으로 직접 필터한다."""
    if not CARS_PATH.exists():
        return None
    df = pd.read_parquet(CARS_PATH)
    for c in ("eventDate", "knownAt", "earKnownAt"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c]).astype("datetime64[ns]")
    if complete_only:
        df = df.dropna(subset=["car"])
    return df


def _kp_adjust(t_bmp: float, sub: pd.DataFrame, store: OntologyStore | None) -> tuple[float, int]:
    """Kolari-Pynnönen 스칼라 보정: t_KP = t·√((1−r̄)/(1+(n_ov−1)·r̄)).

    r̄ = 이벤트창이 달력상 겹치는 쌍들의 시장모형 잔차 상관 근사
        (시장 차감 수익률 r_i − r_m 의 상관 — 원시 상관을 쓰면 공통 시장요인
         때문에 과대 축소되므로 반드시 시장을 차감한다).
    보정의 유효 n 은 전체 표본이 아니라 '겹침에 연루된 이벤트 수' — 겹치지 않는
    이벤트끼리는 독립이므로 전체 n 으로 축소하면 과보정이다.
    """
    n = len(sub)
    if n < 2:
        return t_bmp, 0
    # 대표본은 O(n²) 쌍 비교가 불가 — 최근 300건 샘플로 겹침 비율을 추정 (통계적으로 충분)
    KP_SAMPLE = 300
    sampled = sub.sort_values("eventDate").tail(KP_SAMPLE) if n > KP_SAMPLE else sub
    dates = sampled[["eventDate", "instrumentId", "market"]].reset_index(drop=True)
    m = len(dates)
    window = pd.Timedelta(days=9)  # 이벤트창 [-1,+5] ≈ 달력 9일
    pairs = []
    involved: set[int] = set()
    # 날짜 정렬 상태 + 슬라이딩 윈도우: 9일 밖이면 내부 루프 중단 → O(n×k)
    for i in range(m):
        for j in range(i + 1, m):
            if (dates.eventDate[j] - dates.eventDate[i]) > window:
                break
            if dates.instrumentId[i] != dates.instrumentId[j]:
                pairs.append((dates.instrumentId[i], dates.instrumentId[j]))
                involved.update((i, j))
    # 샘플에서 추정한 '겹침 연루 비율'을 전체 n 으로 환산
    involved_n = int(len(involved) / max(m, 1) * n)
    if not pairs or store is None:
        return t_bmp, len(pairs)
    market = str(dates.market.iloc[0])
    factors = {f["factorId"]: f for f in store.query("Factor")}
    mkt_id = "KR:MKT" if market == "KR" else "FF:MKT"
    r_m = load_factor_series(factors[mkt_id]) if mkt_id in factors else None
    cors = []
    cache: dict[str, pd.Series | None] = {}
    for a, b in pairs[:60]:
        for k in (a, b):
            if k not in cache:
                r_i = ret.load_returns(k)
                if r_i is not None and r_m is not None:
                    r_i = (r_i - r_m.reindex(r_i.index)).dropna()  # 시장 차감 잔차 근사
                cache[k] = r_i
        ra, rb = cache[a], cache[b]
        if ra is None or rb is None:
            continue
        df = pd.concat([ra.rename("a"), rb.rename("b")], axis=1).dropna().tail(252)
        if len(df) >= 60:
            cors.append(float(df["a"].corr(df["b"])))
    if not cors:
        return t_bmp, len(pairs)
    r_bar = max(0.0, float(np.mean(cors)))
    n_ov = max(2, involved_n)  # 겹침 연루 이벤트 수 기준 (전체 n 으로 하면 과보정)
    adj = np.sqrt((1 - r_bar) / (1 + (n_ov - 1) * r_bar)) if r_bar < 1 else 0.0
    return t_bmp * float(adj), len(pairs)


def _stats_from(sub: pd.DataFrame, store: OntologyStore | None = None) -> dict | None:
    n = len(sub)
    if n == 0:
        return None
    scars = sub["scar"].to_numpy()
    cars = sub["car"].to_numpy()
    mean_car = float(cars.mean())
    if n > 1 and scars.std(ddof=1) > 0:
        t_bmp = float(scars.mean() / (scars.std(ddof=1) / np.sqrt(n)))
    else:
        t_bmp = 0.0
    t_kp, n_overlap = _kp_adjust(t_bmp, sub, store)
    return {
        "n": n, "carMean": round(mean_car, 5),
        "carStd": round(float(cars.std(ddof=1)), 5) if n > 1 else 0.0,
        "tBmp": round(t_kp, 2), "tBmpRaw": round(t_bmp, 2),
        "nOverlap": n_overlap,
        "hitRateNeg": round(float((cars < 0).mean()), 3),
    }


def pit_type_stats(cars: pd.DataFrame, event_type: str, market: str,
                   as_of: pd.Timestamp | str, min_n: int = GATE_MIN_N,
                   store: OntologyStore | None = None) -> dict | None:
    """knownAt <= as_of 표본만으로 타입 통계. n < min_n 이면 None ('모름')."""
    as_of = pd.Timestamp(as_of)
    sub = cars[(cars["eventType"] == event_type) & (cars["market"] == market)
               & (cars["knownAt"] <= as_of)]
    if len(sub) < min_n:
        return None
    stats = _stats_from(sub, store)
    if stats:
        stats["asOf"] = str(as_of.date())
    return stats


def get_type_summary(store: OntologyStore, event_type: str, market: str | None,
                     as_of: str | None = None) -> dict | None:
    """단일 조회 경로 — as_of=None 은 오늘(라이브). event_rules/backtest/severity 공용."""
    cars = load_cars()
    if cars is None or cars.empty:
        return None
    ts = pd.Timestamp(as_of) if as_of else pd.Timestamp.now().normalize()
    stats = pit_type_stats(cars, event_type, market or "US", ts, min_n=1, store=None)
    if stats is None:
        return None
    # 소비자 호환 필드 (carT 는 tBmp 로 대체)
    stats["carT"] = stats["tBmp"]
    stats["runId"] = None
    return stats


def judge(n: int, t_stat: float) -> bool:
    return n >= GATE_MIN_N and abs(t_stat) >= GATE_MIN_T


def run(store: OntologyStore, as_of: str | None = None) -> dict:
    """일일 실행: CAR 원장 갱신 → 타입×시장별 EvaluationRun(EVENT_STUDY) 기록."""
    as_of = as_of or str(date.today())
    cars = compute_event_cars(store)
    if cars is None or cars.empty:
        return {"status": "no-data", "types": 0, "significant": []}
    model = active_model(store, "event-classifier") or {"modelVersionId": "event-classifier@1.0.0"}
    summaries = []
    as_of_ts = pd.Timestamp(as_of)
    for (etype, market), _ in cars.groupby(["eventType", "market"]):
        sub = cars[(cars["eventType"] == etype) & (cars["market"] == market)
                   & (cars["knownAt"] <= as_of_ts)]
        stats = _stats_from(sub, store)
        if stats is None:
            continue
        metric_set = {"eventType": etype, "market": market,
                      "window": f"[{EVT_START},+{EVT_END}]", **stats}
        gates = [
            (f"n >= {GATE_MIN_N}", stats["n"] >= GATE_MIN_N, f"n={stats['n']}"),
            (f"|tBmp| >= {GATE_MIN_T}", abs(stats["tBmp"]) >= GATE_MIN_T,
             f"tBmp={stats['tBmp']}"),
        ]
        record_evaluation(store, model["modelVersionId"], "EVENT_STUDY", metric_set,
                          ("2021-01-01", as_of), gates,
                          run_key=f"event-study:{etype}:{market}:{as_of}")
        summaries.append(metric_set)
    return {"status": "ok", "types": len(summaries),
            "significant": [s for s in summaries if judge(s["n"], s["tBmp"])]}
