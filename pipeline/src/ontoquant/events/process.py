"""이벤트 처리 스테이지 — 매크로 이벤트 생성 + 임베딩/분류/링크/심각도 보강.

작업 대상 = severity 가 아직 없는 이벤트 (신규). 보강 결과는 source 계층에
last-wins upsert 되므로 재실행해도 안전(idempotent).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ontoquant.core.store import LinkRecord, OntologyStore
from ontoquant.events import embed as emb
from ontoquant.events import severity as sev
from ontoquant.events.classify import NEWS_CENTROID_THRESHOLD, NEWS_CENTROIDS
from ontoquant.ingest import tsio

MACRO_Z_WINDOW = 252
MACRO_Z_MIN = 2.0
MACRO_LOOKBACK_DAYS = 10
SIMILAR_TOP_K = 3
SIMILAR_MIN = 0.85

MACRO_EVENT_TYPE = {
    "MACRO:DGS10": "RATE_SHOCK", "MACRO:DGS2": "RATE_SHOCK", "MACRO:T10Y2Y": "RATE_SHOCK",
    "MACRO:VIX": "VOL_SPIKE", "MACRO:HY_OAS": "CREDIT_SHOCK",
    "MACRO:USDKRW": "FX_SHOCK", "MACRO:WTI": "OIL_SHOCK",
}
MACRO_TITLE = {
    "RATE_SHOCK": "금리 급변동", "VOL_SPIKE": "변동성 급등", "CREDIT_SHOCK": "신용 스프레드 급변",
    "FX_SHOCK": "환율 급변동", "OIL_SHOCK": "유가 급변동",
}


def generate_macro_events(store: OntologyStore) -> int:
    """FRED 시리즈 일변화 z-score 트리거 → MacroEvent + eventDrivesFactor 링크."""
    existing = {e["eventId"] for e in store.query("Event")}
    added = 0
    for factor in store.query("Factor", where={"source": "FRED"}):
        fid = factor["factorId"]
        etype = MACRO_EVENT_TYPE.get(fid)
        if not etype:
            continue
        df = tsio.read_ts(tsio.factor_path(fid))
        if df is None or len(df) < MACRO_Z_WINDOW + MACRO_LOOKBACK_DAYS:
            continue
        level = df.set_index("date")["value"].astype(float)
        change = np.log(level).diff() if factor["transform"] == "LOGRET" else level.diff()
        z = (change - change.rolling(MACRO_Z_WINDOW).mean()) / change.rolling(MACRO_Z_WINDOW).std()
        recent = z.dropna().tail(MACRO_LOOKBACK_DAYS)
        for dt, zval in recent.items():
            if abs(zval) < MACRO_Z_MIN:
                continue
            date_str = str(pd.Timestamp(dt).date())
            eid = f"macro:{factor['sourceSeriesId']}:{date_str}"
            if eid in existing:
                continue
            existing.add(eid)
            val = float(level.loc[dt])
            store.append_object("source", "MacroEvent", {
                "eventId": eid, "eventType": etype,
                "occurredAt": f"{date_str}T00:00:00+00:00",
                "title": f"{MACRO_TITLE[etype]}: {factor.get('nameKo') or factor['name']} "
                         f"{'+' if zval > 0 else ''}{zval:.1f}σ ({val:,.2f})",
                "summary": f"{factor['sourceSeriesId']} 일간 변화가 252일 분포 대비 {zval:+.1f} 표준편차",
                "severity": sev.macro_severity(float(zval)),
                "seriesId": factor["sourceSeriesId"], "value": val,
                "change1d": float(change.loc[dt]), "zScore": round(float(zval), 2),
            })
            store.append_link("source", LinkRecord(
                "eventDrivesFactor", "MacroEvent", eid, "Factor", fid,
                {"relevance": 1.0, "method": "DIRECT"}))
            added += 1
    return added


SECTOR_CENTROIDS: dict[str, str] = {
    "IT": "반도체 메모리 전자 소프트웨어 클라우드 데이터센터 AI 칩 semiconductor chip software",
    "COMM": "인터넷 플랫폼 통신 미디어 콘텐츠 광고 게임 platform media telecom",
    "CD": "자동차 전기차 유통 소비 여행 의류 automobile retail consumer",
    "CS": "식품 음료 생활용품 필수소비재 food beverage staples",
    "HC": "제약 바이오 신약 임상 헬스케어 의료기기 pharma biotech clinical",
    "FIN": "은행 금융지주 증권 보험 금리 대출 bank finance insurance rates",
    "IND": "방산 조선 기계 건설 플랜트 철도 defense machinery construction",
    "MAT": "철강 화학 소재 배터리 양극재 steel chemicals materials battery",
    "ENE": "정유 석유 가스 에너지 원유 refinery oil gas energy",
    "UTIL": "전력 전기요금 원전 발전 유틸리티 utility power electricity",
}
SECTOR_LINK_THRESHOLD = 0.60
MACRO_SECTOR_MAP: dict[str, list[tuple[str, float]]] = {
    "RATE_SHOCK": [("FIN", 0.7), ("UTIL", 0.6)],
    "OIL_SHOCK": [("ENE", 0.8), ("IND", 0.5)],
    "FX_SHOCK": [("IT", 0.6), ("CD", 0.6)],
    "CREDIT_SHOCK": [("FIN", 0.7)],
}
DEDUPE_SIM = 0.95


def _link_macro_sectors(store: OntologyStore) -> int:
    """매크로 이벤트 → 섹터 결정적 매핑 (없는 링크만 추가)."""
    existing = {(r.fromPk, r.toPk) for r in store.links("eventAffectsSector")}
    added = 0
    for e in store.query("MacroEvent"):
        for sector_id, rel in MACRO_SECTOR_MAP.get(e["eventType"], []):
            if (e["eventId"], sector_id) in existing:
                continue
            store.append_link("source", LinkRecord(
                "eventAffectsSector", "MacroEvent", e["eventId"], "Sector", sector_id,
                {"relevance": rel, "method": "MAPPING"}))
            existing.add((e["eventId"], sector_id))
            added += 1
    return added


def enrich_events(store: OntologyStore) -> dict:
    """신규 이벤트 보강: 임베딩 → dedupe → 감성(뉴스) → 분류 → 심각도 → 섹터 링크."""
    from ontoquant.events import sentiment as senti

    event_types = store.schema.interfaces["Event"].implementedBy
    todo: list[tuple[str, dict]] = []
    for e in store.query("Event"):
        if e.get("severity") is None or (emb.available() and e.get("embeddingId") is None):
            otype = store.get_type_of(e["eventId"], event_types)
            if otype:
                todo.append((otype, e))
    sector_links = _link_macro_sectors(store)
    if not todo:
        return {"enriched": 0, "embedded": 0, "similarLinks": 0, "deduped": 0,
                "sectorLinks": sector_links}

    embedded = similar_links = deduped = 0
    use_embed = emb.available()
    index = emb.EmbeddingIndex() if use_embed else None
    centroid_vecs: dict[str, np.ndarray] = {}
    sector_vecs: dict[str, np.ndarray] = {}
    if use_embed:
        keys = list(NEWS_CENTROIDS)
        centroid_vecs = dict(zip(keys, emb.encode([NEWS_CENTROIDS[k] for k in keys])))
        skeys = list(SECTOR_CENTROIDS)
        sector_vecs = dict(zip(skeys, emb.encode([SECTOR_CENTROIDS[k] for k in skeys])))

    # 뉴스 감성 배치 (신규 NewsEvent 만)
    news_items = [(otype, e) for otype, e in todo
                  if otype == "NewsEvent" and e.get("sentiment") is None]
    sentiments: dict[str, tuple[float, str]] = {}
    if news_items:
        texts = [f"{e['title']} {e.get('summary') or ''}"[:400] for _, e in news_items]
        for (_, e), result in zip(news_items, senti.analyze(texts)):
            sentiments[e["eventId"]] = result

    dup_counts: dict[str, int] = {}
    new_ids: list[str] = []
    for otype, e in todo:
        text = f"{e['title']} {e.get('summary') or ''}".strip()
        updates = dict(e)
        vec = None
        if use_embed and index is not None and not index.has(e["eventId"]):
            vec = emb.encode([text])[0]
            # dedupe: 기존 뉴스와 0.95+ 유사 → 병합(삭제), 원본 dupCount 증가
            if otype == "NewsEvent":
                near = index.search(vec, top_k=1, exclude={e["eventId"]})
                if near and near[0][1] >= DEDUPE_SIM and near[0][0].startswith(("naver:", "press:", "rss:")):
                    store.delete_object("source", "NewsEvent", e["eventId"])
                    dup_counts[near[0][0]] = dup_counts.get(near[0][0], 0) + 1
                    deduped += 1
                    continue
            index.add([e["eventId"]], vec.reshape(1, -1))
            embedded += 1
            new_ids.append(e["eventId"])
            # 뉴스 2차 분류 (센트로이드)
            if otype == "NewsEvent" and e["eventType"] == "NEWS" and centroid_vecs:
                best_type, best_sim = None, 0.0
                for k, cv in centroid_vecs.items():
                    s = float(vec @ cv)
                    if s > best_sim:
                        best_type, best_sim = k, s
                if best_type and best_sim >= NEWS_CENTROID_THRESHOLD:
                    updates["eventType"] = best_type
            # 뉴스 → 섹터 임베딩 링크 (top-1, 임계 이상)
            if otype == "NewsEvent" and sector_vecs:
                best_sec, best_sim = None, 0.0
                for sid, sv in sector_vecs.items():
                    s = float(vec @ sv)
                    if s > best_sim:
                        best_sec, best_sim = sid, s
                if best_sec and best_sim >= SECTOR_LINK_THRESHOLD:
                    store.append_link("source", LinkRecord(
                        "eventAffectsSector", "NewsEvent", e["eventId"], "Sector", best_sec,
                        {"relevance": round(best_sim, 3), "method": "EMBEDDING"}))
                    sector_links += 1
        # 감성 (뉴스)
        if otype == "NewsEvent" and e["eventId"] in sentiments:
            score, label = sentiments[e["eventId"]]
            updates["sentiment"] = score
            updates["sentimentLabel"] = label
        # 심각도: 뉴스는 감성 강도 반영
        if updates.get("severity") is None:
            base = sev.base_severity(updates["eventType"])
            if otype == "NewsEvent":
                base = round(min(1.0, base + 0.35 * abs(updates.get("sentiment") or 0.0)), 3)
            updates["severity"] = base
        if use_embed:
            updates["embeddingId"] = e["eventId"]
        store.append_object("source", otype, updates)

    # dupCount 반영 (원본 뉴스)
    for canon_id, cnt in dup_counts.items():
        canon = store.get("NewsEvent", canon_id)
        if canon:
            store.append_object("source", "NewsEvent", {
                **canon, "dupCount": (canon.get("dupCount") or 0) + cnt})

    # 유사 이벤트 링크 (신규 이벤트만, 인덱스 전체 대상)
    if use_embed and index is not None:
        for eid in new_ids:
            vec = index.vector_of(eid)
            if vec is None:
                continue
            for other_id, score in index.search(vec, top_k=SIMILAR_TOP_K + 1, exclude={eid}):
                if score < SIMILAR_MIN:
                    break
                from_type = store.get_type_of(eid, event_types)
                to_type = store.get_type_of(other_id, event_types)
                if from_type and to_type:
                    store.append_link("source", LinkRecord(
                        "similarEvent", from_type, eid, to_type, other_id,
                        {"similarity": round(score, 3)}))
                    similar_links += 1
        index.save()

    return {"enriched": len(todo), "embedded": embedded, "similarLinks": similar_links,
            "deduped": deduped, "sectorLinks": sector_links,
            "sentimentAnalyzed": len(sentiments)}


def run(store: OntologyStore) -> dict:
    macro = generate_macro_events(store)
    enrich = enrich_events(store)
    return {"status": "ok", "macroEvents": macro, **enrich,
            "embeddings": "on" if emb.available() else "off (rules only)"}
