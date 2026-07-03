"""언론 RSS (매일경제 증권 등, 키리스) — 유니버스 종목이 언급된 기사만 저장.

정보량 조절: 종목 언급 없는 시황성 기사는 버린다 (네이버 종목 뉴스가 주력,
여기는 교차 언급/복수 종목 기사 보강용). 언급 매칭 = nameKo 부분 문자열.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import date, timezone
from email.utils import parsedate_to_datetime

from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest.http import BROWSER_UA, get

FEEDS = [
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
]


def _parse_items(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        pub = item.findtext("pubDate")
        occurred = None
        if pub:
            try:
                occurred = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001
                pass
        out.append({
            "title": title, "link": link, "occurredAt": occurred,
            "description": re.sub(r"<[^>]+>", " ", item.findtext("description") or "").strip()[:300] or None,
        })
    return out


def run(store: OntologyStore, today: date | None = None) -> dict:
    kr_names = [
        (inst.get("nameKo") or inst["name"], inst["instrumentId"])
        for inst in store.query("Instrument", where={"market": "KRX", "assetClass": "EQUITY"})
    ]
    existing = {e["eventId"] for e in store.query("Event")}
    added, errors = 0, []
    for feed_name, url in FEEDS:
        try:
            items = _parse_items(get(url, headers={"User-Agent": BROWSER_UA}).content)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{feed_name}: {exc}")
            continue
        for it in items:
            text = f"{it['title']} {it['description'] or ''}"
            mentioned = [(name, iid) for name, iid in kr_names if name and name in text]
            if not mentioned:
                continue  # 종목 언급 없는 시황 기사는 저장하지 않는다 (정보량 조절)
            eid = f"press:{hashlib.sha1(it['link'].encode()).hexdigest()[:12]}"
            if eid in existing:
                continue
            existing.add(eid)
            store.append_object("source", "NewsEvent", {
                "eventId": eid, "eventType": "NEWS",
                "occurredAt": it["occurredAt"] or f"{today or date.today()}T00:00:00+00:00",
                "title": it["title"], "summary": it["description"],
                "sourceUrl": it["link"], "publisher": feed_name,
                "feedSource": "PRESS_RSS",
            })
            for name, iid in mentioned[:4]:
                store.append_link("source", LinkRecord(
                    "eventAffectsInstrument", "NewsEvent", eid, "Instrument", iid,
                    {"relevance": 0.7, "method": "MAPPING"}))
            added += 1
    return {"status": "partial" if errors else "ok", "added": added, "errors": errors[:2]}
