import numpy as np
import pandas as pd
import pytest

from ontoquant.insights.event_study import compute_car, judge


def _series(rng, n=400, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=n)
    return idx, pd.Series(rng.normal(0.0, 0.01, n), index=idx)


def test_compute_car_detects_abnormal_drop():
    rng = np.random.default_rng(7)
    idx, r_m = _series(rng)
    beta = 1.2
    r_i = beta * r_m + pd.Series(rng.normal(0, 0.002, len(idx)), index=idx)
    event_date = idx[300]
    # 이벤트창 [-1,+5] 에 하루 -3% 비정상 수익률 주입
    r_i.iloc[301] -= 0.03
    car = compute_car(r_i, r_m, event_date)
    assert car is not None
    assert car == pytest.approx(-0.03, abs=0.012)


def test_compute_car_no_abnormal_is_near_zero():
    rng = np.random.default_rng(11)
    idx, r_m = _series(rng)
    r_i = 0.9 * r_m + pd.Series(rng.normal(0, 0.002, len(idx)), index=idx)
    car = compute_car(r_i, r_m, idx[250])
    assert car is not None
    assert abs(car) < 0.02


def test_compute_car_insufficient_history():
    rng = np.random.default_rng(3)
    idx, r_m = _series(rng, n=80)
    r_i = r_m.copy()
    assert compute_car(r_i, r_m, idx[40]) is None      # 추정창 부족
    assert compute_car(r_i, r_m, idx[-2]) is None      # 이벤트창 부족


def test_gate_logic():
    assert judge(n=27, t_stat=-3.4) is True
    assert judge(n=9, t_stat=-5.0) is False    # 표본 부족
    assert judge(n=30, t_stat=1.5) is False    # 유의성 미달
    assert judge(n=10, t_stat=2.0) is True     # 경계값
