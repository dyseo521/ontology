// 포트폴리오 팩터 익스포저 — 서버 렌더 가능한 순수 SVG-free 바
const FACTOR_LABELS: Record<string, string> = {
  "FF:MKT": "미국 시장", "FF:SMB": "사이즈", "FF:HML": "밸류", "FF:MOM": "모멘텀",
  "KR:MKT": "한국 시장", "MACRO:DGS10": "미국 10Y 금리", "MACRO:VIX": "VIX",
  "MACRO:WTI": "WTI 유가", "MACRO:USDKRW": "원달러",
};

export default function ExposureBars({ exposures }: { exposures: Record<string, number> }) {
  const entries = Object.entries(exposures)
    .filter(([k]) => FACTOR_LABELS[k])
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (!entries.length) return <p className="body-sm">익스포저 데이터 없음</p>;
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.001);

  return (
    <div style={{ display: "grid", gap: 10 }}>
      {entries.map(([fid, beta]) => {
        const pct = (Math.abs(beta) / maxAbs) * 100;
        return (
          <div key={fid} style={{ display: "grid", gridTemplateColumns: "120px 1fr 72px", gap: 12, alignItems: "center" }}>
            <span className="body-sm" style={{ fontWeight: 480 }}>{FACTOR_LABELS[fid]}</span>
            <div style={{ position: "relative", height: 14, background: "#00000010", borderRadius: 7 }}>
              <div style={{
                position: "absolute", top: 0, bottom: 0,
                left: beta >= 0 ? "50%" : `${50 - pct / 2}%`,
                width: `${pct / 2}%`,
                background: beta >= 0 ? "var(--ink)" : "#b0532f",
                borderRadius: 7,
              }} />
              <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "#00000030" }} />
            </div>
            <span className="mono-num body-sm" style={{ textAlign: "right" }}>
              {beta >= 0 ? "+" : ""}{beta.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
