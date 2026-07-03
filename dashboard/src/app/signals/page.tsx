import Link from "next/link";
import Tooltip from "@/components/Tooltip";
import { loadSignals } from "@/lib/data";
import { fmtPct } from "@/lib/format";

// 온톨로지 시그널 보드 + 감사 성적표 (정직 우선: 예측력 미검증이면 그대로 표시)
export default function SignalsPage() {
  const doc = loadSignals();
  const board = doc?.board ?? [];
  const audits = doc?.audit ?? {};
  const auditPassed = Object.values(audits).some(
    (a) => a && (a.meanIC ?? 0) > 0 && (a.icTstat ?? 0) >= 2);
  const validity = doc?.sourceValidity;

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">SIGNALS</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>매수·매도 신호</h1>
        <p className="body-lg" style={{ maxWidth: 760 }}>
          최근 5영업일의 공시·뉴스·시장 이벤트가 각 종목에 어느 방향으로 모였는지
          점수로 만든 것입니다. 아래 성적표에서 이 신호가 과거에 실제로 맞았는지도
          함께 공개합니다.
        </p>
      </section>

      {/* 감사 성적표 — 정직 배너 */}
      <section className="section-sm">
        <div className="color-block" style={{
          background: auditPassed ? "var(--block-mint)" : "var(--block-cream)",
        }}>
          <div className="eyebrow">지난 2년 성적표</div>
          <h2 className="headline" style={{ margin: "10px 0 6px" }}>
            {auditPassed
              ? "이 신호는 과거 데이터에서 예측력이 확인되었습니다"
              : "이 신호는 아직 예측력이 검증되지 않았습니다"}
          </h2>
          <p className="body" style={{ maxWidth: 760 }}>
            지난 2년의 모든 신호를 그 시점에 알 수 있던 정보만으로 다시 만들어,
            다음 5일 수익률과 비교했습니다.
            {!auditPassed && " 지금은 참고 지표로만 쓰고, 승인 전에 다른 근거를 함께 보세요."}
          </p>
          <div className="grid-tiles" style={{ marginTop: 20, maxWidth: 820 }}>
            {Object.entries(audits).map(([variant, a]) => a && (
              <div key={variant} className="soft-tile" style={{ background: "#ffffffcc" }}>
                <div className="caption" style={{ display: "flex", alignItems: "center" }}>
                  {variant === "all" ? "모든 근거 사용" : "검증된 유형만"}
                  <Tooltip text={variant === "all"
                    ? "뉴스 감성까지 포함한 전체 신호입니다."
                    : "과거 주가 반응이 통계적으로 확인된 이벤트 유형만 쓴 신호입니다."} />
                </div>
                <div className="mono-num" style={{ fontSize: 22, fontWeight: 640 }}>
                  IC {a.meanIC?.toFixed(3)}
                  <span className="caption" style={{ marginLeft: 8 }}>t={a.icTstat}</span>
                </div>
                <div className="body-sm" style={{ marginTop: 4 }}>
                  강신호 적중률 {a.hitRateStrong != null ? fmtPct(a.hitRateStrong, 0) : "-"}
                  <Tooltip text="신호 크기 상위 25% 발화가 방향을 맞힌 비율입니다. 50%면 동전 던지기와 같습니다." />
                </div>
              </div>
            ))}
          </div>
          {validity && (
            <p className="body-sm" style={{ marginTop: 16, maxWidth: 780 }}>
              {validity.useful.length > 0 && (
                <>예측력이 확인된 이벤트 유형: <strong>{validity.useful.join(", ")}</strong>. </>
              )}
              {validity.weak.length > 0 && (
                <>예측력이 없는 유형(참고만): {validity.weak.slice(0, 5).join(", ")}</>
              )}
            </p>
          )}
        </div>
      </section>

      {/* 오늘의 신호 보드 */}
      <section className="section-sm">
        <h2 className="headline" style={{ marginBottom: 16 }}>
          오늘의 신호 {board.length}건
          <Tooltip text="확신도 = 과거 대비 신호 강도(60%) + 검증된 유형 근거 비율(40%). 공식은 저장소 signals/engine.py 에 있습니다." />
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
                    신호 {Math.abs(b.expected5d).toFixed(1)}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
                  <span className="body-sm">
                    확신도 <strong className="mono-num">{b.conviction?.toFixed(2)}</strong>
                  </span>
                  <span className="body-sm">
                    과거 대비 강도 <strong className="mono-num">{fmtPct(b.strength, 0)}</strong>
                  </span>
                  <span className="body-sm">
                    검증된 근거 <strong className="mono-num">{fmtPct(b.evidenceShare, 0)}</strong>
                    <Tooltip text="이 신호를 만든 이벤트 중, 과거 주가 반응이 통계로 확인된 유형의 비율입니다." />
                  </span>
                </div>
                {b.evidence?.length > 0 && (
                  <p className="caption" style={{ marginTop: 10 }}>
                    근거: {b.evidence.map((e) => e.eventType + (e.validated ? " ✓" : "")).join(" · ")}
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
