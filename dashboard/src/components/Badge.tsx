export function ValidationBadge({ status, summary }: { status: string; summary?: string | null }) {
  const cls = status === "VALIDATED" ? "badge--validated"
    : status === "REJECTED" ? "badge--rejected" : "badge--unvalidated";
  const label = status === "VALIDATED" ? "검증됨" : status === "REJECTED" ? "기각" : "미검증";
  return (
    <span className={`badge ${cls}`} title={summary ?? undefined}>
      {label}{summary ? ` · ${summary}` : ""}
    </span>
  );
}

export function BreachBadge() {
  return <span className="badge badge--breach">한도 위반</span>;
}

export function StageBadge({ stage }: { stage: string }) {
  const label = stage === "PRODUCTION" ? "프로덕션" : stage === "STAGING" ? "스테이징" : "보관";
  return (
    <span className="badge badge--stage" style={stage === "PRODUCTION" ? { background: "var(--semantic-success)", color: "#fff", border: "none" } : undefined}>
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; style?: React.CSSProperties }> = {
    DRAFT: { label: "초안" },
    PENDING: { label: "결재 대기", style: { background: "var(--block-cream)", border: "none" } },
    APPROVED: { label: "승인", style: { background: "var(--semantic-success)", color: "#fff", border: "none" } },
    REJECTED: { label: "반려", style: { background: "var(--ink)", color: "#fff", border: "none" } },
    EXECUTED: { label: "실행됨", style: { background: "var(--block-navy)", color: "#fff", border: "none" } },
    EXPIRED: { label: "만료" },
    OPEN: { label: "열림", style: { background: "var(--block-cream)", border: "none" } },
    COMMITTED: { label: "커밋됨", style: { background: "var(--semantic-success)", color: "#fff", border: "none" } },
    DISCARDED: { label: "폐기" },
  };
  const m = map[status] ?? { label: status };
  return <span className="badge badge--stage" style={m.style}>{m.label}</span>;
}
