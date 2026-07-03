"""기업 정보 — DART 기업개황(company.json) + SEC submissions → Company 오브젝트.

30일 캐시 (updatedAt 기준). companyListedAs 링크로 종목과 연결.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ontoquant.config import get_key
from ontoquant.core.audit import now_iso
from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest import corp_map
from ontoquant.ingest.http import SEC_UA, get

CACHE_DAYS = 30


def _fresh(company: dict | None) -> bool:
    if not company or not company.get("updatedAt"):
        return False
    updated = datetime.fromisoformat(company["updatedAt"])
    return datetime.now(timezone.utc) - updated < timedelta(days=CACHE_DAYS)


def _dart_date(s: str | None) -> str | None:
    if s and len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def fetch_dart_company(corp_code: str) -> dict | None:
    doc = get("https://opendart.fss.or.kr/api/company.json",
              params={"crtfc_key": get_key("DART_API_KEY"), "corp_code": corp_code}).json()
    if doc.get("status") != "000":
        return None
    return {
        "name": doc.get("corp_name_eng") or doc.get("corp_name"),
        "nameKo": doc.get("corp_name"),
        "ceo": doc.get("ceo_nm"),
        "industryCode": doc.get("induty_code"),
        "foundedDate": _dart_date(doc.get("est_dt")),
        "homepage": doc.get("hm_url") or None,
    }


def fetch_sec_company(cik: str) -> dict | None:
    doc = get(f"https://data.sec.gov/submissions/CIK{cik}.json",
              headers={"User-Agent": SEC_UA}).json()
    return {
        "name": doc.get("name"),
        "industryCode": str(doc.get("sic") or "") or None,
        "industryName": doc.get("sicDescription") or None,
        "homepage": doc.get("website") or None,
    }


def run(store: OntologyStore, today: date | None = None) -> dict:
    corp_map.resolve_corp_codes(store)
    added, skipped, errors = 0, 0, []
    for inst in store.query("Instrument", where={"assetClass": "EQUITY"}):
        is_kr = inst["market"] == "KRX"
        key = inst.get("dartCorpCode") if is_kr else inst.get("secCik")
        if not key:
            continue
        company_id = f"KR:{key}" if is_kr else f"US:{key}"
        if _fresh(store.get("Company", company_id)):
            skipped += 1
            continue
        try:
            info = fetch_dart_company(key) if is_kr else fetch_sec_company(key)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
            continue
        if not info:
            continue
        store.append_object("source", "Company", {
            "companyId": company_id,
            "market": "KR" if is_kr else "US",
            "corpCode": key if is_kr else None,
            "cik": None if is_kr else key,
            "nameKo": info.get("nameKo") or inst.get("nameKo"),
            **{k: v for k, v in info.items() if k != "nameKo"},
            "updatedAt": now_iso(),
        })
        store.append_link("source", LinkRecord(
            "companyListedAs", "Company", company_id, "Instrument", inst["instrumentId"]))
        added += 1
    return {"status": "partial" if errors else "ok", "added": added,
            "cached": skipped, "errors": errors[:3]}
