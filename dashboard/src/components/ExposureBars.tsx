// 포트폴리오 팩터 익스포저 바 — 서버 렌더 가능한 순수 마크업
const FACTOR_LABELS: Record<string, string> = {
  "FF:MKT": "미국 시장", "FF:SMB": "중소형주", "FF:HML": "가치주", "FF:MOM": "상승 추세",
  "KR:MKT": "한국 시장", "MACRO:DGS10": "미국 금리", "MACRO:VIX": "변동성(VIX)",
  "MACRO:WTI": "유가", "MACRO:USDKRW": "원달러 환율",
};

export default function ExposureBars({ exposures, inverse = false }: {
  exposures: Record<string, number>;
  inverse?: boolean;
}) {
  const entries = Object.entries(exposures)
    .filter(([k]) => FACTOR_LABELS[k])
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (!entries.length) return <p className="body-sm">아직 계산된 값이 없습니다.</p>;
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.001);
  const ink = inverse ? "#ffffff" : "var(--ink)";
  const track = inverse ? "#ffffff22" : "#00000010";
  const neg = inverse ? "#f3c9b6" : "#b0532f";

  return (
    <div style={{ display: "grid", gap: 10, color: ink }}>
      {entries.map(([fid, beta]) => {
        const pct = (Math.abs(beta) / maxAbs) * 100;
        return (
          <div key={fid} style={{ display: "grid", gridTemplateColumns: "120px 1fr 72px", gap: 12, alignItems: "center" }}>
            <span className="body-sm" style={{ fontWeight: 480, color: ink }}>{FACTOR_LABELS[fid]}</span>
            <div style={{ position: "relative", height: 14, background: track, borderRadius: 7 }}>
              <div style={{
                position: "absolute", top: 0, bottom: 0,
                left: beta >= 0 ? "50%" : `${50 - pct / 2}%`,
                width: `${pct / 2}%`,
                background: beta >= 0 ? ink : neg,
                borderRadius: 7,
              }} />
              <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1,
                            background: inverse ? "#ffffff50" : "#00000030" }} />
            </div>
            <span className="mono-num body-sm" style={{ textAlign: "right", color: ink }}>
              {beta >= 0 ? "+" : ""}{beta.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
