"""shrunk-IC 결합 (Grinold-Kahn) — 데이터가 정하는 것은 가중치 하나뿐, 그것도 PIT+축소.

  IC_k(t)  = mean{ spearman(Z_k(d,·), r_{d+1→d+1+h}) : d 완결(pos(d) ≤ pos(t)−(h+2)) }
  IC̃_k(t)  = max(0, IC_k(t)) × min(1, n_k(t)/60)          # 음수 floor + burn-in ramp
  w_k(t)   ∝ (1−λ)/K + λ·IC̃_k(t)/Σ_j IC̃_j(t)             # λ=0.5 사전 고정
  Z_comb   = Σ_k w_k·Z_k (NaN=0 중립)
  α(t,h)   = ω_h(t) · IC_comb(t) · Z_comb                  # ω_h = h일 수익률 단면 σ (expanding)

이력이 전무한 알파(n=0)는 K 에서 제외(shadow) — 등가중 몫도 주지 않는다.
음수 IC 부호 뒤집기 금지: 시장이 문헌과 반대면 그 알파의 기여가 0 에 수렴하는 것이 정직.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

LAMBDA = 0.5
BURN_IN = 60


def forward_returns(close: pd.DataFrame, h: int) -> pd.DataFrame:
    """t 시그널 → t+1 진입, t+1+h 청산 (체결 지연 1일)."""
    return close.shift(-1 - h) / close.shift(-1) - 1


def daily_ic(z: pd.DataFrame, fwd: pd.DataFrame, min_names: int = 5) -> pd.Series:
    """일별 크로스섹션 spearman IC. 활성(≠0, 비NaN) 종목 min_names 미만이면 NaN."""
    out = pd.Series(np.nan, index=z.index)
    zv, fv = z.to_numpy(), fwd.reindex(index=z.index, columns=z.columns).to_numpy()
    for i in range(len(z.index)):
        row_z, row_f = zv[i], fv[i]
        mask = ~(np.isnan(row_z) | np.isnan(row_f)) & (row_z != 0)
        if mask.sum() < min_names or len(np.unique(row_z[mask])) < 2:
            continue
        ic = sps.spearmanr(row_z[mask], row_f[mask]).statistic
        if not np.isnan(ic):
            out.iloc[i] = ic
    return out


def expanding_weights(ic_series: dict[str, pd.Series], index: pd.DatetimeIndex,
                      h: int) -> pd.DataFrame:
    """날짜별 알파 가중치 (전 구간 PIT — t 에서는 완결된 IC 관측만 사용)."""
    lag = h + 2  # d+1+h < t 보장
    stats = {}
    for k, ic in ic_series.items():
        ic_shifted = ic.reindex(index).shift(lag)
        n = ic_shifted.notna().cumsum()
        mean = ic_shifted.expanding().mean()
        stats[k] = (mean, n)
    weights = pd.DataFrame(0.0, index=index, columns=list(ic_series))
    for i, t in enumerate(index):
        tilded, active = {}, []
        for k, (mean, n) in stats.items():
            n_t = float(n.iloc[i])
            if n_t <= 0:
                continue  # 이력 전무 → shadow (K 제외)
            active.append(k)
            m = mean.iloc[i]
            tilded[k] = max(0.0, float(m) if pd.notna(m) else 0.0) * min(1.0, n_t / BURN_IN)
        if not active:
            continue
        total = sum(tilded.values())
        for k in active:
            ic_part = (tilded[k] / total) if total > 0 else (1.0 / len(active))
            weights.at[t, k] = (1 - LAMBDA) / len(active) + LAMBDA * ic_part
    return weights


def combine(z_panels: dict[str, pd.DataFrame], weights: pd.DataFrame) -> pd.DataFrame:
    """Z_comb = Σ w_k·Z_k (NaN=0 중립)."""
    first = next(iter(z_panels.values()))
    combined = pd.DataFrame(0.0, index=first.index, columns=first.columns)
    for k, z in z_panels.items():
        if k in weights.columns:
            combined += z.fillna(0.0).mul(weights[k], axis=0)
    return combined


def grinold_alpha(z_comb: pd.DataFrame, fwd: pd.DataFrame, h: int) -> pd.DataFrame:
    """α = ω_h·IC_comb·z — 기대 h일 초과수익률 스케일 (expanding PIT)."""
    lag = h + 2
    omega = fwd.std(axis=1, ddof=1).shift(lag).expanding().mean()
    ic_comb = daily_ic(z_comb, fwd).shift(lag).expanding().mean().clip(lower=0)
    return z_comb.mul(omega * ic_comb, axis=0)


def newey_west_t(ic: pd.Series, lag: int) -> tuple[float, float, int]:
    """겹치는 h일 창 자기상관 보정 t (Newey-West). 반환: (meanIC, t, n)."""
    x = ic.dropna().to_numpy()
    n = len(x)
    if n < 20:
        return (float(np.mean(x)) if n else 0.0, 0.0, n)
    mean = float(x.mean())
    e = x - mean
    lrv = float(e @ e) / n
    for j in range(1, min(lag, n - 1) + 1):
        w = 1 - j / (lag + 1)
        lrv += 2 * w * float(e[:-j] @ e[j:]) / n
    se = np.sqrt(max(lrv, 1e-12) / n)
    return mean, float(mean / se), n
