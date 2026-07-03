"""Probabilistic / Deflated Sharpe Ratio — Bailey & López de Prado (2014).

PSR(SR*) = Φ( (SR̂ − SR*)·√(T−1) / √(1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²) )
DSR      = PSR(SR₀),  SR₀ = √V[{SRₙ}]·((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)))

- SR̂ 는 per-period(일간) Sharpe. γ₄ 는 비초과 첨도(정규=3).
- N(시도 수)이 클수록, 시도 간 SR 분산이 클수록 통과 문턱이 자동 상승 —
  다중 시도에 대한 벌점 (Harvey-Liu-Zhu 2016).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps

EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe(sr: float, sr_star: float, t_obs: int,
                         skew: float, kurt: float) -> float:
    if t_obs < 10:
        return 0.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + ((kurt - 1) / 4.0) * sr * sr))
    z = (sr - sr_star) * math.sqrt(t_obs - 1) / denom
    return float(sps.norm.cdf(z))


def expected_max_sharpe(n_trials: int, var_trial_sr: float) -> float:
    """N회 독립 시도(진짜 SR=0 귀무) 하 기대 최대 SR."""
    n = max(2, int(n_trials))
    sd = math.sqrt(max(var_trial_sr, 1e-12))
    return sd * ((1 - EULER_GAMMA) * sps.norm.ppf(1 - 1.0 / n)
                 + EULER_GAMMA * sps.norm.ppf(1 - 1.0 / (n * math.e)))


def deflated_sharpe(returns: pd.Series, trial_srs: list[float] | None = None) -> dict:
    """OOS 일별 수익률과 시도 SR 목록 → PSR/DSR 리포트.

    trial_srs: 서로 다른 시도(그리드 조합/과거 rule-hash)들의 per-period Sharpe.
    없거나 1개면 N=1 → SR₀=0 → DSR=PSR(0).
    """
    r = returns.dropna()
    t_obs = len(r)
    if t_obs < 30 or float(r.std()) == 0:
        return {"srDaily": None, "srAnnual": None, "psr0": None, "dsr": None,
                "nTrials": len(trial_srs or []) or 1, "srStar0": None, "T": t_obs}
    sr = float(r.mean() / r.std())
    skew = float(sps.skew(r))
    kurt = float(sps.kurtosis(r, fisher=False))  # 비초과 (정규=3)
    trials = [s for s in (trial_srs or []) if s is not None]
    n = max(1, len(trials))
    if n >= 2:
        sr0 = expected_max_sharpe(n, float(np.var(trials, ddof=1)))
    else:
        sr0 = 0.0
    return {
        "srDaily": round(sr, 4),
        "srAnnual": round(sr * math.sqrt(252), 3),
        "psr0": round(probabilistic_sharpe(sr, 0.0, t_obs, skew, kurt), 4),
        "dsr": round(probabilistic_sharpe(sr, sr0, t_obs, skew, kurt), 4),
        "nTrials": n,
        "srStar0": round(sr0, 4),
        "skew": round(skew, 3), "kurt": round(kurt, 3), "T": t_obs,
    }
