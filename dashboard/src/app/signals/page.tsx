import Link from "next/link";
import Tooltip from "@/components/Tooltip";
import BacktestChart from "@/app/proposals/BacktestChart";
import { loadBacktest, loadSignals } from "@/lib/data";
import { fmtPct } from "@/lib/format";

// 시그널 v2: 문헌 검증 알파 결합 + 알파×지평 성적표 (정직 우선)
const HORIZON_LABEL: Record<string, string> = {
  "v2@5": "5일", "v2@20": "20일", "v2@60": "60일",
};

export default function SignalsPage() {
  const doc = loadSignals();
  const board = doc?.board ?? [];
  const audits = doc?.audit ?? {};
  const icTable = doc?.icTable ?? [];
  const auditPassed = Object.values(audits).some(
    (a) => a && (a.meanIC ?? 0) > 0 && (a.icTstat ?? 0) >= 2);
  const strategy = doc?.strategy ?? null;
  const strategyCurve = strategy?.curveRunId ? loadBacktest(strategy.curveRunId) : null;

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">SIGNALS · v2</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>매수·매도 신호</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          학계에서 검증된 패턴(실적 표류, 내부자 매수, 증자 후 부진, 모멘텀 등)만 재료로
          씁니다. 각 재료가 이 유니버스에서 실제로 맞았는지 성적표를 아래에 공개하고,
          맞은 재료에 더 큰 가중치가 자동으로 갑니다.
        </p>
      </section>

      {/* 종합 성적 배너 */}
      <section className="section-sm">
        <div className="color-block" style={{
          background: auditPassed ? "var(--block-mint)" : "var(--block-cream)",
        }}>
          <div className="eyebrow">지난 4년 성적표</div>
          <h2 className="headline" style={{ margin: "10px 0 6px" }}>
            {auditPassed
              ? "이 신호 체계는 예측력이 통계적으로 확인되었습니다"
              : "개선 중입니다. 아직 통계적 확신 문턱(t≥2)을 넘지 못했습니다"}
          </h2>
          <p className="body" style={{ maxWidth: 780 }}>
            모든 시점에서 그때 알 수 있던 정보만으로 신호를 다시 만들어 채점했습니다.
            {!auditPassed && " 지금은 참고 지표로 쓰세요. 방향은 양(+)으로 돌아섰고, 표본이 쌓이면 판정이 갱신됩니다."}
          </p>
          <div className="grid-tiles" style={{ marginTop: 20, maxWidth: 860 }}>
            {Object.entries(audits).filter(([v]) => v.startsWith("v2@")).map(([variant, a]) => a && (
              <div key={variant} className="soft-tile" style={{ background: "#ffffffcc" }}>
                <div className="caption">{HORIZON_LABEL[variant] ?? variant} 보유 기준</div>
                <div className="mono-num" style={{ fontSize: 20, fontWeight: 640 }}>
                  IC {a.meanIC?.toFixed(3)}
                  <span className="caption" style={{ marginLeft: 6 }}>t={a.icTstat}</span>
                </div>
                <div className="body-sm" style={{ marginTop: 4 }}>
                  전략 {a.sharpe?.toFixed(2)} vs 그대로 {a.sharpeBaseline?.toFixed(2)}
                </div>
                <div className="caption" style={{ marginTop: 2 }}>
                  연간 초과 {fmtPct(a.activeReturnAnnual, 1, true)} · 진짜일 확률 {a.dsr?.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 알파 × 지평 성적표 */}
      <section className="section-sm">
        <h2 className="headline" style={{ marginBottom: 6 }}>
          재료별 성적
          <Tooltip text="각 재료(알파)가 신호를 낸 뒤 실제 수익률과 얼마나 같은 방향이었는지(IC)와 그것이 우연이 아닐 신뢰도(t)입니다. t가 2를 넘으면 검증된 것으로 보고 가중치가 커집니다." />
        </h2>
        <p className="body-sm" style={{ marginBottom: 16, opacity: 0.8 }}>
          맞은 재료는 자동으로 더 크게, 틀린 재료는 0으로 줄어듭니다. 부호를 뒤집는 일은 없습니다.
          이 표는 4년 전체 표본으로 계산한 참고 통계이고, 신호 계산 자체는 매 시점
          그때까지의 성적만 씁니다.
        </p>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>재료</th><th className="num">보유 지평</th>
                <th className="num">IC</th><th className="num">신뢰도 t</th>
                <th className="num">관측일</th><th>판정</th>
              </tr>
            </thead>
            <tbody>
              {icTable.map((r, i) => (
                <tr key={i} style={r.nDays === 0 ? { opacity: 0.45 } : undefined}>
                  <td className="body-sm" style={{ fontWeight: 480 }}>{r.label}</td>
                  <td className="num mono-num">{r.horizon}일</td>
                  <td className="num mono-num">{r.meanIC?.toFixed(4)}</td>
                  <td className="num mono-num">{r.nwT?.toFixed(2)}</td>
                  <td className="num mono-num">{r.nDays}</td>
                  <td>
                    {r.nDays === 0 ? (
                      <span className="caption">이력 수집 중</span>
                    ) : r.nwT >= 2 ? (
                      <span className="badge" style={{ background: "var(--semantic-success)", color: "#fff" }}>검증됨</span>
                    ) : r.nwT >= 1.5 ? (
                      <span className="caption">근접</span>
                    ) : (
                      <span className="caption">미검증</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 이 신호를 따라 매매했다면 */}
      {strategy && strategy.sharpe != null && (
        <section className="section-sm">
          <div className="hairline-card">
            <div className="flex-between">
              <h2 className="headline">
                이 신호를 4년간 따라 매매했다면 (20일 보유)
                <Tooltip text="강한 신호 상위 종목을 2%p 더 사거나 덜 갖고 20일 뒤 되돌리는 규칙을, 그 시점 정보만으로 4년간 반복한 결과입니다. 거래비용 포함." />
              </h2>
              <span className="caption">틸트 {strategy.nTilts}회 · 균등보유 대비</span>
            </div>
            <div className="grid-tiles" style={{ margin: "16px 0" }}>
              <div className="soft-tile">
                <div className="caption">총 수익</div>
                <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                  {fmtPct(strategy.totalReturn, 0)} <span className="caption">vs {fmtPct(strategy.totalReturnBaseline, 0)}</span>
                </div>
              </div>
              <div className="soft-tile">
                <div className="caption">성과 점수</div>
                <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                  {strategy.sharpe?.toFixed(2)} <span className="caption">vs {strategy.sharpeBaseline?.toFixed(2)}</span>
                </div>
              </div>
              <div className="soft-tile">
                <div className="caption" style={{ display: "flex", alignItems: "center" }}>
                  연간 초과수익
                  <Tooltip text="그대로 둔 것 대비 신호를 따라서 더 벌거나 잃은 연간 수익입니다." />
                </div>
                <div className={`mono-num ${(strategy.activeReturnAnnual ?? 0) >= 0 ? "up" : "down"}`}
                     style={{ fontSize: 22, fontWeight: 640 }}>
                  {fmtPct(strategy.activeReturnAnnual, 1, true)}
                </div>
              </div>
            </div>
            {strategyCurve && <BacktestChart data={strategyCurve} />}
          </div>
        </section>
      )}

      {/* 오늘의 신호 보드 */}
      <section className="section-sm">
        <h2 className="headline" style={{ marginBottom: 16 }}>
          오늘의 신호 {board.length}건
          <Tooltip text="확신도 = 과거 대비 강도(40%) + 검증된 재료 비율(30%) + 재료 방향 일치(30%)." />
        </h2>
        {board.length === 0 ? (
          <p className="body">오늘은 의미 있는 신호가 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {board.slice(0, 20).map((b) => (
              <article key={b.instrumentId} className="hairline-card" style={{ padding: 20 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="badge" style={{
                    background: b.direction === "BUY" ? "var(--block-mint)" : "var(--block-pink)",
                    border: "none", fontWeight: 700,
                  }}>
                    {b.direction === "BUY" ? "매수" : "매도"}
                  </span>
                  <Link href={`/instruments/${b.instrumentId.replace(/:/g, "_")}/`}
                        className="body-lg link-strong">
                    {b.name} <span className="caption">{b.ticker}</span>
                  </Link>
                  {!b.held && b.tradable && (
                    <span className="badge badge--stage" style={{ background: "var(--block-lilac)", border: "none" }}>
                      비보유
                    </span>
                  )}
                  {b.strengthNote && (
                    <span className="caption" style={{
                      background: "var(--block-cream)", padding: "3px 10px", borderRadius: 999, fontWeight: 700,
                    }}>
                      {b.strengthNote}
                    </span>
                  )}
                  <span className="caption" style={{ marginLeft: "auto" }}>
                    신호 {b.signal > 0 ? "+" : ""}{b.signal?.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
                  <span className="body-sm">확신도 <strong className="mono-num">{b.conviction?.toFixed(2)}</strong></span>
                  <span className="body-sm">과거 대비 강도 <strong className="mono-num">{fmtPct(b.strength, 0)}</strong></span>
                  <span className="body-sm">
                    검증된 재료 <strong className="mono-num">{fmtPct(b.evidenceShare, 0)}</strong>
                  </span>
                </div>
                {b.evidence?.length > 0 && (
                  <p className="caption" style={{ marginTop: 10 }}>
                    근거: {b.evidence.map((e) => `${e.label}${e.validated ? " ✓" : ""}`).join(" · ")}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
