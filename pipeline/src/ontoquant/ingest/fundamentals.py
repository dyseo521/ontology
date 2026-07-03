"""분기 재무 — DART fnlttSinglAcnt(주요계정) + SEC companyfacts → Fundamental 오브젝트.

- KR: 보고서 코드 11013(Q1)/11012(반기)/11014(Q3)/11011(사업). 반기/사업은 누적치 —
  period 라벨(H1/FY)로 구분해 YoY는 동일 라벨끼리만 비교한다.
- US: companyfacts 의 frame(CYyyyyQq) 항목으로 달력 분기 정규화.
- 증분: 이미 store 에 있는 fundamentalId 는 스킵. 분기 종료 + 45일 전에는 조회하지 않음.
"""
from __future__ import annotations

from datetime import date

from ontoquant.config import get_key
from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest.http import SEC_UA, get

DART_REPORTS = [("11013", "Q1"), ("11012", "H1"), ("11014", "Q3"), ("11011", "FY")]
DART_ACCOUNTS = {
    "매출액": "revenue", "영업이익": "operatingIncome", "당기순이익": "netIncome",
    "자산총계": "totalAssets", "부채총계": "totalLiabilities", "자본총계": "totalEquity",
}
SEC_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "SalesRevenueNet"],
    "operatingIncome": ["OperatingIncomeLoss"],
    "netIncome": ["NetIncomeLoss"],
    "totalAssets": ["Assets"],
    "totalLiabilities": ["Liabilities"],
    "totalEquity": ["StockholdersEquity"],
}
BACKFILL_YEARS = 3


def _num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _dart_periods(today: date) -> list[tuple[str, str, str]]:
    """(bsns_year, reprt_code, label) — 공시 마감(분기말+45d) 지난 것만."""
    out = []
    quarter_end = {"Q1": (3, 31), "H1": (6, 30), "Q3": (9, 30), "FY": (12, 31)}
    for year in range(today.year - BACKFILL_YEARS, today.year + 1):
        for code, label in DART_REPORTS:
            m, d = quarter_end[label]
            qe = date(year, m, d)
            if (today - qe).days >= 45:
                out.append((str(year), code, f"{year}{label}"))
    return out


def ingest_dart(store: OntologyStore, inst: dict, existing: set[str], today: date) -> int:
    corp = inst.get("dartCorpCode")
    if not corp:
        return 0
    company_id = f"KR:{corp}"
    added = 0
    for year, code, period in _dart_periods(today):
        fid = f"{company_id}:{period}"
        if fid in existing:
            continue
        doc = get("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json", params={
            "crtfc_key": get_key("DART_API_KEY"), "corp_code": corp,
            "bsns_year": year, "reprt_code": code}).json()
        existing.add(fid)  # 데이터 없어도 재조회 방지 (파일에는 있는 것만 기록)
        if doc.get("status") != "000":
            continue
        rows = [r for r in doc.get("list", []) if r.get("fs_div") == "CFS"] or doc.get("list", [])
        values: dict[str, float | None] = {}
        for r in rows:
            key = DART_ACCOUNTS.get(r.get("account_nm", "").strip())
            if key and key not in values:
                values[key] = _num(r.get("thstrm_amount"))
        if not values:
            continue
        store.append_object("source", "Fundamental", {
            "fundamentalId": fid, "companyId": company_id, "period": period,
            "fiscalDate": None, "currency": "KRW", "source": "DART", **values,
        })
        store.append_link("source", LinkRecord(
            "fundamentalOfCompany", "Fundamental", fid, "Company", company_id))
        added += 1
    return added


def ingest_sec(store: OntologyStore, inst: dict, existing: set[str], today: date) -> int:
    cik = inst.get("secCik")
    if not cik:
        return 0
    company_id = f"US:{cik}"
    marker = f"{company_id}:{today.year}Q{(today.month - 1) // 3 or 4}"
    doc = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
              headers={"User-Agent": SEC_UA}, timeout=60).json()
    gaap = doc.get("facts", {}).get("us-gaap", {})
    # frame(CYyyyyQq[I]) 기준으로 분기값 수집
    by_period: dict[str, dict] = {}
    for field, tags in SEC_TAGS.items():
        for tag in tags:
            units = gaap.get(tag, {}).get("units", {}).get("USD", [])
            found = False
            for u in units:
                frame = u.get("frame", "")
                if not frame.startswith("CY") or "Q" not in frame:
                    continue
                period = frame[2:].replace("I", "")  # CY2026Q1I → 2026Q1
                if int(period[:4]) < today.year - BACKFILL_YEARS:
                    continue
                by_period.setdefault(period, {})[field] = float(u["val"])
                by_period[period].setdefault("fiscalDate", u.get("end"))
                found = True
            if found:
                break
    added = 0
    for period, values in by_period.items():
        fid = f"{company_id}:{period}"
        if fid in existing:
            continue
        existing.add(fid)
        store.append_object("source", "Fundamental", {
            "fundamentalId": fid, "companyId": company_id, "period": period,
            "fiscalDate": values.pop("fiscalDate", None),
            "currency": "USD", "source": "SEC", **values,
        })
        store.append_link("source", LinkRecord(
            "fundamentalOfCompany", "Fundamental", fid, "Company", company_id))
        added += 1
    return added


def run(store: OntologyStore, today: date | None = None) -> dict:
    today = today or date.today()
    existing = {f["fundamentalId"] for f in store.query("Fundamental")}
    added, errors = 0, []
    for inst in store.query("Instrument", where={"assetClass": "EQUITY"}):
        try:
            if inst["market"] == "KRX":
                added += ingest_dart(store, inst, existing, today)
            else:
                added += ingest_sec(store, inst, existing, today)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
    return {"status": "partial" if errors else "ok", "added": added, "errors": errors[:3]}
