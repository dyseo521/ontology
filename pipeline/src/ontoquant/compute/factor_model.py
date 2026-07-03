"""팩터 모델 — 롤링 OLS 분리 회귀 (다중공선성 방지).

그룹:
  US_STYLE : 초과수익률 ~ Mkt-RF + SMB + HML + MOM   (Ken French, 미국 종목)
  US_MACRO : 수익률     ~ ΔDGS10 + dlogVIX + dlogWTI  (미국 종목)
  KR_CORE  : 수익률     ~ KR:MKT(t) + USDKRW(t-1) + FF:MKT(t-1)  (한국 종목)

KR 래그 규칙: KST 마감이 US 장 시작 전이므로 US 소스 팩터는 "직전 관측값"을
merge_asof(allow_exact_matches=False) 로 매칭한다 (Factor.lagForKr >= 1).

산출: FactorExposure 스냅샷(computed) + instrumentExposures/exposureFactor 링크
     + FACTOR_QUALITY EvaluationRun (게이트: medianR2>=0.15 AND coverage=100%)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ontoquant.compute import returns as ret
from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest import tsio
from ontoquant.modeling.objective import active_model, record_evaluation

WINDOW = 252
MIN_OBS = 120
HAC_LAGS = 5

GROUPS = {
    "US_STYLE": ["FF:MKT", "FF:SMB", "FF:HML", "FF:MOM"],
    "US_MACRO": ["MACRO:DGS10", "MACRO:VIX", "MACRO:WTI"],
    "KR_CORE": ["KR:MKT", "MACRO:USDKRW", "FF:MKT"],
}


def load_factor_series(factor: dict) -> pd.Series | None:
    """Factor.transform 적용 후 소수 단위 시계열 반환."""
    fid, transform = factor["factorId"], factor["transform"]
    if factor["source"] == "NAVER":
        close = ret.load_close(f"KRX:{factor['sourceSeriesId']}", prefer_adj=False)
        if close is None:
            return None
        s = close.pct_change()
    else:
        df = tsio.read_ts(tsio.factor_path(fid))
        if df is None or df.empty:
            return None
        level = df.set_index("date")["value"].astype(float)
        if transform == "LEVEL":
            s = level / 100.0 if factor.get("unit") == "PCT" else level
        elif transform == "DIFF":
            s = level.diff()
        elif transform == "LOGRET":
            s = np.log(level).diff()
        elif transform == "PCT_RETURN":
            s = level.pct_change()
        else:
            raise ValueError(f"알 수 없는 transform: {transform}")
    s = s.dropna()
    s.name = fid
    return s


def load_rf() -> pd.Series:
    df = tsio.read_ts(tsio.factor_path("FF:RF"))
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return (df.set_index("date")["value"].astype(float) / 100.0).rename("RF")


def _align_group(y: pd.Series, factors: list[dict], series: dict[str, pd.Series],
                 is_kr: bool) -> pd.DataFrame:
    """y 인덱스(종목 거래일) 기준으로 팩터 정렬. KR 은 lagForKr 규칙 적용."""
    base = y.rename("y").to_frame()
    for f in factors:
        s = series.get(f["factorId"])
        if s is None:
            return pd.DataFrame()
        lag = int(f.get("lagForKr") or 0) if is_kr else 0
        if lag > 0:
            merged = pd.merge_asof(
                base.reset_index()[["date"]].assign(_k=1),
                s.rename("v").reset_index().assign(_k=1)[["date", "v"]],
                on="date", allow_exact_matches=False, direction="backward",
            )
            base[f["factorId"]] = merged["v"].to_numpy()
        else:
            base[f["factorId"]] = s.reindex(base.index).to_numpy()
    return base.dropna()


def _rolling_beta_stability(y: pd.Series, f: pd.Series, window: int = 60) -> float | None:
    df = pd.concat([y.rename("y"), f.rename("f")], axis=1).dropna()
    if len(df) < window * 2:
        return None
    cov = df["y"].rolling(window).cov(df["f"])
    var = df["f"].rolling(window).var()
    betas = (cov / var).dropna()
    return float(betas.tail(WINDOW).std()) if len(betas) else None


def run(store: OntologyStore, as_of=None) -> dict:
    instruments = store.query("Instrument")
    factor_objs = {f["factorId"]: f for f in store.query("Factor")}
    series = {fid: load_factor_series(f) for fid, f in factor_objs.items()}
    rf = load_rf()
    model = active_model(store, "factor-model") or {"modelVersionId": "factor-model@1.0.0"}
    mv_id = model["modelVersionId"]

    exposures: list[dict] = []
    links_exp: list[LinkRecord] = []
    links_fac: list[LinkRecord] = []
    group_r2: list[float] = []
    stabilities: list[float] = []
    covered = 0
    end_date = None

    for inst in instruments:
        iid = inst["instrumentId"]
        y = ret.load_returns(iid)
        if y is None or len(y) < MIN_OBS:
            continue
        is_kr = inst["currency"] == "KRW"
        groups = ["KR_CORE"] if is_kr else ["US_STYLE", "US_MACRO"]
        inst_ok = False
        for group in groups:
            f_defs = [factor_objs[fid] for fid in GROUPS[group] if fid in factor_objs]
            yy = y.copy()
            if group == "US_STYLE" and not rf.empty:
                yy = (yy - rf.reindex(yy.index).fillna(0.0)).rename(iid)
            df = _align_group(yy, f_defs, series, is_kr).tail(WINDOW)
            if len(df) < MIN_OBS:
                continue
            X = sm.add_constant(df[[f["factorId"] for f in f_defs]])
            res = sm.OLS(df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
            r2 = float(res.rsquared)
            group_r2.append(r2)
            end_date = max(end_date or df.index.max(), df.index.max())
            inst_ok = True
            for f in f_defs:
                fid = f["factorId"]
                exposures.append({
                    "exposureId": f"{iid}:{fid}",
                    "instrumentId": iid, "factorId": fid,
                    "beta": round(float(res.params[fid]), 6),
                    "tStat": round(float(res.tvalues[fid]), 3),
                    "stderr": round(float(res.bse[fid]), 6),
                    "r2": round(r2, 4),
                    "window": len(df),
                    "asOfDate": str(df.index.max().date()),
                    "modelVersionId": mv_id,
                })
                links_exp.append(LinkRecord("instrumentExposures", "Instrument", iid,
                                            "FactorExposure", f"{iid}:{fid}"))
                links_fac.append(LinkRecord("exposureFactor", "FactorExposure", f"{iid}:{fid}",
                                            "Factor", fid))
        if inst_ok:
            covered += 1
            mkt_fid = "KR:MKT" if is_kr else "FF:MKT"
            stab = _rolling_beta_stability(y, series.get(mkt_fid, pd.Series(dtype=float)))
            if stab is not None:
                stabilities.append(stab)

    coverage_pct = round(100.0 * covered / max(len(instruments), 1), 1)
    median_r2 = round(float(np.median(group_r2)), 4) if group_r2 else 0.0
    metric_set = {
        "medianR2": median_r2,
        "minR2": round(float(np.min(group_r2)), 4) if group_r2 else 0.0,
        "betaStability": round(float(np.median(stabilities)), 4) if stabilities else None,
        "coveragePct": coverage_pct,
        "nRegressions": len(group_r2),
    }
    gates = [
        ("medianR2 >= 0.15", median_r2 >= 0.15, f"medianR2={median_r2}"),
        ("coveragePct == 100", coverage_pct == 100.0, f"coverage={coverage_pct}%"),
    ]
    passed = all(p for _, p, _ in gates)
    if not passed:
        for e in exposures:
            e["stale"] = True

    store.replace_objects("computed", "FactorExposure", exposures)
    store.replace_links("computed", "instrumentExposures", links_exp)
    store.replace_links("computed", "exposureFactor", links_fac)
    eval_run = record_evaluation(
        store, mv_id, "FACTOR_QUALITY", metric_set,
        (str((end_date - pd.Timedelta(days=365)).date()) if end_date is not None else "",
         str(end_date.date()) if end_date is not None else ""),
        gates,
    )
    return {"exposures": len(exposures), "coveragePct": coverage_pct,
            "medianR2": median_r2, "passedGates": passed, "runId": eval_run["runId"]}
