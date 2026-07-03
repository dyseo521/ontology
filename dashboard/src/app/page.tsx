import Link from "next/link";
import { BreachBadge, ValidationBadge } from "@/components/Badge";
import ExposureBars from "@/components/ExposureBars";
import { DrawdownChart, PortfolioValueChart } from "@/components/ValueChart";
import {
  loadEvents, loadExposures, loadInsights, loadMeta, loadPortfolio,
  loadRiskMetrics, loadRiskSeries,
} from "@/lib/data";
import { fmtKrw, fmtLocal, fmtPct, signClass } from "@/lib/format";

const METRIC_LABELS: Record<string, { label: string; fmt: (v: number) => string; desc: string }> = {
  VAR_95_1D: { label: "1일 VaR 95%", fmt: (v) => fmtPct(v, 2), desc: "Historical simulation 250d" },
  VOL_30D: { label: "30일 변동성(연율)", fmt: (v) => fmtPct(v, 1), desc: "일간 표준편차 ×√252" },
  MDD_1Y: { label: "1년 최대낙폭", fmt: (v) => fmtPct(v, 1), desc: "고점 대비" },
  HHI: { label: "집중도 HHI", fmt: (v) => v.toFixed(3), desc: "Σ 비중²" },
  BETA_MKT: { label: "벤치마크 베타", fmt: (v) => v.toFixed(2), desc: "vs SPY (KRW)" },
};

export default function HomePage() {
  const meta = loadMeta();
  const { portfolio, positions } = loadPortfolio();
  const metrics = loadRiskMetrics().filter((m) => m.scopeType === "PORTFOLIO");
  const series = loadRiskSeries();
  const insights = loadInsights().slice(0, 4);
  const exposures = loadExposures();
  const events = loadEvents().slice(0, 5);
  const pnl = portfolio.dailyPnlBase ?? 0;
  const pnlPct = portfolio.totalValueBase ? pnl / (portfolio.totalValueBase - pnl) : 0;

  return (
    <div className="container">
      {/* ── 히어로 ─────────────────────────────────────────── */}
      <section className="section" style={{ marginTop: 72 }}>
        <div className="eyebrow reveal reveal-1">PORTFOLIO · {portfolio.name} · AS OF {meta.asOf ?? "—"}</div>
        <h1 className="display-xl tabular reveal reveal-2" style={{ margin: "20px 0 12px" }}>
          {fmtKrw(portfolio.totalValueBase)}
        </h1>
        <p className={`body-lg reveal reveal-3 ${signClass(pnl)}`} style={{ fontWeight: 480 }}>
          {pnl >= 0 ? "▲" : "▼"} {fmtKrw(Math.abs(pnl))} ({fmtPct(pnlPct, 2, true)}) 오늘
        </p>
        <div className="reveal reveal-4" style={{ display: "flex", gap: 12, marginTop: 28 }}>
          <Link href="/graph/" className="pill pill-primary">전파 그래프 열기</Link>
          <Link href="/proposals/" className="pill pill-secondary">리밸런싱 제안</Link>
        </div>
      </section>

      {/* ── 리스크 타일 ────────────────────────────────────── */}
      <section className="section-sm grid-tiles">
        {metrics
          .sort((a, b) => Object.keys(METRIC_LABELS).indexOf(a.metricType) - Object.keys(METRIC_LABELS).indexOf(b.metricType))
          .map((m) => {
            const def = METRIC_LABELS[m.metricType];
            if (!def) return null;
            return (
              <div key={m.metricId} className="hairline-card">
                <div className="caption" style={{ marginBottom: 10 }}>{def.label}</div>
                <div className="card-title mono-num" style={{ fontSize: 30 }}>{def.fmt(m.value)}</div>
                <div className="body-sm" style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  {m.limitBreached ? <BreachBadge /> : <span style={{ opacity: 0.75 }}>{def.desc}</span>}
                  {m.limitValue != null && (
                    <span className="caption">한도 {def.fmt(m.limitValue)}</span>
                  )}
                </div>
              </div>
            );
          })}
      </section>

      {/* ── 라임 색블록: 리스크 브리핑 ───────────────────────── */}
      <section className="section">
        <div className="color-block" style={{ background: "var(--block-lime)" }}>
          <div className="eyebrow">RISK BRIEFING</div>
          <h2 className="display-lg" style={{ margin: "16px 0 28px" }}>오늘의 온톨로지가<br />말하는 것</h2>
          {insights.length === 0 ? (
            <p className="subhead">현재 활성 인사이트가 없습니다. 파이프라인이 매일 아침 갱신합니다.</p>
          ) : (
            <div style={{ display: "grid", gap: 16, maxWidth: 860 }}>
              {insights.map((ins) => (
                <div key={ins.insightId} style={{ borderTop: "1px solid #00000022", paddingTop: 16 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="headline" style={{ fontSize: 21 }}>{ins.title}</span>
                    <ValidationBadge status={ins.validationStatus} summary={ins.validationSummary} />
                  </div>
                  <p className="body" style={{ marginTop: 6, maxWidth: 720 }}>{ins.narrative}</p>
                </div>
              ))}
            </div>
          )}
          <Link href="/insights/" className="pill pill-primary" style={{ marginTop: 28 }}>
            인사이트 전체 보기
          </Link>
        </div>
      </section>

      {/* ── 가치/낙폭 차트 ─────────────────────────────────── */}
      {series && (
        <section className="section">
          <div className="flex-between" style={{ marginBottom: 24 }}>
            <h2 className="headline">포트폴리오 가치 · 최근 1년</h2>
            <span className="caption">기준통화 {portfolio.baseCurrency}</span>
          </div>
          <PortfolioValueChart series={series} />
          <div style={{ marginTop: 32 }}>
            <div className="caption" style={{ marginBottom: 12 }}>DRAWDOWN</div>
            <DrawdownChart series={series} />
          </div>
        </section>
      )}

      {/* ── 포지션 테이블 ──────────────────────────────────── */}
      <section className="section">
        <h2 className="headline" style={{ marginBottom: 20 }}>보유 포지션 {positions.length}</h2>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>종목</th><th>시장</th>
                <th className="num">수량</th><th className="num">현재가</th>
                <th className="num">평가액(₩)</th><th className="num">비중</th>
                <th className="num">일간손익</th><th className="num">평가수익률</th>
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
                  <td className="body-sm">{p.instrument.market}</td>
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

      {/* ── 크림 색블록: 팩터 익스포저 ───────────────────────── */}
      <section className="section">
        <div className="color-block" style={{ background: "var(--block-cream)" }}>
          <div className="eyebrow">FACTOR EXPOSURE</div>
          <h2 className="headline" style={{ margin: "12px 0 24px" }}>포트폴리오가 어떤 바람에 흔들리는가</h2>
          <div style={{ maxWidth: 640 }}>
            <ExposureBars exposures={exposures.portfolio} />
          </div>
          <p className="body-sm" style={{ marginTop: 20, opacity: 0.75 }}>
            베타 = 비중가중 롤링 OLS (252일). 상세 행렬은 종목 상세에서.
          </p>
        </div>
      </section>

      {/* ── 네이비 색블록: 이벤트 → 그래프 CTA ────────────────── */}
      <section className="section">
        <div className="color-block color-block--navy" style={{ background: "var(--block-navy)" }}>
          <div className="eyebrow" style={{ color: "#ffffffb0" }}>EVENT PROPAGATION</div>
          <h2 className="display-lg" style={{ margin: "16px 0 20px" }}>
            이 이벤트는 내 포트폴리오<br />어디에 전파되는가
          </h2>
          {events.length === 0 ? (
            <p className="subhead" style={{ color: "#ffffffd0", maxWidth: 720 }}>
              공시·실적·매크로 이벤트가 수집되면 종목→포지션→포트폴리오로 이어지는
              전파 경로가 그래프에 나타납니다.
            </p>
          ) : (
            <ul style={{ display: "grid", gap: 10, maxWidth: 760 }}>
              {events.map((e) => (
                <li key={e.eventId} style={{ borderTop: "1px solid #ffffff22", paddingTop: 10 }}>
                  <Link href={`/graph/?focus=${encodeURIComponent(e.eventId)}`} className="body-lg link-strong">
                    {e.title}
                  </Link>
                  <span className="caption" style={{ color: "#ffffff90", marginLeft: 10 }}>
                    {e.eventType} · {e.occurredAt?.slice(0, 10)}
                    {e.impact ? ` · 영향도 ${(e.impact.portfolioImpactScore * 100).toFixed(1)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div style={{ display: "flex", gap: 12, marginTop: 28 }}>
            <Link href="/graph/" className="pill" style={{ background: "#fff", color: "#000" }}>그래프 열기</Link>
            <Link href="/events/" className="pill" style={{ border: "1px solid #ffffff50", color: "#fff" }}>이벤트 피드</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
