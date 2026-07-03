"""Ken French Data Library — 일간 3팩터 + 모멘텀 (키리스, ~270KB).

CSV 값은 % 단위 그대로 저장 (Factor.unit=PCT, transform=LEVEL).
RF 도 FF:RF 이름으로 저장해 초과수익률 계산에 사용 (Factor 오브젝트는 아님).
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

from ontoquant.ingest import tsio
from ontoquant.ingest.http import get

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FILES = {
    f"{BASE}/F-F_Research_Data_Factors_daily_CSV.zip": ["Mkt-RF", "SMB", "HML", "RF"],
    f"{BASE}/F-F_Momentum_Factor_daily_CSV.zip": ["Mom"],
}
# CSV 컬럼명 → factor 저장 키
COLUMN_TO_KEY = {"Mkt-RF": "FF:MKT", "SMB": "FF:SMB", "HML": "FF:HML",
                 "Mom": "FF:MOM", "RF": "FF:RF"}


def _parse_zip(content: bytes, expect_cols: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        raw = zf.read(zf.namelist()[0]).decode("latin-1")
    rows = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and len(parts[0]) == 8 and parts[0].isdigit():
            rows.append(parts)
    if not rows:
        raise ValueError("Ken French CSV 파싱 실패: 데이터 행 없음")
    width = min(len(rows[0]) - 1, len(expect_cols))
    df = pd.DataFrame([r[: width + 1] for r in rows], columns=["date"] + expect_cols[:width])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in expect_cols[:width]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] <= -99.98, c] = pd.NA  # -99.99 = 결측 코드
    return df


def run(store=None, today=None) -> list[dict]:
    results = []
    for url, cols in FILES.items():
        try:
            df = _parse_zip(get(url).content, cols)
            for col in cols:
                key = COLUMN_TO_KEY[col]
                sub = df[["date", col]].rename(columns={col: "value"}).dropna()
                added = tsio.append_ts(tsio.factor_path(key), sub)
                results.append({"factorId": key, "added": added, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            results.append({"factorId": url.rsplit("/", 1)[-1], "added": 0,
                            "status": f"error: {exc}"})
    return results
