"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { EventView } from "@/lib/data";

const TYPE_TABS: { key: string; label: string }[] = [
  { key: "ALL", label: "전체" },
  { key: "DisclosureEvent", label: "공시" },
  { key: "EarningsEvent", label: "실적" },
  { key: "MacroEvent", label: "시장 지표" },
  { key: "NewsEvent", label: "뉴스" },
];

const PAGE = 40;

function SentimentPill({ v }: { v?: number | null }) {
  if (v == null) return null;
  if (v > 0.25) {
    return <span className="caption" style={{ background: "var(--block-mint)", padding: "2px 10px", borderRadius: 999 }}>긍정</span>;
  }
  if (v < -0.25) {
    return <span className="caption" style={{ background: "var(--block-pink)", padding: "2px 10px", borderRadius: 999 }}>부정</span>;
  }
  return null;
}

export default function EventFilter({ events }: { events: EventView[] }) {
  const [tab, setTab] = useState("ALL");
  const [minImpact, setMinImpact] = useState(true);
  const [sortImpact, setSortImpact] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const filtered = useMemo(() => {
    const list = events
      .filter((e) => tab === "ALL" || e.objectType === tab)
      .filter((e) => !minImpact || (e.impact?.portfolioImpactScore ?? 0) > 0.001
        || Math.abs(e.sentiment ?? 0) > 0.5);
    if (sortImpact) {
      return [...list].sort((a, b) =>
        (b.impact?.portfolioImpactScore ?? 0) - (a.impact?.portfolioImpactScore ?? 0));
    }
    return list; // export 기본 정렬 = 최신순
  }, [events, tab, minImpact, sortImpact]);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24 }}>
        {TYPE_TABS.map((t) => (
          <button key={t.key} className="pill pill-tab" data-active={tab === t.key} aria-pressed={tab === t.key}
                  onClick={() => { setTab(t.key); setLimit(PAGE); }}>
            {t.label}
          </button>
        ))}
        <button className="pill pill-tab" data-active={sortImpact} aria-pressed={sortImpact}
                onClick={() => setSortImpact(!sortImpact)} style={{ marginLeft: "auto" }}>
          {sortImpact ? "영향 큰 순" : "최신순"}
        </button>
        <button className="pill pill-tab" data-active={minImpact} aria-pressed={minImpact}
                onClick={() => setMinImpact(!minImpact)}>
          핵심만
        </button>
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        {filtered.slice(0, limit).map((e) => (
          <article key={e.eventId} className="hairline-card" style={{ padding: 20 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="caption" style={{ background: "var(--block-pink)", padding: "3px 10px", borderRadius: 999 }}>
                {e.eventType}
              </span>
              <SentimentPill v={e.sentiment} />
              <span className="caption">{e.occurredAt?.slice(0, 16).replace("T", " ")}</span>
              {e.publisher && <span className="caption">{e.publisher}</span>}
              {(e.dupCount ?? 0) > 0 && (
                <span className="caption">비슷한 기사 {e.dupCount}건 묶음</span>
              )}
              {e.impact && e.impact.portfolioImpactScore > 0 && (
                <span className="caption" style={{ fontWeight: 700 }}>
                  영향 {(e.impact.portfolioImpactScore * 100).toFixed(2)}
                </span>
              )}
            </div>
            <h2 className="body-lg" style={{ fontWeight: 540, margin: "10px 0 4px" }}>
              <Link href={`/graph/?focus=${encodeURIComponent(e.eventId)}`}>{e.title}</Link>
            </h2>
            {e.summary && <p className="body-sm" style={{ maxWidth: 780, opacity: 0.85 }}>{e.summary}</p>}
            {e.impact && e.impact.topPositions?.length > 0 && (
              <p className="body-sm" style={{ marginTop: 10 }}>
                닿는 곳: {e.impact.topPositions.slice(0, 4).map((t) => t.label).join(" · ")}
              </p>
            )}
            <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
              <Link href={`/graph/?focus=${encodeURIComponent(e.eventId)}`} className="caption link-strong">
                전파 경로 →
              </Link>
              {e.sourceUrl && (
                <a href={e.sourceUrl} target="_blank" rel="noreferrer" className="caption">원문 ↗</a>
              )}
            </div>
          </article>
        ))}
      </div>
      {filtered.length > limit && (
        <button className="pill pill-secondary" style={{ marginTop: 20 }}
                onClick={() => setLimit(limit + PAGE)}>
          더 보기 ({filtered.length - limit}건 남음)
        </button>
      )}
    </div>
  );
}
