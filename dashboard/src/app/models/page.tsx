import { StageBadge } from "@/components/Badge";
import Tooltip from "@/components/Tooltip";
import { loadModels } from "@/lib/data";
import { fmtDateTime, fmtPct } from "@/lib/format";
import type { EvaluationRunView } from "@/lib/data";

// 검증 페이지: 시스템이 스스로를 어떻게 채점하는지 보여준다
const MODEL_LABELS: Record<string, { name: string; desc: string }> = {
  "factor-model": {
    name: "민감도 계산",
    desc: "각 종목이 시장·금리·환율에 얼마나 민감한지 매일 다시 잽니다.",
  },
  "event-classifier": {
    name: "이벤트 분석",
    desc: "공시·뉴스를 유형별로 나누고, 그 유형이 과거에 실제로 주가를 움직였는지 검증합니다.",
  },
  "rebalance-strategy": {
    name: "리밸런싱 전략",
    desc: "매수·매도 제안을 만들기 전에 과거 3년으로 미리 돌려보고, 통과한 것만 승인 대상이 됩니다.",
  },
};

const RUN_LABELS: Record<string, string> = {
  FACTOR_QUALITY: "품질 점검", EVENT_STUDY: "이벤트 검증",
  PROPOSAL_BACKTEST: "제안 검증", WALK_FORWARD: "전략 검증 (미래 구간)",
  DECISION_OUTCOME: "결정 성적",
};

const COLUMNS: Record<string, { key: string; label: string; tip?: string }[]> = {
  FACTOR_QUALITY: [
    { key: "medianR2", label: "설명력", tip: "민감도 계산이 실제 주가 움직임을 얼마나 설명하는지 (중앙값). 높을수록 좋습니다." },
    { key: "coveragePct", label: "커버리지%" },
  ],
  EVENT_STUDY: [
    { key: "eventType", label: "유형" }, { key: "market", label: "시장" },
    { key: "n", label: "표본" },
    { key: "carMean", label: "평균 반응", tip: "이 유형의 사건 후 6일간 시장 대비 평균 주가 반응입니다." },
    { key: "tBmp", label: "신뢰도", tip: "우연이 아닐 가능성입니다. 절대값 2를 넘으면 통계적으로 의미 있다고 봅니다." },
  ],
  PROPOSAL_BACKTEST: [
    { key: "sharpe", label: "성과 점수", tip: "위험 대비 수익입니다. 그대로 둘 때보다 높아야 통과합니다." },
    { key: "sharpeBaseline", label: "vs 그대로" },
    { key: "mdd", label: "최대 하락" }, { key: "mddBaseline", label: "vs 그대로" },
  ],
  WALK_FORWARD: [
    { key: "oosSharpe", label: "미래 구간 성과", tip: "전략을 정한 뒤 본 적 없는 구간에서만 잰 성과입니다. 과거에 끼워 맞춘 전략을 걸러냅니다." },
    { key: "oosSharpeBaseline", label: "vs 그대로" },
    { key: "dsr", label: "진짜일 확률", tip: "여러 번 시도한 것을 감안해도 이 성과가 우연이 아닐 확률입니다 (0.95 이상 통과)." },
    { key: "nTrials", label: "시도 수", tip: "지금까지 시도한 전략 조합 수입니다. 많이 시도할수록 통과 기준이 자동으로 높아집니다." },
    { key: "nOosEvents", label: "표본 사건" },
  ],
  DECISION_OUTCOME: [
    { key: "horizonBd", label: "지평(일)" },
    { key: "activeReturn", label: "결정의 값어치", tip: "승인한 제안대로 한 것이 그대로 둔 것보다 얼마나 나았는지입니다." },
    { key: "rollingHitRate", label: "최근 적중률", tip: "최근 결정 10건 중 그대로 둔 것보다 나았던 비율입니다." },
  ],
};


function Cell({ v, k }: { v: unknown; k: string }) {
  if (v == null) return <>-</>;
  if (typeof v === "number") {
    if (["carMean", "activeReturn", "rollingHitRate", "mdd", "mddBaseline"].includes(k)) {
      return <>{fmtPct(v, k === "rollingHitRate" ? 0 : 2, k === "activeReturn")}</>;
    }
    return <>{Number.isInteger(v) ? v : v.toFixed(2)}</>;
  }
  return <>{String(v)}</>;
}

function RunTable({ runs, runType }: { runs: EvaluationRunView[]; runType: string }) {
  const cols = COLUMNS[runType] ?? [];
  const isEventStudy = runType === "EVENT_STUDY";
  // 이벤트 검증은 유형별 최신만, 나머지는 최근 실행 순
  let rows = runs;
  if (isEventStudy) {
    const latest = new Map<string, EvaluationRunView>();
    for (const r of [...runs].sort((a, b) => a.createdAt.localeCompare(b.createdAt))) {
      const ms = r.metricSet as Record<string, unknown>;
      latest.set(`${ms.eventType}:${ms.market}`, r);
    }
    rows = [...latest.values()].sort((a, b) =>
      Math.abs(Number((b.metricSet as Record<string, unknown>).tBmp ?? 0))
      - Math.abs(Number((a.metricSet as Record<string, unknown>).tBmp ?? 0)));
  }
  return (
    <div className="table-scroll" style={{ marginTop: 8 }}>
      <table className="data-table">
        <thead>
          <tr>
            {!isEventStudy && <th>실행</th>}
            <th>판정</th>
            {cols.map((c) => (
              <th key={c.key} className="num" style={{ whiteSpace: "nowrap" }}>
                {c.label}{c.tip && <Tooltip text={c.tip} />}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((r) => (
            <tr key={r.runId + r.createdAt}>
              {!isEventStudy && <td className="body-sm mono-num">{fmtDateTime(r.createdAt)}</td>}
              <td>
                <span className="badge" style={r.passedGates
                  ? { background: "var(--semantic-success)", color: "#fff" }
                  : { background: "var(--surface-soft)", border: "1px solid var(--hairline)" }}>
                  {r.passedGates ? "통과" : "미달"}
                </span>
              </td>
              {cols.map((c) => (
                <td key={c.key} className="num mono-num">
                  <Cell v={(r.metricSet as Record<string, unknown>)[c.key]} k={c.key} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ModelsPage() {
  const models = loadModels();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">VALIDATION</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>검증</h1>
        <p className="body-lg" style={{ maxWidth: 740 }}>
          이 시스템의 모든 인사이트와 제안은 과거 데이터로 먼저 채점됩니다.
          여기서 그 성적표를 공개합니다. 통과하지 못한 제안은 승인 자체가 막힙니다.
        </p>
      </section>

      <section className="section-sm" style={{ display: "grid", gap: 24 }}>
        {models.map((m) => {
          const info = MODEL_LABELS[m.modelId] ?? { name: m.modelId, desc: "" };
          const byType = new Map<string, EvaluationRunView[]>();
          for (const r of m.evaluationRuns) {
            byType.set(r.runType, [...(byType.get(r.runType) ?? []), r]);
          }
          return (
            <article key={m.modelVersionId} className="hairline-card">
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <h2 className="card-title">{info.name}</h2>
                <span className="caption">{m.modelVersionId}</span>
                <StageBadge stage={m.stage} />
              </div>
              <p className="body-sm" style={{ margin: "8px 0 4px", maxWidth: 720 }}>{info.desc}</p>
              {[...byType.entries()].map(([runType, runs]) => (
                <div key={runType} style={{ marginTop: 16 }}>
                  <div className="caption" style={{ marginBottom: 4 }}>
                    {RUN_LABELS[runType] ?? runType} · {runs.length}회
                  </div>
                  <RunTable runs={runs} runType={runType} />
                </div>
              ))}
              {m.evaluationRuns.length === 0 && (
                <p className="body-sm" style={{ marginTop: 12, opacity: 0.7 }}>아직 실행 기록이 없습니다.</p>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
