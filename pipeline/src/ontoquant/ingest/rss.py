"""RSS 뉴스 — Yahoo per-ticker(US) + DART todayRSS(KR) → NewsEvent.

브라우저 UA 필수. 실패 시 조용히 스킵 (뉴스는 보조 신호).
"""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest.http import BROWSER_UA, get

YAHOO_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"


def _hash_id(link: str) -> str:
    return hashlib.sha1(link.encode()).hexdigest()[:12]


def _parse_pubdate(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return None


def fetch_yahoo(ticker: str) -> list[dict]:
    resp = get(YAHOO_URL, params={"s": ticker, "region": "US", "lang": "en-US"},
               headers={"User-Agent": BROWSER_UA}, retries=2, backoff=5.0)
    root = ET.fromstring(resp.content)
    out = []
    for item in root.iter("item"):
        link = item.findtext("link") or ""
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        out.append({
            "link": link, "title": title,
            "description": (item.findtext("description") or "").strip()[:300] or None,
            "pubDate": _parse_pubdate(item.findtext("pubDate")),
        })
    return out


def run(store: OntologyStore, today: date | None = None) -> dict:
    existing = {e["eventId"] for e in store.query("Event")}
    added, errors = 0, []
    us_tickers = [(i["ticker"], i["instrumentId"], i.get("nameKo") or i["name"])
                  for i in store.query("Instrument")
                  if i["currency"] == "USD" and i["assetClass"] == "EQUITY"]
    for idx, (ticker, iid, label) in enumerate(us_tickers):
        if idx:
            time.sleep(2.0)  # Yahoo 429 완화
        try:
            items = fetch_yahoo(ticker)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ticker}: {exc}")
            continue
        for it in items:
            eid = f"rss:yahoo:{_hash_id(it['link'])}"
            if eid in existing:
                continue
            existing.add(eid)
            store.append_object("source", "NewsEvent", {
                "eventId": eid, "eventType": "NEWS",
                "occurredAt": it["pubDate"] or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "title": it["title"],
                "summary": re.sub(r"<[^>]+>", " ", it["description"] or "").strip() or None,
                "sourceUrl": it["link"],
                "publisher": "Yahoo Finance", "feedSource": "YAHOO_RSS", "tickerHint": ticker,
            })
            store.append_link("source", LinkRecord(
                "eventAffectsInstrument", "NewsEvent", eid, "Instrument", iid,
                {"relevance": 0.9, "method": "DIRECT"}))
            added += 1
    return {"status": "partial" if errors else "ok", "added": added, "errors": errors[:3]}
