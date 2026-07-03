"""DART 지분 공시 방향 수집 — elestock(임원·주요주주) + majorstock(5%룰).

insider 알파(Cohen-Malloy-Pomorski 2012: 매수만·기회적만)의 원천.
두 API 모두 파라미터는 crtfc_key + corp_code 뿐 (전체 이력 반환, KR 21종목 × 2 = 일 42요청).

저장: 신규 타입 없이 기존 DisclosureEvent 에 rcept_no 로 조인해 방향 속성을 upsert.
list.json 에 없던 접수번호는 신규 DisclosureEvent 로 생성 (classify_dart 로 유형 판정).
routine 필터는 여기서 저장하지 않는다 — 알파 계산 시점에 PIT 판정 (소급 누출 방지).
"""
from __future__ import annotations

from datetime import date

from ontoquant.config import get_key
from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.events.classify import classify_dart
from ontoquant.ingest.fundamentals import _num
from ontoquant.ingest.http import get


def _direction(net: float | None) -> str:
    if net is None or net == 0:
        return "NEUTRAL"
    return "BUY" if net > 0 else "SELL"


def _fetch(endpoint: str, corp_code: str) -> list[dict]:
    doc = get(f"https://opendart.fss.or.kr/api/{endpoint}.json",
              params={"crtfc_key": get_key("DART_API_KEY"), "corp_code": corp_code}).json()
    if doc.get("status") == "013":
        return []
    if doc.get("status") != "000":
        raise RuntimeError(f"DART {endpoint} {doc.get('status')}: {doc.get('message')}")
    return doc.get("list", [])


def _rows_elestock(corp_code: str) -> list[dict]:
    out = []
    for r in _fetch("elestock", corp_code):
        net = _num(r.get("sp_stock_lmp_irds_cnt"))
        out.append({
            "rcpNo": r.get("rcept_no"), "rcept_dt": r.get("rcept_dt"),
            "ownerDirection": _direction(net),
            "ownerNetShares": net,
            "ownerNetRatio": _num(r.get("sp_stock_lmp_irds_rate")),
            "reporter": (r.get("repror") or "").strip() or None,
            "reporterRole": (r.get("isu_exctv_ofcps") or r.get("isu_main_shrholdr") or "").strip() or None,
            "corp_name": r.get("corp_name"),
            "kind": "임원ㆍ주요주주특정증권등소유상황보고서",
        })
    return out


def _rows_majorstock(corp_code: str) -> list[dict]:
    out = []
    for r in _fetch("majorstock", corp_code):
        net = _num(r.get("stkqy_irds"))
        out.append({
            "rcpNo": r.get("rcept_no"), "rcept_dt": r.get("rcept_dt"),
            "ownerDirection": _direction(net),
            "ownerNetShares": net,
            "ownerNetRatio": _num(r.get("stkrt_irds")),
            "reporter": (r.get("repror") or "").strip() or None,
            "reporterRole": (r.get("report_resn") or r.get("report_tp") or "").strip() or None,
            "corp_name": r.get("corp_name"),
            "kind": "주식등의대량보유상황보고서",
        })
    return out


def run(store: OntologyStore, today: date | None = None) -> dict:
    from ontoquant.ingest import corp_map
    corp_map.resolve_corp_codes(store)
    events_by_rcp = {}
    for e in store.query("DisclosureEvent"):
        if e.get("rcpNo"):
            events_by_rcp[e["rcpNo"]] = e
    updated, created, errors = 0, 0, []
    for inst in store.query("Instrument", where={"market": "KRX", "assetClass": "EQUITY"}):
        corp = inst.get("dartCorpCode")
        if not corp:
            continue
        try:
            rows = _rows_elestock(corp) + _rows_majorstock(corp)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst['ticker']}: {exc}")
            continue
        for r in rows:
            rcp = r["rcpNo"]
            if not rcp:
                continue
            props = {k: r[k] for k in ("ownerDirection", "ownerNetShares",
                                       "ownerNetRatio", "reporter", "reporterRole")}
            existing = events_by_rcp.get(rcp)
            if existing is not None:
                if existing.get("ownerDirection") == props["ownerDirection"] \
                        and existing.get("ownerNetShares") == props["ownerNetShares"]:
                    continue  # 이미 반영
                store.append_object("source", "DisclosureEvent", {**existing, **props})
                events_by_rcp[rcp] = {**existing, **props}
                updated += 1
            else:
                dt = (r.get("rcept_dt") or "").replace("-", "")  # "2024-08-01" 또는 "20240801"
                occurred = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}T09:00:00+09:00" if len(dt) == 8 else None
                if not occurred:
                    continue
                event = {
                    "eventId": f"dart:{rcp}", "rcpNo": rcp,
                    "eventType": classify_dart(r["kind"]),
                    "occurredAt": occurred,
                    "title": f"{r.get('corp_name') or inst.get('nameKo')} · {r['kind']}",
                    "sourceUrl": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}",
                    "market": "KR", "corpCode": corp,
                    "filingType": r["kind"][:60], **props,
                }
                store.append_object("source", "DisclosureEvent", event)
                store.append_link("source", LinkRecord(
                    "eventAffectsInstrument", "DisclosureEvent", event["eventId"],
                    "Instrument", inst["instrumentId"],
                    {"relevance": 1.0, "method": "DIRECT"}))
                events_by_rcp[rcp] = event
                created += 1
    return {"status": "partial" if errors else "ok",
            "updated": updated, "created": created, "errors": errors[:3]}
