"""누출(결과론적 학습) 회귀 테스트 — PIT 규율이 깨지면 여기서 잡힌다."""
import numpy as np
import pandas as pd
import pytest

from ontoquant.insights.event_study import pit_type_stats
from ontoquant.proposals.backtest import EMBARGO_BD, _fold_bounds


def _ledger(rows):
    df = pd.DataFrame(rows)
    df["eventDate"] = pd.to_datetime(df["eventDate"])
    df["knownAt"] = pd.to_datetime(df["knownAt"])
    return df


def test_pit_excludes_future_rows():
    """knownAt > as_of 행은 절대 포함되지 않는다 (property)."""
    rows = [
        {"eventId": f"e{i}", "eventType": "EARNINGS", "market": "KR",
         "instrumentId": "KRX:X",
         "eventDate": f"2024-{(i % 12) + 1:02d}-10",
         "knownAt": f"2024-{(i % 12) + 1:02d}-20",
         "car": -0.02, "scar": -1.5, "estN": 100, "residStd": 0.01}
        for i in range(24)
    ]
    cars = _ledger(rows)
    stats_mid = pit_type_stats(cars, "EARNINGS", "KR", as_of="2024-06-30", min_n=1)
    n_known = int((cars["knownAt"] <= pd.Timestamp("2024-06-30")).sum())
    assert stats_mid["n"] == n_known
    assert stats_mid["n"] < len(cars)  # 미래 표본이 섞이면 실패


def test_pit_vs_fullsample_divergence():
    """CAR 이 표본 후반부에만 음(-) → 초반 시점 PIT 는 규칙 발동 불가(=None 또는 부호 다름),
    full-sample 은 발동 — 이 차이가 사라지면 누출 재발."""
    early = [
        {"eventId": f"a{i}", "eventType": "BUYBACK", "market": "KR",
         "instrumentId": "KRX:X", "eventDate": f"2023-0{(i % 6) + 1}-15",
         "knownAt": f"2023-0{(i % 6) + 1}-25",
         "car": +0.01, "scar": +0.8, "estN": 100, "residStd": 0.01}
        for i in range(12)
    ]
    late = [
        {"eventId": f"b{i}", "eventType": "BUYBACK", "market": "KR",
         "instrumentId": "KRX:X", "eventDate": f"2024-0{(i % 6) + 1}-15",
         "knownAt": f"2024-0{(i % 6) + 1}-25",
         "car": -0.05, "scar": -3.0, "estN": 100, "residStd": 0.01}
        for i in range(12)
    ]
    cars = _ledger(early + late)
    pit_early = pit_type_stats(cars, "BUYBACK", "KR", as_of="2023-07-01", min_n=10)
    full = pit_type_stats(cars, "BUYBACK", "KR", as_of="2025-01-01", min_n=10)
    assert pit_early is not None and pit_early["carMean"] > 0   # 당시엔 호재로 보였다
    assert full["carMean"] < -0.01                              # 사후에는 악재
    # 규칙 carMax=-0.01 판정: PIT 는 미발동, full-sample 은 발동
    assert not (pit_early["carMean"] <= -0.01)
    assert full["carMean"] <= -0.01


def test_walkforward_embargo_boundaries():
    """train 종료 + embargo <= test 시작, test 창은 서로 겹치지 않는다."""
    index = pd.bdate_range("2023-07-01", periods=756)
    folds = _fold_bounds(index)
    assert len(folds) >= 3
    prev_test_end = 0
    for train_sl, test_sl in folds:
        assert train_sl.stop + EMBARGO_BD <= test_sl.start + 1e-9
        assert test_sl.start >= prev_test_end   # 겹침 없음
        prev_test_end = test_sl.stop
        assert train_sl.stop >= 126             # 최소 학습 표본


def test_min_n_returns_none():
    cars = _ledger([{
        "eventId": "x", "eventType": "MERGER", "market": "KR", "instrumentId": "KRX:X",
        "eventDate": "2024-01-10", "knownAt": "2024-01-20",
        "car": -0.1, "scar": -2.0, "estN": 100, "residStd": 0.01}])
    assert pit_type_stats(cars, "MERGER", "KR", as_of="2024-06-30", min_n=10) is None
