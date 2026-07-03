import { StatusBadge } from "@/components/Badge";
import Tooltip from "@/components/Tooltip";
import BacktestChart from "./BacktestChart";
import { loadBacktest, loadProposals } from "@/lib/data";
import { fmtDateTime, fmtPct } from "@/lib/format";

const SIDE_LABEL: Record<string, string> = { BUY: "매수", SELL: "매도", HOLD: "보유" };

export default function ProposalsPage() {
  const proposals = loadProposals();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">PROPOSALS</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>매수·매도 제안</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          모든 제안은 과거 3년으로 미리 돌려본 뒤에 옵니다 (거래비용 포함).
          그대로 둔 것보다 낫지 않으면 승인 자체가 막힙니다.
        </p>
      </section>

      {proposals.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-coral)" }}>
            <h2 className="headline">아직 제안이 없습니다</h2>
            <p className="body" style={{ marginTop: 8, maxWidth: 640 }}>
              한도를 넘거나 위험 신호가 잡히면 시스템이 제안을 만들어 여기에 올립니다.
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
                      {p.backtest.passedGates ? "검증 통과" : "검증 미달"}
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
                          <td className="body-sm">{leg.reason ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {p.backtest && (
                  <div style={{ marginTop: 16 }}>
                    <div className="grid-tiles" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                      <div className="soft-tile">
                        <div className="caption" style={{ display: "flex", alignItems: "center" }}>
                          성과 점수<Tooltip text="같은 위험을 지고 얼마나 벌었는지입니다. 오른쪽의 '그대로 둘 때'보다 높아야 통과합니다." />
                        </div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                          {(ms.sharpe ?? ms.oosSharpe)?.toFixed(2)}{" "}
                          <span className="caption">vs {(ms.sharpeBaseline ?? ms.oosSharpeBaseline)?.toFixed(2)}</span>
                        </div>
                      </div>
                      <div className="soft-tile">
                        <div className="caption" style={{ display: "flex", alignItems: "center" }}>
                          최대 하락<Tooltip text="시뮬레이션 기간 중 고점 대비 가장 크게 빠졌던 폭입니다. 작을수록 좋습니다." />
                        </div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                          {fmtPct(ms.mdd ?? ms.oosMdd, 1)}{" "}
                          <span className="caption">vs {fmtPct(ms.mddBaseline ?? ms.oosMddBaseline, 1)}</span>
                        </div>
                      </div>
                      {ms.dsr != null && (
                        <div className="soft-tile">
                          <div className="caption" style={{ display: "flex", alignItems: "center" }}>
                            진짜일 확률<Tooltip text="여러 번 시도한 것을 감안해도 이 성과가 우연이 아닐 확률입니다. 0.95 이상이면 통과." />
                          </div>
                          <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>{ms.dsr?.toFixed(2)}</div>
                        </div>
                      )}
                      <div className="soft-tile">
                        <div className="caption">거래 수</div>
                        <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>{ms.nTrades ?? "-"}</div>
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
