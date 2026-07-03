import { StatusBadge } from "@/components/Badge";
import Tooltip from "@/components/Tooltip";
import { loadScenarios } from "@/lib/data";
import { fmtDate, fmtPct } from "@/lib/format";

const METRIC_LABEL: Record<string, string> = {
  VAR_95_1D: "하루 위험액", VOL_30D: "출렁임", MDD_1Y: "최대 하락",
  HHI: "쏠림 지수", BETA_MKT: "시장 민감도",
};

export default function ScenariosPage() {
  const scenarios = loadScenarios();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">WHAT-IF</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>시나리오</h1>
        <p className="body-lg" style={{ maxWidth: 720 }}>
          &ldquo;엔비디아를 절반 줄이면 위험이 얼마나 줄까?&rdquo; 같은 질문을
          실제 포트폴리오는 건드리지 않고 미리 계산해 본 기록입니다.
        </p>
      </section>

      {scenarios.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-cream)" }}>
            <h2 className="headline">아직 시나리오가 없습니다</h2>
            <p className="body" style={{ marginTop: 8, maxWidth: 640 }}>
              포지션을 바꾸기 전에 먼저 여기서 결과를 미리 볼 수 있습니다.
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
                  기준일 {fmtDate(s.baseDate)}
                </span>
              </div>
              {s.diffSummary?.metrics && (
                <div className="table-scroll" style={{ marginTop: 16 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>지표</th><th className="num">지금</th>
                        <th className="num">바꾸면</th>
                        <th className="num">
                          차이<Tooltip text="음수(초록)면 위험이 줄어든다는 뜻입니다." />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(s.diffSummary.metrics).map(([k, v]) => (
                        <tr key={k}>
                          <td className="body-sm" style={{ fontWeight: 480 }}>{METRIC_LABEL[k] ?? k}</td>
                          <td className="num mono-num">{v.base != null ? fmtPct(v.base, 2) : "-"}</td>
                          <td className="num mono-num">{v.scenario != null ? fmtPct(v.scenario, 2) : "-"}</td>
                          <td className={`num mono-num ${v.delta != null && v.delta < 0 ? "up" : "down"}`}>
                            {v.delta != null ? fmtPct(v.delta, 2, true) : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {s.diffSummary?.positions?.changed && s.diffSummary.positions.changed.length > 0 && (
                <p className="body-sm" style={{ marginTop: 12 }}>
                  바꾼 것: {s.diffSummary.positions.changed.map((c) =>
                    `${c.positionId.split(":").slice(1).join(":")} ${c.base} → ${c.scenario}`).join(" · ")}
                </p>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
