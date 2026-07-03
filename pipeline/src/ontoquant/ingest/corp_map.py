"""DART corpCode.xml — corp_code ↔ stock_code 매핑 (주 1회 캐시).

캐시: data/reference/corp_codes.csv (stock_code 있는 상장사만, ~3천 행)
"""
from __future__ import annotations

import csv
import io
import time
import xml.etree.ElementTree as ET
import zipfile

from ontoquant import config
from ontoquant.config import get_key
from ontoquant.ingest.http import get

CACHE = config.REFERENCE_DIR / "corp_codes.csv"
MAX_AGE_DAYS = 7


def refresh_cache(force: bool = False) -> int:
    if CACHE.exists() and not force:
        age_days = (time.time() - CACHE.stat().st_mtime) / 86400
        if age_days < MAX_AGE_DAYS:
            return 0
    resp = get("https://opendart.fss.or.kr/api/corpCode.xml",
               params={"crtfc_key": get_key("DART_API_KEY")}, timeout=60)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    rows = []
    for el in root.iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if not stock:
            continue
        rows.append({
            "corp_code": (el.findtext("corp_code") or "").strip(),
            "corp_name": (el.findtext("corp_name") or "").strip(),
            "stock_code": stock,
        })
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["corp_code", "corp_name", "stock_code"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def stock_to_corp() -> dict[str, str]:
    if not CACHE.exists():
        refresh_cache(force=True)
    with open(CACHE, encoding="utf-8") as f:
        return {r["stock_code"]: r["corp_code"] for r in csv.DictReader(f)}


def resolve_corp_codes(store) -> int:
    """KR 종목의 dartCorpCode 를 채워 source Instrument 스냅샷 갱신."""
    refresh_cache()
    mapping = stock_to_corp()
    instruments = store.query("Instrument")
    changed = 0
    for inst in instruments:
        if inst["currency"] == "KRW" and inst["assetClass"] == "EQUITY":
            code = mapping.get(inst["ticker"])
            if code and inst.get("dartCorpCode") != code:
                inst["dartCorpCode"] = code
                changed += 1
    if changed:
        store.replace_objects("source", "Instrument", instruments)
    return changed
