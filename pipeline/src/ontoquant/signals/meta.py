"""메타라벨링 (López de Prado) — ML 은 방향이 아니라 "이 신호를 얼마나 신뢰할까"만 학습.

- 1차 모델(알파 결합)이 방향을 정하고, ridge logistic 은 적중 확률 p̂ 만 추정
- 출력 = 사이즈 승수 clip(2(p̂−0.5), 0, 1) — 방향 불변
- 63bd 마다 expanding 재적합(최소 252bd), 학습/평가 사이 embargo = h+1bd (purged)
- 채택 게이트(OOS 정확도 > 무필터 기저율 + 유의) 통과 전에는 shadow (승수 미적용)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_TRAIN_BD = 252
REFIT_BD = 63
C_FIXED = 1.0


def available() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def build_dataset(z_all: dict[str, pd.DataFrame], z_comb: pd.DataFrame,
                  fwd: pd.DataFrame, vix_z: pd.Series | None,
                  markets: dict[str, str]) -> pd.DataFrame:
    """발화 인스턴스 데이터셋: (date, instrument) 행, 특징 ≤10, 라벨 = 방향 적중."""
    rows = []
    active = z_comb.where(z_comb.abs() > 0.2).stack()
    for (d, iid), z in active.items():
        f = fwd.at[d, iid] if (d in fwd.index and iid in fwd.columns) else np.nan
        if pd.isna(f):
            continue
        row = {"date": d, "instrumentId": iid,
               "zComb": float(z), "absZ": abs(float(z)),
               "isKr": 1.0 if markets.get(iid) == "KR" else 0.0,
               "vixZ": float(vix_z.get(d, 0.0)) if vix_z is not None else 0.0,
               "label": 1 if np.sign(z) * np.sign(f) > 0 else 0}
        for k in ("str_reversal", "momentum", "pead_ear"):
            zk = z_all.get(k)
            v = zk.at[d, iid] if (zk is not None and d in zk.index and iid in zk.columns) else np.nan
            row[f"z_{k}"] = float(v) if pd.notna(v) else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame()


def purged_walkforward_eval(ds: pd.DataFrame, h: int) -> dict | None:
    """expanding 재적합 + embargo 로 OOS 적중 확률 평가 (shadow 성적표)."""
    if not available() or ds.empty:
        return None
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    features = [c for c in ds.columns if c not in ("date", "instrumentId", "label")]
    dates = ds["date"].drop_duplicates().sort_values().reset_index(drop=True)
    if len(dates) < MIN_TRAIN_BD + REFIT_BD:
        return {"status": "insufficient", "nDates": int(len(dates))}
    preds, labels = [], []
    embargo = h + 1
    for start in range(MIN_TRAIN_BD, len(dates) - 1, REFIT_BD):
        train_end_date = dates.iloc[start - embargo] if start - embargo >= 0 else dates.iloc[0]
        test_dates = set(dates.iloc[start: start + REFIT_BD])
        train = ds[ds["date"] <= train_end_date]
        test = ds[ds["date"].isin(test_dates)]
        if len(train) < 100 or test.empty or train["label"].nunique() < 2:
            continue
        scaler = StandardScaler().fit(train[features])
        clf = LogisticRegression(C=C_FIXED, max_iter=500)
        clf.fit(scaler.transform(train[features]), train["label"])
        p = clf.predict_proba(scaler.transform(test[features]))[:, 1]
        preds.extend(p)
        labels.extend(test["label"].tolist())
    if len(labels) < 100:
        return {"status": "insufficient", "nOos": int(len(labels))}
    preds_a, labels_a = np.array(preds), np.array(labels)
    base_rate = float(labels_a.mean())
    # 상위 절반 확신 구간의 적중률 vs 기저율 — 필터로서의 가치
    hi = preds_a >= np.median(preds_a)
    acc_hi = float(labels_a[hi].mean())
    n_hi = int(hi.sum())
    se = np.sqrt(base_rate * (1 - base_rate) / max(n_hi, 1))
    t = (acc_hi - base_rate) / max(se, 1e-9)
    return {"status": "ok", "nOos": int(len(labels_a)), "baseHitRate": round(base_rate, 3),
            "highConfHitRate": round(acc_hi, 3), "lift": round(acc_hi - base_rate, 3),
            "liftT": round(float(t), 2), "passes": bool(t >= 2.0)}
