// 숫자/날짜 포맷 유틸 (ko-KR)
export const fmtKrw = (v: number | null | undefined, compact = false): string => {
  if (v == null || Number.isNaN(v)) return "—";
  if (compact) {
    const abs = Math.abs(v);
    if (abs >= 1e8) return `₩${(v / 1e8).toFixed(1)}억`;
    if (abs >= 1e4) return `₩${(v / 1e4).toFixed(0)}만`;
  }
  return `₩${Math.round(v).toLocaleString("ko-KR")}`;
};

export const fmtNum = (v: number | null | undefined, digits = 2): string =>
  v == null || Number.isNaN(v) ? "—" : v.toLocaleString("ko-KR", { maximumFractionDigits: digits });

export const fmtPct = (v: number | null | undefined, digits = 2, signed = false): string => {
  if (v == null || Number.isNaN(v)) return "—";
  const s = (v * 100).toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
};

export const fmtLocal = (v: number | null | undefined, currency?: string): string => {
  if (v == null || Number.isNaN(v)) return "—";
  if (currency === "USD") return `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  return `₩${Math.round(v).toLocaleString("ko-KR")}`;
};

export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  return iso.slice(0, 10);
};

export const fmtDateTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
};

export const signClass = (v: number | null | undefined): string =>
  v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
