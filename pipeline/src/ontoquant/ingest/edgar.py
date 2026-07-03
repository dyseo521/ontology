"""SEC EDGAR 8-K Atom 피드 → DisclosureEvent/EarningsEvent + 직접 링크.

UA 헤더(연락처 포함) 필수. CIK 별 최근 40건 조회 후 신규만 추가.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.events.classify import classify_edgar
from ontoquant.ingest.http import SEC_UA, get

URL = "https://www.sec.gov/cgi-bin/browse-edgar"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_filings(cik: str, form_type: str = "8-K", count: int = 40) -> list[dict]:
    resp = get(URL, params={
        "action": "getcompany", "CIK": cik, "type": form_type,
        "dateb": "", "owner": "include", "count": count, "output": "atom",
    }, headers={"User-Agent": SEC_UA})
    root = ET.fromstring(resp.content)
    out = []
    for entry in root.iter(f"{ATOM}entry"):
        title = entry.findtext(f"{ATOM}title") or ""
        updated = entry.findtext(f"{ATOM}updated") or ""
        link_el = entry.find(f"{ATOM}link")
        href = link_el.get("href") if link_el is not None else None
        summary = entry.findtext(f"{ATOM}summary") or ""
        accession = None
        m = re.search(r"accession[-_]?number=([\d-]+)", href or "")
        if m:
            accession = m.group(1)
        else:
            id_text = entry.findtext(f"{ATOM}id") or ""
            m2 = re.search(r"accession-number=([\d-]+)", id_text)
            accession = m2.group(1) if m2 else None
        out.append({"title": title, "updated": updated, "href": href,
                    "summary": summary, "accession": accession})
    return out


def run(store: OntologyStore, today: date | None = None) -> dict:
    existing = {e["eventId"] for e in store.query("Event")}
    added, errors = 0, []
    for inst in store.query("Instrument"):
        cik = inst.get("secCik")
        if not cik:
            continue
        try:
            filings = fetch_filings(cik)
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
                "eventAffectsInstrument", otype, eid,
                "Instrument", inst["instrumentId"],
                {"relevance": 1.0, "method": "DIRECT"}))
            added += 1
    return {"status": "partial" if errors else "ok", "added": added, "errors": errors[:3]}
