import { loadDecisions } from "@/lib/data";
import { fmtDateTime } from "@/lib/format";

// Decision capture 타임라인 — 누가/언제/왜/추천 대비 결정
const DECISION_LABEL: Record<string, string> = { APPROVE: "승인", REJECT: "반려", MODIFY: "수정" };

export default function DecisionsPage() {
  const { decisions, actionLog } = loadDecisions();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="color-block color-block--navy" style={{ background: "var(--block-navy)" }}>
          <div className="eyebrow" style={{ color: "#ffffffb0" }}>DECISION CAPTURE · AUDIT LOG</div>
          <h1 className="display-lg" style={{ margin: "16px 0 12px" }}>결정 로그</h1>
          <p className="subhead" style={{ color: "#ffffffd0", maxWidth: 760 }}>
            모든 액션 제출은 추천 스냅샷(값+근거+검증 메트릭)과 사람의 결정·사유를 함께
            기록합니다 — 결정의 계보(lineage)가 그대로 감사 자산이 됩니다.
          </p>
        </div>
      </section>

      <section className="section-sm">
        <h2 className="headline" style={{ marginBottom: 20 }}>결정 {decisions.length}건</h2>
        {decisions.length === 0 ? (
          <p className="body">아직 기록된 결정이 없습니다. MCP <code>approveProposal</code> 액션이 첫 기록을 만듭니다.</p>
        ) : (
          <ol style={{ display: "grid", gap: 0 }}>
            {decisions.map((d) => (
              <li key={d.decisionId} style={{
                borderLeft: "2px solid var(--ink)", paddingLeft: 24, paddingBottom: 28, position: "relative",
              }}>
                <span style={{
                  position: "absolute", left: -6, top: 4, width: 10, height: 10, borderRadius: 999,
                  background: d.decision === "APPROVE" ? "var(--semantic-success)" : "var(--ink)",
                }} />
                <div className="caption">{fmtDateTime(d.decidedAt)} · {d.decidedBy}</div>
                <div className="body-lg" style={{ fontWeight: 540, margin: "4px 0" }}>
                  {DECISION_LABEL[d.decision] ?? d.decision} — {d.subjectType} <span className="caption">{d.subjectId}</span>
                </div>
                <p className="body-sm" style={{ maxWidth: 720 }}>{d.reason}</p>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="section-sm">
        <h2 className="caption" style={{ marginBottom: 12 }}>액션 감사 로그 (최근 {actionLog.length}건)</h2>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>시각</th><th>액션</th><th>주체</th><th>상태</th><th>변경</th></tr>
            </thead>
            <tbody>
              {actionLog.map((a, i) => (
                <tr key={i}>
                  <td className="body-sm mono-num">{fmtDateTime(String(a.submittedAt ?? ""))}</td>
                  <td className="body-sm" style={{ fontWeight: 480 }}>{String(a.actionType ?? "")}</td>
                  <td className="body-sm">{String(a.actor ?? "")}</td>
                  <td className="body-sm">{String(a.status ?? "")}</td>
                  <td className="body-sm">{Array.isArray(a.objectsChanged) ? a.objectsChanged.length : 0}건</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
