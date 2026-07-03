import { ValidationBadge } from "@/components/Badge";
import { loadInsights } from "@/lib/data";
import { fmtPct } from "@/lib/format";

const TYPE_LABELS: Record<string, string> = {
  EVENT_IMPACT: "이벤트 영향", LIMIT_BREACH: "한도 위반", EXPOSURE_SHIFT: "익스포저 변화",
  CONCENTRATION: "집중도", FACTOR_MOVE: "팩터 급변",
};

export default function InsightsPage() {
  const insights = loadInsights();
  const rejected = insights.filter((i) => i.validationStatus === "REJECTED");
  const active = insights.filter((i) => i.validationStatus !== "REJECTED");

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">INSIGHTS · VALIDATED BY EVENT STUDY</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>인사이트</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          모든 통계적 인사이트는 과거 동일 유형 이벤트의 CAR(누적초과수익률) 스터디로 검증됩니다.
          표본 부족(n&lt;10) 또는 유의성 미달(|t|&lt;2)이면 <strong>미검증</strong>, 서사와 부호가
          반대면 <strong>기각</strong>되어 노출이 억제됩니다.
        </p>
      </section>

      <section className="section-sm" style={{ display: "grid", gap: 16 }}>
        {active.length === 0 && (
          <div className="hairline-card body">현재 활성 인사이트가 없습니다.</div>
        )}
        {active.map((ins) => (
          <article key={ins.insightId} className="hairline-card">
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span className="caption" style={{ background: "var(--surface-soft)", padding: "3px 10px", borderRadius: 999 }}>
                {TYPE_LABELS[ins.insightType] ?? ins.insightType}
              </span>
              <ValidationBadge status={ins.validationStatus} summary={ins.validationSummary} />
              <span className="caption" style={{ marginLeft: "auto" }}>
                {ins.asOfDate} · 심각도 {fmtPct(ins.severity, 0)}
              </span>
            </div>
            <h2 className="card-title" style={{ margin: "12px 0 8px" }}>{ins.title}</h2>
            <p className="body" style={{ maxWidth: 820 }}>{ins.narrative}</p>
          </article>
        ))}
      </section>

      {rejected.length > 0 && (
        <section className="section-sm">
          <h2 className="caption" style={{ marginBottom: 12 }}>기각된 인사이트 (노출 억제)</h2>
          <div style={{ display: "grid", gap: 8 }}>
            {rejected.map((ins) => (
              <div key={ins.insightId} className="body-sm" style={{ opacity: 0.55 }}>
                <ValidationBadge status="REJECTED" /> <span style={{ marginLeft: 8 }}>{ins.title}</span>
                <span className="caption" style={{ marginLeft: 8 }}>{ins.validationSummary}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
