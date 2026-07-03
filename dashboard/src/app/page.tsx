import Link from "next/link";
import { BreachBadge, ValidationBadge } from "@/components/Badge";
import ExposureBars from "@/components/ExposureBars";
import Tooltip from "@/components/Tooltip";
import { DrawdownChart, PortfolioValueChart } from "@/components/ValueChart";
import {
  loadEvents, loadExposures, loadInsights, loadMeta, loadPortfolio,
  loadRiskMetrics, loadRiskSeries, loadSectors,
} from "@/lib/data";
import { fmtKrw, fmtLocal, fmtPct, signClass } from "@/lib/format";

const METRIC_TILES: Record<string, { label: string; fmt: (v: number) => string; tip: string }> = {
  VAR_95_1D: {
    label: "하루 위험액", fmt: (v) => fmtPct(v, 2),
    tip: "하루 동안 95% 확률로 이 비율 이상 잃지 않는 수준입니다. 최근 250일 실제 등락으로 계산합니다.",
  },
  VOL_30D: {
    label: "출렁임 (연환산)", fmt: (v) => fmtPct(v, 1),
    tip: "최근 30일 일간 등락 폭을 1년치로 환산한 값입니다. 클수록 가격이 크게 흔들립니다.",
  },
  MDD_1Y: {
    label: "1년 최대 하락", fmt: (v) => fmtPct(v, 1),
    tip: "지난 1년 중 고점에서 저점까지 가장 크게 빠졌던 폭입니다.",
  },
  HHI: {
    label: "쏠림 지수", fmt: (v) => v.toFixed(3),
    tip: "한 종목에 몰려 있을수록 커집니다. 골고루 나누면 낮아집니다 (비중 제곱의 합).",
  },
  BETA_MKT: {
    label: "시장 민감도", fmt: (v) => v.toFixed(2),
    tip: "기준 지수(SPY)가 1% 움직일 때 내 포트폴리오가 평균 몇 % 움직이는지입니다.",
  },
};

function SentimentPill({ v }: { v?: number | null }) {
  if (v == null) return null;
  const positive = v > 0.25;
  const negative = v < -0.25;
  if (!positive && !negative) return null;
  return (
    <span className="caption" style={{
      background: positive ? "var(--block-mint)" : "var(--block-pink)",
      padding: "2px 10px", borderRadius: 999,
    }}>
      {positive ? "긍정" : "부정"}
    </span>
  );
}

export default function HomePage() {
  const meta = loadMeta();
  const { portfolio, positions } = loadPortfolio();
  const metrics = loadRiskMetrics().filter((m) => m.scopeType === "PORTFOLIO");
  const series = loadRiskSeries();
  const insights = loadInsights()
    .filter((i) => i.validationStatus !== "REJECTED")
    .sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0))
    .slice(0, 4);
  const exposures = loadExposures();
  const sectors = loadSectors().filter((s) => s.weight > 0).slice(0, 5);
  const signals = loadEvents()
    .filter((e) => (e.impact?.portfolioImpactScore ?? 0) > 0 || Math.abs(e.sentiment ?? 0) > 0.5)
    .sort((a, b) => (b.impact?.portfolioImpactScore ?? 0) - (a.impact?.portfolioImpactScore ?? 0))
    .slice(0, 5);
  const pnl = portfolio.dailyPnlBase ?? 0;
  const pnlPct = portfolio.totalValueBase ? pnl / (portfolio.totalValueBase - pnl) : 0;
  const maxHoldings = portfolio.riskLimits?.maxHoldings;

  return (
    <div className="container">
      {/* 히어로 */}
      <section className="section" style={{ marginTop: 72 }}>
        <div className="eyebrow reveal reveal-1">{portfolio.name} · {meta.asOf ?? ""}</div>
        <h1 className="display-xl tabular reveal reveal-2" style={{ margin: "20px 0 12px" }}>
          {fmtKrw(portfolio.totalValueBase)}
        </h1>
        <p className={`body-lg reveal reveal-3 ${signClass(pnl)}`} style={{ fontWeight: 480 }}>
          {pnl >= 0 ? "▲" : "▼"} 오늘 {fmtKrw(Math.abs(pnl))} ({fmtPct(pnlPct, 2, true)})
        </p>
        <div className="reveal reveal-4" style={{ display: "flex", gap: 12, marginTop: 28 }}>
          <Link href="/graph/" className="pill pill-primary">무엇이 내 포트폴리오를 움직이나</Link>
          <Link href="/insights/" className="pill pill-secondary">지금 할 일 보기</Link>
        </div>
      </section>

      {/* 리스크 타일 */}
      <section className="section-sm grid-tiles">
        {metrics
          .sort((a, b) => Object.keys(METRIC_TILES).indexOf(a.metricType) - Object.keys(METRIC_TILES).indexOf(b.metricType))
          .map((m) => {
            const def = METRIC_TILES[m.metricType];
            if (!def) return null;
            return (
              <div key={m.metricId} className="hairline-card">
                <div className="caption" style={{ marginBottom: 10, display: "flex", alignItems: "center" }}>
                  {def.label}<Tooltip text={def.tip} />
                </div>
                <div className="card-title mono-num" style={{ fontSize: 30 }}>{def.fmt(m.value)}</div>
                <div className="body-sm" style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  {m.limitBreached && <BreachBadge />}
                  {m.limitValue != null && (
                    <span className="caption">한도 {def.fmt(m.limitValue)}</span>
                  )}
                </div>
              </div>
            );
          })}
      </section>

      {/* 라임 색블록: 지금 할 일 */}
      <section className="section">
        <div className="color-block" style={{ background: "var(--block-lime)" }}>
          <div className="eyebrow">TODAY</div>
          <h2 className="display-lg" style={{ margin: "16px 0 28px" }}>지금 확인할 것</h2>
          {insights.length === 0 ? (
            <p className="subhead">지금은 특별히 확인할 것이 없습니다. 매일 아침 자동으로 갱신됩니다.</p>
          ) : (
            <div style={{ display: "grid", gap: 16, maxWidth: 860 }}>
              {insights.map((ins) => (
                <div key={ins.insightId} style={{ borderTop: "1px solid #00000022", paddingTop: 16 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="headline" style={{ fontSize: 21 }}>{ins.title}</span>
                    <ValidationBadge status={ins.validationStatus} summary={ins.validationSummary} />
                  </div>
                  <p className="body" style={{ marginTop: 6, maxWidth: 720 }}>{ins.narrative}</p>
                  {ins.recommendedAction?.label && (
                    <p className="body-sm" style={{ marginTop: 8, fontWeight: 640 }}>
                      → {ins.recommendedAction.label}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
          <Link href="/insights/" className="pill pill-primary" style={{ marginTop: 28 }}>
            전체 보기
          </Link>
        </div>
      </section>

      {/* 오늘의 시장 신호 (뉴스/이벤트) */}
      <section className="section">
        <div className="flex-between" style={{ marginBottom: 20 }}>
          <h2 className="headline">오늘의 시장 신호</h2>
          <Link href="/events/" className="caption link-strong">전체 이벤트 →</Link>
        </div>
        {signals.length === 0 ? (
          <p className="body">최근 신호가 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {signals.map((e) => (
              <div key={e.eventId} className="flex-between"
                   style={{ borderBottom: "1px solid var(--hairline-soft)", paddingBottom: 10 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <Link href={`/graph/?focus=${encodeURIComponent(e.eventId)}`}
                        className="body link-strong">
                    {e.title}
                  </Link>
                  <SentimentPill v={e.sentiment} />
                </div>
                <span className="caption" style={{ whiteSpace: "nowrap" }}>
                  {e.occurredAt?.slice(5, 10)}
                  {e.impact && e.impact.portfolioImpactScore > 0.001
                    ? ` · 영향 ${(e.impact.portfolioImpactScore * 100).toFixed(1)}`
                    : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 가치/낙폭 차트 */}
      {series && (
        <section className="section">
          <div className="flex-between" style={{ marginBottom: 24 }}>
            <h2 className="headline">포트폴리오 가치 · 최근 1년</h2>
            <span className="caption">원화 기준</span>
          </div>
          <PortfolioValueChart series={series} />
          <div style={{ marginTop: 32 }}>
            <div className="caption" style={{ marginBottom: 12, display: "flex", alignItems: "center" }}>
              고점 대비 하락
              <Tooltip text="그동안의 최고점에서 얼마나 내려왔는지입니다. 0%면 신고가 상태입니다." />
            </div>
            <DrawdownChart series={series} />
          </div>
        </section>
      )}

      {/* 크림 색블록: 섹터 한눈에 */}
      <section className="section">
        <div className="color-block" style={{ background: "var(--block-cream)" }}>
          <div className="eyebrow">SECTORS</div>
          <h2 className="headline" style={{ margin: "12px 0 24px" }}>내 돈이 실린 산업</h2>
          <div style={{ display: "grid", gap: 10, maxWidth: 620 }}>
            {sectors.map((s) => (
              <div key={s.sectorId} style={{ display: "grid", gridTemplateColumns: "110px 1fr 64px", gap: 12, alignItems: "center" }}>
                <span className="body-sm" style={{ fontWeight: 480 }}>{s.nameKo}</span>
                <div style={{ height: 12, background: "#00000012", borderRadius: 6, position: "relative" }}>
                  <div style={{
                    position: "absolute", inset: 0,
                    width: `${(s.weight / (sectors[0]?.weight || 1)) * 100}%`,
                    background: "var(--ink)", borderRadius: 6,
                  }} />
                </div>
                <span className="mono-num body-sm" style={{ textAlign: "right" }}>{fmtPct(s.weight, 1)}</span>
              </div>
            ))}
          </div>
          <Link href="/sectors/" className="pill pill-primary" style={{ marginTop: 24 }}>
            섹터별 자세히
          </Link>
        </div>
      </section>

      {/* 포지션 테이블 */}
      <section className="section">
        <div className="flex-between" style={{ marginBottom: 20 }}>
          <h2 className="headline">보유 종목 {positions.length}</h2>
          {maxHoldings != null && (
            <span className="caption" style={{ display: "inline-flex", alignItems: "center" }}>
              개별주 {positions.filter((p) => !["SPY", "QQQ"].includes(p.instrument.ticker ?? "")).length}
              /{maxHoldings}
              <Tooltip text="지수 ETF를 뺀 개별 주식 보유 수입니다. 한도를 넘는 신규 편입은 자동으로 막힙니다." />
            </span>
          )}
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>종목</th><th>섹터</th>
                <th className="num">수량</th><th className="num">현재가</th>
                <th className="num">평가액(₩)</th><th className="num">비중</th>
                <th className="num">오늘 손익</th><th className="num">수익률</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.positionId}>
                  <td>
                    <Link href={`/instruments/${p.instrumentId.replace(/:/g, "_")}/`} className="link-strong">
                      {p.instrument.nameKo ?? p.instrument.name}
                    </Link>
                    <span className="caption" style={{ marginLeft: 8 }}>{p.instrument.ticker}</span>
                  </td>
                  <td className="body-sm">{p.instrument.sector}</td>
                  <td className="num mono-num">{p.quantity.toLocaleString()}</td>
                  <td className="num mono-num">{fmtLocal(p.lastPriceLocal, p.instrument.currency)}</td>
                  <td className="num mono-num">{fmtKrw(p.marketValueBase)}</td>
                  <td className="num mono-num">{fmtPct(p.weight, 1)}</td>
                  <td className={`num mono-num ${signClass(p.dailyPnlBase)}`}>{fmtKrw(p.dailyPnlBase, true)}</td>
                  <td className={`num mono-num ${signClass(p.unrealizedPnlPct)}`}>{fmtPct(p.unrealizedPnlPct, 1, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 네이비 색블록: 팩터 */}
      <section className="section">
        <div className="color-block color-block--navy" style={{ background: "var(--block-navy)" }}>
          <div className="eyebrow" style={{ color: "#ffffffb0" }}>FACTORS</div>
          <h2 className="display-lg" style={{ margin: "16px 0 20px" }}>
            내 포트폴리오를<br />흔드는 힘
          </h2>
          <div style={{ maxWidth: 640, background: "#ffffff14", borderRadius: 16, padding: 24 }}>
            <ExposureBars exposures={exposures.portfolio} inverse />
          </div>
          <p className="body-sm" style={{ marginTop: 16, color: "#ffffffb0", maxWidth: 640 }}>
            오른쪽 값이 클수록 그 힘이 1% 움직일 때 내 포트폴리오도 그만큼 따라 움직입니다.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
            <Link href="/graph/" className="pill" style={{ background: "#fff", color: "#000" }}>연결 그래프</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
