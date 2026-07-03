"""알파 라이브러리 — 문헌에서 부호·지평이 검증된 예측자만 (signal-model v2).

공통 규약:
- 반환 Panel = pd.DataFrame(index=영업일, columns=instrumentId)
- 모든 이벤트는 knownAt "다음 영업일"부터 값에 반영 (감사의 t+1 진입과 이중 지연 방지:
  알파(t)는 knownAt≤t 정보만, 체결은 t+1)
- 이벤트성 알파는 무신호=0, 연속형(반전/모멘텀)은 값 그대로
- 부호는 사전 고정 (표에서 뒤집기 금지):
    pead_sue(+, BT89) · pead_ear(+, Brandt08) · insider(+ BUY만, CMP12)
    news_fresh(+, Tetlock08) · news_stale(−, Tetlock11)
    str_reversal(− 최근수익, Jegadeesh90) · momentum(+ 12-1, JT93)
    flag_buyback(+, Ikenberry95) · flag_issuance(−, LR95)
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from ontoquant.core.store import OntologyStore

DRIFT_BD = 60          # PEAD/insider/flag 지속 기간
NEWS_BD = 5
INSIDER_RATIO_CAP = 0.1   # 지분 증감 0.1%p 에서 impulse 포화
MAJOR_IMPULSE = 0.5


def _panel(bdays: pd.DatetimeIndex, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(0.0, index=bdays, columns=columns)


def _add_pulse(panel: pd.DataFrame, known_at: pd.Timestamp, iid: str,
               value: float, hold_bd: int, decay: bool = False) -> None:
    """knownAt 다음 영업일부터 hold_bd 동안 value 를 더한다 (decay=선형감쇠)."""
    if iid not in panel.columns:
        return
    start = panel.index.searchsorted(known_at, side="right")  # knownAt 다음 영업일
    if start >= len(panel.index):
        return
    end = min(start + hold_bd, len(panel.index))
    if decay:
        weights = np.linspace(1.0, 0.0, end - start, endpoint=False)
        panel.iloc[start:end, panel.columns.get_loc(iid)] += value * weights
    else:
        panel.iloc[start:end, panel.columns.get_loc(iid)] += value


# ── PEAD ────────────────────────────────────────────────────────────

def alpha_pead_sue(store: OntologyStore, bdays: pd.DatetimeIndex,
                   columns: list[str]) -> pd.DataFrame:
    from ontoquant.signals.sue import sue_events
    panel = _panel(bdays, columns)
    for ev in sue_events(store):
        _add_pulse(panel, ev["knownAt"], ev["instrumentId"], ev["sue"], DRIFT_BD)
    return panel


def alpha_pead_ear(cars: pd.DataFrame | None, bdays: pd.DatetimeIndex,
                   columns: list[str]) -> pd.DataFrame:
    """발표창 초과수익(sear) — EARNINGS 이벤트만, earKnownAt(+2bd) 기준."""
    panel = _panel(bdays, columns)
    if cars is None or cars.empty:
        return panel
    sub = cars[(cars["eventType"] == "EARNINGS")].dropna(subset=["ear", "earKnownAt"])
    for _, r in sub.iterrows():
        _add_pulse(panel, r["earKnownAt"], r["instrumentId"],
                   float(np.clip(r["sear"], -5, 5)), DRIFT_BD)
    return panel


# ── 내부자 (KR 전용 — CMP 2012: 매수만, 기회적만) ────────────────────

def is_routine(reporter: str | None, iid: str, when: pd.Timestamp,
               history: dict[tuple[str, str], list[pd.Timestamp]]) -> bool:
    """PIT routine 판정: 직전 2개 연도 모두 같은 달력월에 BUY 보고가 있으면 routine."""
    if not reporter:
        return False
    dates = history.get((reporter, iid), [])
    months = {(d.year, d.month) for d in dates if d < when}
    return all((when.year - k, when.month) in months for k in (1, 2))


def alpha_insider(store: OntologyStore, bdays: pd.DatetimeIndex,
                  columns: list[str]) -> pd.DataFrame:
    panel = _panel(bdays, columns)
    # 보고자 이력 (routine 판정용) — 판정 자체는 각 이벤트 시점 이전만 본다 (PIT)
    history: dict[tuple[str, str], list[pd.Timestamp]] = defaultdict(list)
    filings: list[tuple[pd.Timestamp, str, str, float, str]] = []
    for e in store.query("DisclosureEvent"):
        if e.get("ownerDirection") != "BUY" or not e.get("occurredAt"):
            continue
        ratio = e.get("ownerNetRatio")
        if ratio is None or ratio <= 0:
            continue
        when = pd.Timestamp(str(e["occurredAt"])[:10])
        for nb in store.neighbors("DisclosureEvent", e["eventId"],
                                  "eventAffectsInstrument", "out"):
            reporter = e.get("reporter")
            history[(reporter, nb.pk)].append(when)
            is_major = e.get("eventType") == "MAJOR_HOLDINGS"
            filings.append((when, nb.pk, reporter, float(ratio), "M" if is_major else "E"))
            break
    for v in history.values():
        v.sort()
    for when, iid, reporter, ratio, kind in filings:
        if kind == "E" and is_routine(reporter, iid, when, history):
            continue  # 정기 보고 패턴 = 무정보 (CMP 2012)
        impulse = min(1.0, ratio / INSIDER_RATIO_CAP)
        if kind == "M":
            impulse *= MAJOR_IMPULSE
        _add_pulse(panel, when, iid, impulse, DRIFT_BD, decay=True)
    return panel


# ── 뉴스 (fresh=과소반응+; t→t+1 시차는 _add_pulse 가 보장) ──────────

def alpha_news_fresh(store: OntologyStore, bdays: pd.DatetimeIndex,
                     columns: list[str]) -> pd.DataFrame:
    """원본 뉴스 감성 (과소반응 +, Tetlock 08). dupCount 는 나중에 도착한 중복이
    원본에 소급 가산되는 값이라 PIT 분류에 쓸 수 없다 (검증 리뷰 LEAK 2) —
    저장된 뉴스는 전부 원본(발행 시점엔 fresh)이므로 모두 여기서 처리한다."""
    panel = _panel(bdays, columns)
    for e in store.query("NewsEvent"):
        s = e.get("sentiment")
        if s is None or abs(s) < 0.25 or not e.get("occurredAt"):
            continue
        when = pd.Timestamp(str(e["occurredAt"])[:10])
        value = float(s) * float(e.get("severity") or 0.3)
        for nb in store.neighbors("NewsEvent", e["eventId"], "eventAffectsInstrument", "out"):
            _add_pulse(panel, when, nb.pk, value, NEWS_BD, decay=True)
            break
    return panel


def alpha_news_stale(store: OntologyStore, bdays: pd.DatetimeIndex,
                     columns: list[str]) -> pd.DataFrame:
    """재탕 뉴스 반전 (Tetlock 2011) — 비활성 (0 패널 = IC 관측 없음 → shadow).
    중복 기사가 삭제되고 dupCount 만 원본에 소급 가산되는 현재 파이프라인에서는
    PIT 재구성이 불가능하다. 중복을 도착일 그대로 보존하게 되면 활성화한다."""
    return _panel(bdays, columns)


# ── 가격 컨텍스트 팩터 ───────────────────────────────────────────────

def alpha_str_reversal(close: pd.DataFrame) -> pd.DataFrame:
    """단기 반전: 최근 5일 수익률의 음수 (Jegadeesh 1990)."""
    return -(close / close.shift(5) - 1)


def alpha_momentum(close: pd.DataFrame) -> pd.DataFrame:
    """12-1 모멘텀 (Jegadeesh-Titman 1993): 최근 1개월 제외 12개월 수익률."""
    return close.shift(21) / close.shift(252) - 1


# ── 이벤트 플래그 (저빈도 드리프트) ──────────────────────────────────

def _flag(store: OntologyStore, bdays: pd.DatetimeIndex, columns: list[str],
          types: set[str], sign: float) -> pd.DataFrame:
    panel = _panel(bdays, columns)
    event_types = store.schema.interfaces["Event"].implementedBy
    for e in store.query("Event"):
        if e.get("eventType") not in types or not e.get("occurredAt"):
            continue
        otype = store.get_type_of(e["eventId"], event_types)
        if not otype:
            continue
        when = pd.Timestamp(str(e["occurredAt"])[:10])
        for nb in store.neighbors(otype, e["eventId"], "eventAffectsInstrument", "out"):
            if float(nb.link.props.get("relevance", 0)) >= 0.9:
                _add_pulse(panel, when, nb.pk, sign, DRIFT_BD)
            break
    return panel


def alpha_flag_buyback(store, bdays, columns) -> pd.DataFrame:
    return _flag(store, bdays, columns, {"BUYBACK"}, +1.0)


def alpha_flag_issuance(store, bdays, columns) -> pd.DataFrame:
    return _flag(store, bdays, columns, {"CAPITAL_INCREASE", "CONVERTIBLE_BOND"}, -1.0)


# ── 표준화 · 지평 적격표 ────────────────────────────────────────────

def zscore_xs(panel: pd.DataFrame, min_names: int = 10) -> pd.DataFrame:
    """일별 크로스섹션 z-score. 유효 종목 부족일은 NaN, ±3 클립.
    이벤트성 알파(대부분 0)는 0 도 유효 관측 — '활성 vs 나머지'가 정보다."""
    mean = panel.mean(axis=1)
    std = panel.std(axis=1, ddof=1)
    valid = panel.notna().sum(axis=1) >= min_names
    z = panel.sub(mean, axis=0).div(std.replace(0, np.nan), axis=0)
    z[~valid] = np.nan
    return z.clip(-3, 3)


# 지평별 적격 알파 (사전 고정 — 변경은 ruleHash 신규 시도)
HORIZON_ALPHAS: dict[int, list[str]] = {
    5: ["str_reversal", "news_fresh", "news_stale"],
    20: ["pead_sue", "pead_ear", "insider", "news_fresh", "news_stale",
         "flag_buyback", "flag_issuance", "momentum"],
    60: ["pead_sue", "pead_ear", "insider", "flag_buyback", "flag_issuance", "momentum"],
}


def build_all(store: OntologyStore, close: pd.DataFrame,
              cars: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """전 알파 raw Panel 생성 (표준화 전)."""
    bdays = close.index
    cols = list(close.columns)
    return {
        "pead_sue": alpha_pead_sue(store, bdays, cols),
        "pead_ear": alpha_pead_ear(cars, bdays, cols),
        "insider": alpha_insider(store, bdays, cols),
        "news_fresh": alpha_news_fresh(store, bdays, cols),
        "news_stale": alpha_news_stale(store, bdays, cols),
        "str_reversal": alpha_str_reversal(close),
        "momentum": alpha_momentum(close),
        "flag_buyback": alpha_flag_buyback(store, bdays, cols),
        "flag_issuance": alpha_flag_issuance(store, bdays, cols),
    }
