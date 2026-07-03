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


def enrich_events(store: OntologyStore) -> dict:
    """신규 이벤트(severity 없음)에 심각도/임베딩/뉴스 재분류/유사 링크 부여."""
    event_types = store.schema.interfaces["Event"].implementedBy
    todo: list[tuple[str, dict]] = []
    for e in store.query("Event"):
        if e.get("severity") is None or (emb.available() and e.get("embeddingId") is None):
            otype = store.get_type_of(e["eventId"], event_types)
            if otype:
                todo.append((otype, e))
    if not todo:
        return {"enriched": 0, "embedded": 0, "similarLinks": 0}

    embedded = similar_links = 0
    use_embed = emb.available()
    index = emb.EmbeddingIndex() if use_embed else None
    centroid_vecs: dict[str, np.ndarray] = {}
    if use_embed:
        keys = list(NEWS_CENTROIDS)
        vecs = emb.encode([NEWS_CENTROIDS[k] for k in keys])
        centroid_vecs = dict(zip(keys, vecs))

    new_ids: list[str] = []
    for otype, e in todo:
        text = f"{e['title']} {e.get('summary') or ''}".strip()
        updates = dict(e)
        if updates.get("severity") is None:
            updates["severity"] = sev.base_severity(e["eventType"])
        if use_embed and index is not None and not index.has(e["eventId"]):
            vec = emb.encode([text])[0]
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
                    updates["severity"] = sev.base_severity(best_type)
        if use_embed:
            updates["embeddingId"] = e["eventId"]
        store.append_object("source", otype, updates)

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

    return {"enriched": len(todo), "embedded": embedded, "similarLinks": similar_links}


def run(store: OntologyStore) -> dict:
    macro = generate_macro_events(store)
    enrich = enrich_events(store)
    return {"status": "ok", "macroEvents": macro, **enrich,
            "embeddings": "on" if emb.available() else "off (rules only)"}
