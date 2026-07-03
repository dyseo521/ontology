"""KR 종목 뉴스 — 네이버 모바일 뉴스 API (키리스, 실호출 검증됨).

GET m.stock.naver.com/api/news/stock/{code}?pageSize=20&page=1
응답: [{total, items: [{id, officeId, articleId, officeName, datetime(YYYYMMDDHHMM),
       title(HTML escaped), body(요약), mobileNewsUrl, ...}]}]

정보량 조절: 종목당 최근 CAP 건, 동일 제목(3일 내) 사전 dedupe.
임베딩 기반 유사 기사 병합(dupCount)은 events/process 에서 수행.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone

from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.ingest.http import BROWSER_UA, get

URL = "https://m.stock.naver.com/api/news/stock/{code}"
CAP_PER_INSTRUMENT = 20
KST = timezone(timedelta(hours=9))


def _parse_dt(s: str) -> str | None:
    try:
        return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=KST).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return None


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def fetch_naver_news(code: str, page_size: int = CAP_PER_INSTRUMENT) -> list[dict]:
    resp = get(URL.format(code=code), params={"pageSize": page_size, "page": 1},
               headers={"User-Agent": BROWSER_UA})
    out = []
    for group in resp.json():
        for it in group.get("items", []):
            title = _clean(it.get("title"))
            if not title or not it.get("id"):
                continue
            out.append({
                "id": str(it["id"]),
                "title": title,
                "body": _clean(it.get("body"))[:300] or None,
                "publisher": it.get("officeName"),
                "occurredAt": _parse_dt(it.get("datetime", "")),
                "url": it.get("mobileNewsUrl"),
            })
    return out


def run(store: OntologyStore, today: date | None = None) -> dict:
    existing = {e["eventId"] for e in store.query("Event")}
    recent_titles = {
        (e.get("tickerHint"), e["title"]) for e in store.query("NewsEvent")
        if str(e.get("occurredAt") or "") >= (datetime.now(KST) - timedelta(days=3)).isoformat()
    }
    added, errors = 0, []
    for inst in store.query("Instrument", where={"market": "KRX", "assetClass": "EQUITY"}):
        try:
            items = fetch_naver_news(inst["ticker"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
            continue
        for it in items:
            eid = f"naver:{it['id']}"
            if eid in existing or (inst["ticker"], it["title"]) in recent_titles:
                continue
            existing.add(eid)
            recent_titles.add((inst["ticker"], it["title"]))
            store.append_object("source", "NewsEvent", {
                "eventId": eid, "eventType": "NEWS",
                "occurredAt": it["occurredAt"] or datetime.now(KST).isoformat(timespec="seconds"),
                "title": it["title"], "summary": it["body"],
                "sourceUrl": it["url"], "publisher": it["publisher"],
                "feedSource": "NAVER_NEWS", "tickerHint": inst["ticker"],
            })
            store.append_link("source", LinkRecord(
                "eventAffectsInstrument", "NewsEvent", eid,
                "Instrument", inst["instrumentId"],
                {"relevance": 0.9, "method": "DIRECT"}))
            added += 1
    return {"status": "partial" if errors else "ok", "added": added, "errors": errors[:3]}
