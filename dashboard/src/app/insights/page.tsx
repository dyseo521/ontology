import { ValidationBadge } from "@/components/Badge";
import Tooltip from "@/components/Tooltip";
import { loadInsights } from "@/lib/data";

const TYPE_LABELS: Record<string, string> = {
  EVENT_IMPACT: "이벤트 영향", LIMIT_BREACH: "한도 초과", EXPOSURE_SHIFT: "민감도 변화",
  CONCENTRATION: "종목 쏠림", FACTOR_MOVE: "시장 급변",
  SECTOR_CONCENTRATION: "섹터 쏠림", SECTOR_EVENT_CLUSTER: "섹터 위험 신호",
  CASH_ALLOCATION: "현금 확보", NEWS_SENTIMENT_SHIFT: "뉴스 흐름",
  FUNDAMENTAL_SHIFT: "실적 변화",
};

export default function InsightsPage() {
  const insights = loadInsights();
  const rejected = insights.filter((i) => i.validationStatus === "REJECTED");
  const active = insights
    .filter((i) => i.validationStatus !== "REJECTED")
    .sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0));

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">INSIGHTS</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>지금 확인할 것</h1>
        <p className="body-lg" style={{ maxWidth: 740 }}>
          무슨 일이 있고, 어떻게 대응할지 한 줄로 정리했습니다.
          <span style={{ whiteSpace: "nowrap" }}>
            초록 배지
            <Tooltip text="같은 유형의 과거 사건들에서 실제로 주가가 움직였다는 통계적 근거가 있다는 뜻입니다. 회색이면 아직 근거를 쌓는 중입니다." />
          </span>
          가 붙은 것은 과거 데이터로 근거가 확인된 것입니다.
        </p>
      </section>

      <section className="section-sm" style={{ display: "grid", gap: 16 }}>
        {active.length === 0 && (
          <div className="hairline-card body">지금은 확인할 것이 없습니다.</div>
        )}
        {active.map((ins) => (
          <article key={ins.insightId} className="hairline-card">
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span className="caption" style={{ background: "var(--surface-soft)", padding: "3px 10px", borderRadius: 999 }}>
                {TYPE_LABELS[ins.insightType] ?? ins.insightType}
              </span>
              <ValidationBadge status={ins.validationStatus} summary={ins.validationSummary} />
              <span className="caption" style={{ marginLeft: "auto" }}>{ins.asOfDate}</span>
            </div>
            <h2 className="card-title" style={{ margin: "12px 0 8px" }}>{ins.title}</h2>
            <p className="body" style={{ maxWidth: 820 }}>{ins.narrative}</p>
            {ins.recommendedAction?.label && (
              <p className="body-sm" style={{
                marginTop: 12, display: "inline-flex", alignItems: "center", gap: 8,
                background: "var(--block-lime)", padding: "8px 16px", borderRadius: 999,
                fontWeight: 640,
              }}>
                권장 대응: {ins.recommendedAction.label}
              </p>
            )}
          </article>
        ))}
      </section>

      {rejected.length > 0 && (
        <section className="section-sm">
          <h2 className="caption" style={{ marginBottom: 12 }}>근거가 반대여서 감춘 것</h2>
          <div style={{ display: "grid", gap: 8 }}>
            {rejected.map((ins) => (
              <div key={ins.insightId} className="body-sm" style={{ opacity: 0.55 }}>
                <ValidationBadge status="REJECTED" /> <span style={{ marginLeft: 8 }}>{ins.title}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
