"""데이터 불균형 진단 — 기간·시장·타입 커버리지를 점검하고 시정 대상을 표시.

  python -m ontoquant.quality

산출: data/computed/quality.json (export 가 meta.json 에 요약 포함)
관점:
  1) 가격: 종목별 기간, 최신성 (7일 이상 미갱신 = stale)
  2) 이벤트: 시장×연도 매트릭스, 타입 편중, KR/US 균형 (겹치는 기간 기준)
  3) 뉴스: 커버 기간(구조적으로 최근만인지), 보유 종목 중 뉴스 0건
  4) 재무: 회사별 분기 수
  5) 이벤트 스터디 표본: n<10 이라 검증 불가한 타입
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta

import pandas as pd

from ontoquant import config
from ontoquant.core.store import OntologyStore
from ontoquant.ingest import tsio

STALE_DAYS = 7
EVENT_BALANCE_RATIO = 4.0


def run(store: OntologyStore | None = None, verbose: bool = True) -> dict:
    store = store or OntologyStore().build()
    today = date.today()
    flags: list[dict] = []

    def flag(severity: str, area: str, message: str, fix: str | None = None):
        flags.append({"severity": severity, "area": area, "message": message, "fix": fix})

    # ── 1) 가격 커버리지 ────────────────────────────────────────────
    prices = {}
    for inst in store.query("Instrument"):
        iid = inst["instrumentId"]
        df = tsio.read_ts(tsio.price_path(iid))
        if df is None or df.empty:
            prices[iid] = None
            flag("HIGH", "prices", f"{iid} 가격 데이터 없음", "ingest 실행")
            continue
        start, end = df["date"].min().date(), df["date"].max().date()
        prices[iid] = {"start": str(start), "end": str(end), "rows": len(df)}
        if (today - end).days > STALE_DAYS:
            flag("MED", "prices", f"{iid} 가격 {end} 이후 미갱신", "소스 상태 확인")

    # ── 2) 이벤트 분포 ──────────────────────────────────────────────
    events = store.query("Event")
    by_market_year: dict[tuple[str, str], int] = Counter()
    by_type: Counter = Counter()
    for e in events:
        occurred = str(e.get("occurredAt") or "")[:4]
        market = e.get("market") or ("KR" if str(e["eventId"]).startswith(("dart", "naver", "press")) else "US")
        if occurred:
            by_market_year[(market, occurred)] += 1
        by_type[e["eventType"]] += 1
    # 겹치는 기간(양쪽 모두 데이터가 있는 연도)의 KR/US 균형
    years = sorted({y for (_, y) in by_market_year})
    overlap = [y for y in years
               if by_market_year.get(("KR", y), 0) > 0 and by_market_year.get(("US", y), 0) > 0]
    kr_total = sum(by_market_year.get(("KR", y), 0) for y in overlap)
    us_total = sum(by_market_year.get(("US", y), 0) for y in overlap)
    if us_total and kr_total / max(us_total, 1) > EVENT_BALANCE_RATIO:
        top_kr = by_type.most_common(1)[0]
        flag("INFO", "events",
             f"KR 이벤트가 US 대비 {kr_total / us_total:.1f}배 (겹치는 기간). "
             f"최다 타입 {top_kr[0]} {top_kr[1]}건이 주 원인",
             "이벤트 스터디는 타입×시장별이라 통계 왜곡 없음. 전파는 severity 가중으로 완충")
    if by_type and events:
        dom_type, dom_n = by_type.most_common(1)[0]
        if dom_n / len(events) > 0.5:
            flag("INFO", "events", f"타입 편중: {dom_type} 이 전체의 {dom_n / len(events) * 100:.0f}%",
                 "절차성 공시(임원 보고 등)는 severity 가 낮아 인사이트에 과대 반영되지 않음")
    # 기간 비대칭 (매우 중요): 통계에 실제로 쓰이는 CAR 원장의 기간을 비교한다.
    # 원시 이벤트가 더 오래됐어도 가격 추정창이 없으면 원장에 못 들어가므로,
    # 원장 기준이 국면 정합성의 올바른 척도다.
    ledger_path = config.COMPUTED_DIR / "event_cars.parquet"
    if ledger_path.exists():
        ledger = pd.read_parquet(ledger_path)
        starts = {}
        for market, g in ledger.groupby("market"):
            starts[market] = pd.to_datetime(g["eventDate"]).min()
        if "KR" in starts and "US" in starts:
            gap_days = abs((starts["KR"] - starts["US"]).days)
            if gap_days > 400:
                later = "KR" if starts["KR"] > starts["US"] else "US"
                flag("MED", "events",
                     f"CAR 원장 기간 비대칭: KR {starts['KR'].date()} ~ vs US {starts['US'].date()} ~ "
                     f"(차이 {gap_days}일) — 통계가 다른 시장 국면 기반",
                     f"{later} 이벤트 백필 기간 확장 (backfill --years)")

    # ── 3) 뉴스 커버리지 ────────────────────────────────────────────
    news = store.query("NewsEvent")
    news_dates = sorted(str(n.get("occurredAt") or "")[:10] for n in news if n.get("occurredAt"))
    held = {p["instrumentId"] for p in store.query("Position") if p.get("quantity")}
    kr_held_equity = {i["instrumentId"] for i in store.query("Instrument", where={"market": "KRX", "assetClass": "EQUITY"})
                      if i["instrumentId"] in held}
    covered = set()
    for n in news:
        for nb in store.neighbors("NewsEvent", n["eventId"], "eventAffectsInstrument", "out"):
            covered.add(nb.pk)
    missing_news = sorted(kr_held_equity - covered)
    if news_dates:
        span_days = (pd.Timestamp(news_dates[-1]) - pd.Timestamp(news_dates[0])).days
        if span_days < 30:
            flag("INFO", "news", f"뉴스 커버 기간이 {span_days}일 (소스가 최근 기사만 제공)",
             "뉴스는 이벤트 스터디에서 제외되어 과거 통계를 오염시키지 않음. 매일 누적으로 자연 확장")
    for iid in missing_news:
        flag("MED", "news", f"보유 KR 종목 {iid} 뉴스 0건", "news_kr 수집 확인")

    # ── 4) 재무 커버리지 ────────────────────────────────────────────
    fund_by_company: dict[str, int] = defaultdict(int)
    for f in store.query("Fundamental"):
        fund_by_company[f["companyId"]] += 1
    company_inst = {r.fromPk: r.toPk for r in store.links("companyListedAs")}
    for cid, inst_id in company_inst.items():
        n = fund_by_company.get(cid, 0)
        if inst_id in held and n < 4:
            flag("MED", "fundamentals", f"{inst_id} 분기 재무 {n}건 (<4)", "fundamentals 백필")

    # ── 5) 이벤트 스터디 표본 ───────────────────────────────────────
    thin_types = []
    cars_path = config.COMPUTED_DIR / "event_cars.parquet"
    if cars_path.exists():
        cars = pd.read_parquet(cars_path)
        for (etype, market), g in cars.groupby(["eventType", "market"]):
            if len(g) < 10:
                thin_types.append({"eventType": etype, "market": market, "n": int(len(g))})

    report = {
        "asOf": str(today),
        "prices": prices,
        "eventsByMarketYear": {f"{m}:{y}": c for (m, y), c in sorted(by_market_year.items())},
        "eventTypeTop": by_type.most_common(12),
        "newsWindow": {"start": news_dates[0] if news_dates else None,
                       "end": news_dates[-1] if news_dates else None, "count": len(news)},
        "fundamentalsQuartersMedian": (
            int(pd.Series(list(fund_by_company.values())).median()) if fund_by_company else 0),
        "eventStudyThinTypes": thin_types,
        "flags": flags,
        "summary": {
            "highFlags": sum(1 for f in flags if f["severity"] == "HIGH"),
            "medFlags": sum(1 for f in flags if f["severity"] == "MED"),
            "infoFlags": sum(1 for f in flags if f["severity"] == "INFO"),
        },
    }
    config.COMPUTED_DIR.mkdir(parents=True, exist_ok=True)
    (config.COMPUTED_DIR / "quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    if verbose:
        print(f"데이터 품질 진단 ({today})")
        print(f"  가격: {sum(1 for v in prices.values() if v)} / {len(prices)} 종목")
        print(f"  이벤트 시장×연도: {report['eventsByMarketYear']}")
        print(f"  뉴스: {report['newsWindow']}")
        print(f"  검증 불가(표본<10) 타입: {len(thin_types)}")
        for f in flags:
            print(f"  [{f['severity']:4s}] {f['area']}: {f['message']}")
    return report


if __name__ == "__main__":
    run()
