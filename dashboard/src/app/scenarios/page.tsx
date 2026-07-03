import { StatusBadge } from "@/components/Badge";
import { loadScenarios } from "@/lib/data";
import { fmtDate, fmtPct } from "@/lib/format";

// Scenario = 온톨로지 fork/sandbox — baseline vs scenario 메트릭 diff
const METRIC_LABEL: Record<string, string> = {
  VAR_95_1D: "1일 VaR", VOL_30D: "변동성", MDD_1Y: "최대낙폭", HHI: "집중도", BETA_MKT: "베타",
};

export default function ScenariosPage() {
  const scenarios = loadScenarios();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">SCENARIOS · ONTOLOGY FORK</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>시나리오</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          시나리오는 온톨로지의 <strong>fork</strong>입니다 — 액션을 샌드박스에 적용해
          &ldquo;NVDA -3%p면 VaR이 어떻게 변하나&rdquo; 같은 what-if를 원본을 건드리지 않고
          검토하고, 만족하면 커밋합니다. 생성은 MCP <code>run_scenario</code> 도구로.
        </p>
      </section>

      {scenarios.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-cream)" }}>
            <h2 className="headline">열린 시나리오가 없습니다</h2>
            <p className="body" style={{ marginTop: 8 }}>
              Claude Code에서 <code>run_scenario</code> → <code>compare_scenario</code> →
              <code> commit_scenario</code> 흐름으로 what-if 분석을 시작하세요.
            </p>
          </div>
        </section>
      ) : (
        <section className="section-sm" style={{ display: "grid", gap: 20 }}>
          {scenarios.map((s) => (
            <article key={s.scenarioId} className="hairline-card">
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <h2 className="card-title">{s.name}</h2>
                <StatusBadge status={s.status} />
                <span className="caption" style={{ marginLeft: "auto" }}>
                  기준일 {fmtDate(s.baseDate)} · 액션 {s.appliedActionIds.length}건
                </span>
              </div>
              {s.diffSummary?.metrics && (
                <div className="table-scroll" style={{ marginTop: 16 }}>
                  <table className="data-table">
                    <thead>
                      <tr><th>지표</th><th className="num">베이스라인</th><th className="num">시나리오</th><th className="num">Δ</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(s.diffSummary.metrics).map(([k, v]) => (
                        <tr key={k}>
                          <td className="body-sm" style={{ fontWeight: 480 }}>{METRIC_LABEL[k] ?? k}</td>
                          <td className="num mono-num">{v.base != null ? fmtPct(v.base, 2) : "—"}</td>
                          <td className="num mono-num">{v.scenario != null ? fmtPct(v.scenario, 2) : "—"}</td>
                          <td className={`num mono-num ${v.delta != null && v.delta < 0 ? "up" : "down"}`}>
                            {v.delta != null ? fmtPct(v.delta, 2, true) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {s.diffSummary?.positions?.changed && s.diffSummary.positions.changed.length > 0 && (
                <p className="body-sm" style={{ marginTop: 12 }}>
                  변경 포지션: {s.diffSummary.positions.changed.map((c) =>
                    `${c.positionId.split(":").slice(1).join(":")} ${c.base}→${c.scenario}`).join(" · ")}
                </p>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
