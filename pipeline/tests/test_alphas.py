"""알파 PIT 규율 테스트 — 미래 정보가 과거 알파값에 스며들면 여기서 잡힌다."""
import numpy as np
import pandas as pd

from ontoquant.signals.alphas import _add_pulse, _panel, zscore_xs
from ontoquant.signals.sue import _quarterly_series, compute_sue

BDAYS = pd.bdate_range("2025-01-01", periods=100)
COLS = ["A", "B", "C"]


def test_pulse_starts_next_business_day():
    """knownAt 당일에는 0, 다음 영업일부터 반영 (t→t+1 규율)."""
    panel = _panel(BDAYS, COLS)
    known = BDAYS[10]
    _add_pulse(panel, known, "A", 1.0, hold_bd=5)
    assert panel.loc[known, "A"] == 0.0
    assert panel.iloc[11]["A"] == 1.0
    assert panel.iloc[15]["A"] == 1.0
    assert panel.iloc[16]["A"] == 0.0


def test_future_event_does_not_change_past():
    """미래 이벤트 주입 → 그 이전 구간의 알파값 불변 (누출 회귀)."""
    panel = _panel(BDAYS, COLS)
    _add_pulse(panel, BDAYS[20], "A", 1.0, hold_bd=10)
    before = panel.iloc[:50].copy()
    _add_pulse(panel, BDAYS[60], "A", 9.9, hold_bd=10)   # 미래 이벤트
    pd.testing.assert_frame_equal(panel.iloc[:50], before)


def test_pulse_decay_is_linear_and_forward_only():
    panel = _panel(BDAYS, COLS)
    _add_pulse(panel, BDAYS[10], "B", 1.0, hold_bd=4, decay=True)
    vals = panel["B"].iloc[11:15].to_numpy()
    assert np.allclose(vals, [1.0, 0.75, 0.5, 0.25])
    assert (panel["B"].iloc[:11] == 0).all()


def test_zscore_cross_section():
    panel = _panel(BDAYS, list("ABCDEFGHIJKL"))  # 12종목 (min_names=10 충족)
    panel.iloc[5] = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -2]
    z = zscore_xs(panel, min_names=10)
    assert z.iloc[5]["A"] > 1.5 and z.iloc[5]["L"] < -1.5
    assert abs(z.iloc[5].mean()) < 1e-9
    assert z.abs().max().max() <= 3.0 + 1e-9


def test_sue_kr_h1_is_standalone_q2():
    """실측 시맨틱: KR H1 행 = Q2 단독 3개월치, FY = 연간 누적 → Q4 = FY − ΣQ1..Q3."""
    rows = []
    for y, vals in [(2023, (10, 12, 11, 47)), (2024, (11, 13, 12, 52))]:
        q1, q2, q3, fy = vals
        rows += [
            {"period": f"{y}Q1", "operatingIncome": q1},
            {"period": f"{y}H1", "operatingIncome": q2},   # Q2 단독
            {"period": f"{y}Q3", "operatingIncome": q3},
            {"period": f"{y}FY", "operatingIncome": fy},   # 연간 누적
        ]
    q = _quarterly_series(rows)
    assert q[(2023, 2)] == 12          # H1 그대로 Q2
    assert q[(2023, 4)] == 47 - 33     # FY − (Q1+Q2+Q3)
    assert q[(2024, 4)] == 52 - 36


def test_sue_detects_cumulative_h1():
    """누적형으로 저장된 회사: H1 > Q3 이고 H1 > 1.6×Q1 → Q2 = H1 − Q1."""
    rows = [
        {"period": "2023Q1", "operatingIncome": 10},
        {"period": "2023H1", "operatingIncome": 22},   # 누적 (10+12)
        {"period": "2023Q3", "operatingIncome": 11},
        {"period": "2023FY", "operatingIncome": 47},
    ]
    q = _quarterly_series(rows)
    assert q[(2023, 2)] == 12          # 22 − 10
    assert q[(2023, 4)] == 47 - 33


def test_sue_requires_min_history():
    """계절차분 4개 미만이면 SUE 를 만들지 않는다 (억지 신호 금지)."""
    rows = []
    for y in (2023, 2024):
        for lbl, v in (("Q1", 10), ("H1", 12), ("Q3", 11), ("FY", 47)):
            rows.append({"period": f"{y}{lbl}", "operatingIncome": v})
    assert compute_sue(rows) == {}     # 차분 4개뿐 → history(직전) 부족

    for y in (2020, 2021, 2022):
        for lbl, v in (("Q1", 9 + y % 3), ("H1", 11), ("Q3", 10), ("FY", 44)):
            rows.append({"period": f"{y}{lbl}", "operatingIncome": v})
    sues = compute_sue(rows)
    assert len(sues) > 0
    assert all(abs(v) <= 5.0 for v in sues.values())   # winsorize
