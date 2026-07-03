import { StageBadge } from "@/components/Badge";
import { loadModels } from "@/lib/data";
import { fmtDateTime } from "@/lib/format";

// Modeling Objective 페이지 — 모델 버전 + EvaluationRun(MetricSet) 이력 + 게이트
const MODEL_LABELS: Record<string, string> = {
  "factor-model": "팩터 모델", "event-classifier": "이벤트 분류기",
  "rebalance-strategy": "리밸런싱 전략",
};

function MetricCell({ v }: { v: unknown }) {
  if (v == null) return <>—</>;
  if (typeof v === "number") return <>{Number.isInteger(v) ? v : v.toFixed(3)}</>;
  return <>{String(v)}</>;
}

export default function ModelsPage() {
  const models = loadModels();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">MODELING OBJECTIVE</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>모델</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          각 모델은 버전·스테이지를 갖고, 매 평가(EvaluationRun)가
          모델 버전 + 데이터 범위에 바인딩됩니다. STAGING 모델은 게이트 2회 통과 후 승격됩니다.
        </p>
      </section>

      <section className="section-sm" style={{ display: "grid", gap: 24 }}>
        {models.map((m) => (
          <article key={m.modelVersionId} className="hairline-card">
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              <h2 className="card-title">{MODEL_LABELS[m.modelId] ?? m.modelId}</h2>
              <span className="caption">{m.modelVersionId}</span>
              <StageBadge stage={m.stage} />
            </div>
            {m.description && <p className="body-sm" style={{ margin: "8px 0 4px" }}>{m.description}</p>}

            {m.evaluationRuns.length > 0 && (
              <div className="table-scroll" style={{ marginTop: 16 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>실행</th><th>기간</th><th>게이트</th>
                      {Object.keys(m.evaluationRuns[0].metricSet).slice(0, 6).map((k) => (
                        <th key={k} className="num">{k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {m.evaluationRuns.slice(0, 10).map((r) => (
                      <tr key={r.runId + r.createdAt}>
                        <td className="body-sm">{fmtDateTime(r.createdAt)}</td>
                        <td className="body-sm mono-num">
                          {r.datasetRange ? `${r.datasetRange.start} ~ ${r.datasetRange.end}` : "—"}
                        </td>
                        <td>
                          <span className="badge" style={r.passedGates
                            ? { background: "var(--semantic-success)", color: "#fff" }
                            : { background: "var(--semantic-danger)", color: "#fff" }}>
                            {r.passedGates ? "통과" : "실패"}
                          </span>
                        </td>
                        {Object.keys(m.evaluationRuns[0].metricSet).slice(0, 6).map((k) => (
                          <td key={k} className="num mono-num"><MetricCell v={r.metricSet[k]} /></td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {m.evaluationRuns[0]?.gateResults?.length > 0 && (
              <p className="caption" style={{ marginTop: 12 }}>
                게이트: {m.evaluationRuns[0].gateResults.map((g) => `${g.gate} ${g.passed ? "✓" : "✗"}`).join(" · ")}
              </p>
            )}
          </article>
        ))}
      </section>
    </div>
  );
}
