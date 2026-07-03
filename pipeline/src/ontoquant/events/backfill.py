"""이벤트 히스토리 백필 — 이벤트 스터디 표본 확보 (1회성 + 필요 시 증분).

  python -m ontoquant.events.backfill --years 3

- DART: 보유 KR 종목 공시를 연 단위 청크로 수집 (일 20,000 요청 한도 내 소량)
- EDGAR: CIK 별 8-K 최대 100건 (browse-edgar Atom 페이지네이션 1회)
- 매크로: FRED z-score 트리거를 과거 lookback 으로 재생성
백필 후 events 스테이지(임베딩/보강)를 이어서 실행한다.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from ontoquant.core.store import OntologyStore
from ontoquant.events import process
from ontoquant.ingest import dart


def backfill_dart(store: OntologyStore, years: int) -> dict:
    today = date.today()
    total = {"added": 0, "errors": []}
    for k in range(years):
        end = today - timedelta(days=365 * k)
        bgn = today - timedelta(days=365 * (k + 1))
        r = dart.ingest_range(store, bgn, end)
        total["added"] += r["added"]
        total["errors"].extend(r.get("errors", []))
        print(f"  DART {bgn} ~ {end}: +{r['added']}")
    return total


def backfill_edgar(store: OntologyStore) -> dict:
    from ontoquant.ingest import edgar
    added, errors = 0, []
    existing = {e["eventId"] for e in store.query("Event")}
    for inst in store.query("Instrument"):
        cik = inst.get("secCik")
        if not cik:
            continue
        try:
            filings = edgar.fetch_filings(cik, count=100)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
            continue
        label = inst.get("nameKo") or inst["name"]
        for f in filings:
            if not f["accession"]:
                continue
            eid = f"edgar:{f['accession']}"
            if eid in existing:
                continue
            existing.add(eid)
            from ontoquant.core.store import LinkRecord
            from ontoquant.events.classify import classify_edgar
            import re
            form = "8-K" if "8-K" in f["title"] else f["title"].split(" - ")[0].strip()
            etype, item = classify_edgar(form, f["summary"] + " " + f["title"])
            base = {
                "eventId": eid, "eventType": etype, "occurredAt": f["updated"],
                "title": f"{label} · {form}" + (f" (Item {item})" if item else ""),
                "summary": re.sub(r"<[^>]+>", " ", f["summary"]).strip()[:300] or None,
                "sourceUrl": f["href"], "market": "US",
            }
            otype = "EarningsEvent" if etype == "EARNINGS" else "DisclosureEvent"
            if otype == "DisclosureEvent":
                base.update({"rcpNo": f["accession"], "filingType": form, "filingDetail": item})
            store.append_object("source", otype, base)
            store.append_link("source", LinkRecord(
                "eventAffectsInstrument", otype, eid, "Instrument", inst["instrumentId"],
                {"relevance": 1.0, "method": "DIRECT"}))
            added += 1
        print(f"  EDGAR {inst['ticker']}: 누적 +{added}")
    return {"added": added, "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    args = ap.parse_args()

    store = OntologyStore().build()
    print("▶ DART 백필")
    d = backfill_dart(store, args.years)
    print("▶ EDGAR 백필")
    e = backfill_edgar(store)
    print("▶ 매크로 백필")
    old_lookback = process.MACRO_LOOKBACK_DAYS
    process.MACRO_LOOKBACK_DAYS = 365 * args.years
    store = OntologyStore().build()
    m = process.generate_macro_events(store)
    process.MACRO_LOOKBACK_DAYS = old_lookback
    print(f"완료: DART +{d['added']}, EDGAR +{e['added']}, 매크로 +{m}")
    if d["errors"] or e["errors"]:
        print("오류:", (d["errors"] + e["errors"])[:5])


if __name__ == "__main__":
    main()
