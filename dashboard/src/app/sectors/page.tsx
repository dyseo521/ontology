import Link from "next/link";
import Tooltip from "@/components/Tooltip";
import { loadInsights, loadPortfolio, loadSectors } from "@/lib/data";
import { fmtPct } from "@/lib/format";

const TOKEN_BG: Record<string, string> = {
  "block-lime": "var(--block-lime)", "block-lilac": "var(--block-lilac)",
  "block-cream": "var(--block-cream)", "block-pink": "var(--block-pink)",
  "block-mint": "var(--block-mint)", "block-coral": "var(--block-coral)",
  "block-navy": "var(--block-navy)",
};

export default function SectorsPage() {
  const sectors = loadSectors();
  const insights = new Map(loadInsights().map((i) => [i.insightId, i]));
  const maxSectorWeight = loadPortfolio().portfolio.riskLimits?.maxSectorWeight;
  const held = sectors.filter((s) => s.weight > 0);
  const maxW = Math.max(...held.map((s) => s.weight), 0.001);

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">SECTORS</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>섹터</h1>
        <p className="body-lg" style={{ maxWidth: 700 }}>
          내 돈이 어느 산업에 얼마나 실려 있고, 지금 어디서 신호가 나오는지 봅니다.
          {maxSectorWeight && <> 섹터당 한도는 {fmtPct(maxSectorWeight, 0)}입니다.</>}
        </p>
      </section>

      <section className="section-sm" style={{ display: "grid", gap: 16 }}>
        {held.map((s) => {
          const over = maxSectorWeight != null && s.weight > maxSectorWeight;
          const accent = TOKEN_BG[s.colorToken ?? ""] ?? "var(--surface-soft)";
          const navy = s.colorToken === "block-navy";
          const sectorInsights = s.insightIds.map((id) => insights.get(id)).filter(Boolean);
          return (
            <article key={s.sectorId} className="hairline-card"
                     style={{ display: "grid", gap: 14 }}>
              <div className="flex-between">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{
                    width: 34, height: 34, borderRadius: 10, background: accent,
                    border: "1px solid #00000018",
                  }} />
                  <h2 className="card-title">{s.nameKo ?? s.name}</h2>
                  {over && <span className="badge badge--breach">한도 초과</span>}
                  {s.recentEvents > 0 && (
                    <span className="caption">최근 7일 신호 {s.recentEvents}건</span>
                  )}
                </div>
                <div className="mono-num" style={{ fontSize: 26, fontWeight: 640 }}>
                  {fmtPct(s.weight, 1)}
                </div>
              </div>

              <div style={{ position: "relative", height: 12, background: "#00000010", borderRadius: 6 }}>
                <div style={{
                  position: "absolute", inset: 0, width: `${(s.weight / maxW) * 100}%`,
                  background: navy ? "var(--block-navy)" : accent, borderRadius: 6,
                  border: "1px solid #00000014",
                }} />
                {maxSectorWeight != null && maxSectorWeight <= maxW && (
                  <div title="섹터 한도"
                       style={{ position: "absolute", left: `${(maxSectorWeight / maxW) * 100}%`,
                                top: -3, bottom: -3, width: 2, background: "var(--ink)" }} />
                )}
              </div>

              <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
                {s.members.map((m) => (
                  <Link key={m.instrumentId} className="body-sm link-strong"
                        href={`/instruments/${m.instrumentId.replace(/:/g, "_")}/`}>
                    {m.name} <span className="caption">{fmtPct(m.weight, 1)}</span>
                  </Link>
                ))}
                <span className="body-sm" style={{ marginLeft: "auto", opacity: 0.75 }}>
                  손실 기여
                  <Tooltip text="포트폴리오가 하루 크게 잃을 때 이 섹터가 차지하는 몫입니다. 클수록 이 섹터가 손실을 주도합니다." />
                  {" "}{fmtPct(s.contribVar, 2)}
                </span>
              </div>

              {sectorInsights.length > 0 && (
                <div style={{ borderTop: "1px solid var(--hairline-soft)", paddingTop: 12 }}>
                  {sectorInsights.map((i) => i && (
                    <p key={i.insightId} className="body-sm" style={{ marginBottom: 4 }}>
                      <span style={{ fontWeight: 640 }}>{i.title}</span>
                      {i.recommendedAction?.label && (
                        <span className="caption" style={{
                          marginLeft: 10, background: "var(--block-lime)",
                          padding: "2px 10px", borderRadius: 999,
                        }}>
                          → {i.recommendedAction.label}
                        </span>
                      )}
                    </p>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
