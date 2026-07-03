"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { EventView } from "@/lib/data";

const TYPE_TABS: { key: string; label: string }[] = [
  { key: "ALL", label: "전체" },
  { key: "DisclosureEvent", label: "공시" },
  { key: "EarningsEvent", label: "실적" },
  { key: "MacroEvent", label: "매크로" },
  { key: "NewsEvent", label: "뉴스" },
];

export default function EventFilter({ events }: { events: EventView[] }) {
  const [tab, setTab] = useState("ALL");
  const [minImpact, setMinImpact] = useState(false);
  const filtered = useMemo(
    () => events
      .filter((e) => tab === "ALL" || e.objectType === tab)
      .filter((e) => !minImpact || (e.impact?.portfolioImpactScore ?? 0) > 0.005),
    [events, tab, minImpact],
  );

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24 }}>
        {TYPE_TABS.map((t) => (
          <button key={t.key} className="pill pill-tab" data-active={tab === t.key} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
        <button className="pill pill-tab" data-active={minImpact} onClick={() => setMinImpact(!minImpact)}
                style={{ marginLeft: "auto" }}>
          포트폴리오 영향만
        </button>
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        {filtered.map((e) => (
          <article key={e.eventId} className="hairline-card" style={{ padding: 20 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="caption" style={{
                background: "var(--block-pink)", padding: "3px 10px", borderRadius: 999,
              }}>
                {e.eventType}
              </span>
              <span className="caption">{e.occurredAt?.slice(0, 16).replace("T", " ")}</span>
              {e.severity != null && (
                <span className="caption">심각도 {(e.severity * 100).toFixed(0)}</span>
              )}
              {e.impact && e.impact.portfolioImpactScore > 0 && (
                <span className="caption" style={{ fontWeight: 700 }}>
                  영향도 {(e.impact.portfolioImpactScore * 100).toFixed(2)}
                </span>
              )}
            </div>
            <h2 className="body-lg" style={{ fontWeight: 540, margin: "10px 0 4px" }}>
              <Link href={`/graph/?focus=${encodeURIComponent(e.eventId)}`}>{e.title}</Link>
            </h2>
            {e.summary && <p className="body-sm" style={{ maxWidth: 780, opacity: 0.85 }}>{e.summary}</p>}
            {e.impact && e.impact.topPositions?.length > 0 && (
              <p className="body-sm" style={{ marginTop: 10 }}>
                전파: {e.impact.topPositions.slice(0, 4).map((t) =>
                  `${t.label} (${(t.score * 100).toFixed(2)})`).join(" · ")}
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
    </div>
  );
}
