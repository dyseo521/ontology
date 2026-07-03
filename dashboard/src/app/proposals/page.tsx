import { StatusBadge } from "@/components/Badge";
import BacktestChart from "./BacktestChart";
import { loadBacktest, loadProposals } from "@/lib/data";
import { fmtDateTime, fmtPct } from "@/lib/format";

const SIDE_LABEL: Record<string, string> = { BUY: "매수", SELL: "매도", HOLD: "보유" };

export default function ProposalsPage() {
  const proposals = loadProposals();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">REBALANCE PROPOSALS · BACKTEST-GATED</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>리밸런싱 제안</h1>
        <p className="body-lg" style={{ maxWidth: 780 }}>
          제안은 3년 walk-forward 백테스트(거래비용 포함)로 검증되며,
          게이트(<span className="mono-num">Sharpe &gt; 베이스라인 AND MDD ≤ 베이스라인×1.1</span>)를
          통과해야만 승인할 수 있습니다. 결재는 Claude Code MCP의 <code>approveProposal</code> 액션으로.
        </p>
      </section>

      {proposals.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-coral)" }}>
            <h2 className="headline">아직 제안이 없습니다</h2>
            <p className="body" style={{ marginTop: 8, maxWidth: 640 }}>
              파이프라인이 이벤트·한도 위반에서 제안을 생성하거나, Claude Code에서
              <code> propose_rebalance</code> MCP 도구로 직접 생성할 수 있습니다.
            </p>
          </div>
        </section>
      ) : (
        <section className="section-sm" style={{ display: "grid", gap: 20 }}>
          {proposals.map((p) => {
            const bt = p.backtestRunId ? loadBacktest(p.backtestRunId) : null;
            const ms = (p.backtest?.metricSet ?? {}) as Record<string, number>;
            return (
              <article key={p.proposalId} className="hairline-card">
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <h2 className="card-title">{p.title}</h2>
                  <StatusBadge status={p.status} />
                  {p.backtest && (
                    <span className="badge" style={p.backtest.passedGates
                      ? { background: "var(--semantic-success)", color: "#fff" }
                      : { background: "var(--semantic-danger)", color: "#fff" }}>
                      백테스트 {p.backtest.passedGates ? "게이트 통과" : "게이트 실패"}
                    </span>
                  )}
                  <span className="caption" style={{ marginLeft: "auto" }}>
                    {fmtDateTime(p.createdAt)} · {p.createdBy}
                  </span>
                </div>
                <p className="body" style={{ margin: "10px 0 16px", maxWidth: 820 }}>{p.rationale}</p>

                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr><th>종목</th><th>방향</th><th className="num">비중 변화</th><th>사유</th></tr>
                    </thead>
                    <tbody>
                      {p.legs.map((leg, i) => (
                        <tr key={i}>
                          <td className="body-sm">{leg.instrumentId}</td>
                          <td>
                            <span className="badge badge--stage" style={{
                              background: leg.side === "BUY" ? "var(--block-mint)"
                                : leg.side === "SELL" ? "var(--block-pink)" : "var(--surface-soft)",
                              border: "none",
                            }}>
                              {SIDE_LABEL[leg.side] ?? leg.side}
                            </span>
                          </td>
                          <td className={`num mono-num ${leg.targetWeightDelta > 0 ? "up" : "down"}`}>
                            {fmtPct(leg.targetWeightDelta, 1, true)}p
                          </td>
                          <td className="body-sm">{leg.reason ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {p.backtest && (
                  <div style={{ marginTop: 16 }}>
                    <div className="grid-tiles" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
                      <div className="soft-tile">
                        <div className="caption">Sharpe</div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                          {ms.sharpe?.toFixed(2)} <span className="caption">vs {ms.sharpeBaseline?.toFixed(2)}</span>
                        </div>
                      </div>
                      <div className="soft-tile">
                        <div className="caption">MDD</div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                          {fmtPct(ms.mdd, 1)} <span className="caption">vs {fmtPct(ms.mddBaseline, 1)}</span>
                        </div>
                      </div>
                      <div className="soft-tile">
                        <div className="caption">회전율(연)</div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>{fmtPct(ms.turnover, 0)}</div>
                      </div>
                      <div className="soft-tile">
                        <div className="caption">거래 수</div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>{ms.nTrades}</div>
                      </div>
                    </div>
                    {bt && <div style={{ marginTop: 16 }}><BacktestChart data={bt} /></div>}
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
