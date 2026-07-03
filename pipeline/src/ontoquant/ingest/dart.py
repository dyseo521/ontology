"""DART 공시검색 (list.json) → DisclosureEvent/EarningsEvent + 직접 링크.

일일 실행: 보유 KR 종목별 최근 4일 (주말/휴일 커버). corp_code 는 corp_map 이 해석.
백필: events/backfill.py (Phase 3) 가 bgn_de 를 과거로 확장해 재사용.
"""
from __future__ import annotations

from datetime import date, timedelta

from ontoquant.config import get_key
from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.events.classify import classify_dart
from ontoquant.ingest import corp_map
from ontoquant.ingest.http import get

URL = "https://opendart.fss.or.kr/api/list.json"


def fetch_disclosures(corp_code: str, bgn: date, end: date) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        resp = get(URL, params={
            "crtfc_key": get_key("DART_API_KEY"), "corp_code": corp_code,
            "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
            "page_no": page, "page_count": 100,
        })
        doc = resp.json()
        if doc.get("status") == "013":  # 조회 데이터 없음
            break
        if doc.get("status") != "000":
            raise RuntimeError(f"DART {doc.get('status')}: {doc.get('message')}")
        out.extend(doc.get("list", []))
        if page >= int(doc.get("total_page", 1)):
            break
        page += 1
    return out


def event_from_row(row: dict, instrument_id: str) -> tuple[str, dict]:
    """(objectType, event dict) 반환."""
    etype = classify_dart(row.get("report_nm", ""))
    rcept_dt = row.get("rcept_dt", "")
    occurred = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}T09:00:00+09:00" if len(rcept_dt) == 8 else None
    base = {
        "eventId": f"dart:{row['rcept_no']}",
        "eventType": etype,
        "occurredAt": occurred,
        "title": f"{row.get('corp_name', '')} · {row.get('report_nm', '').strip()}",
        "summary": None,
        "sourceUrl": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}",
        "market": "KR",
    }
    if etype == "EARNINGS":
        return "EarningsEvent", base
    return "DisclosureEvent", {
        **base,
        "rcpNo": row["rcept_no"], "corpCode": row.get("corp_code"),
        "filingType": row.get("report_nm", "").strip()[:60],
    }


def ingest_range(store: OntologyStore, bgn: date, end: date) -> dict:
    """기간 내 보유 KR 종목 공시 수집 (증분: 기존 eventId 스킵)."""
    corp_map.resolve_corp_codes(store)
    existing = {e["eventId"] for e in store.query("Event")}
    added, links = 0, 0
    errors: list[str] = []
    for inst in store.query("Instrument", where={"market": "KRX"}):
        corp = inst.get("dartCorpCode")
        if not corp:
            continue
        try:
            rows = fetch_disclosures(corp, bgn, end)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
            continue
        for row in rows:
            otype, event = event_from_row(row, inst["instrumentId"])
            if event["eventId"] in existing:
                continue
            existing.add(event["eventId"])
            store.append_object("source", otype, event)
            store.append_link("source", LinkRecord(
                "eventAffectsInstrument", otype, event["eventId"],
                "Instrument", inst["instrumentId"],
                {"relevance": 1.0, "method": "DIRECT"}))
            added += 1
            links += 1
    return {"status": "partial" if errors else "ok", "added": added,
            "links": links, "errors": errors[:3]}


def run(store: OntologyStore, today: date | None = None) -> dict:
    today = today or date.today()
    return ingest_range(store, today - timedelta(days=4), today)
