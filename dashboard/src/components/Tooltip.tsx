"use client";

import { useId, useState } from "react";

// 작은 회색 ? 동그라미 — 궁금할 만한 용어에만 붙인다 (hover/focus/tap, Esc 닫기)
export default function Tooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span style={{ position: "relative", display: "inline-flex", marginLeft: 4 }}>
      <button
        type="button"
        aria-label="설명 보기"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        style={{
          width: 24, height: 24, borderRadius: 999, padding: 0,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          verticalAlign: "middle", cursor: "help", touchAction: "manipulation",
        }}
      >
        <span aria-hidden style={{
          width: 16, height: 16, borderRadius: 999,
          background: "var(--surface-soft)", border: "1px solid var(--hairline)",
          color: "#595959", fontSize: 10.5, fontWeight: 600, lineHeight: "14px",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
        }}>?</span>
      </button>
      {open && (
        <span id={id} role="tooltip" style={{
          position: "absolute", bottom: "calc(100% + 6px)", left: "50%",
          transform: "translateX(-50%)", zIndex: 60,
          width: 230, padding: "10px 12px",
          background: "var(--ink)", color: "#fff",
          borderRadius: 8, fontSize: 12.5, fontWeight: 330, lineHeight: 1.45,
          letterSpacing: "-0.1px", textTransform: "none", overscrollBehavior: "contain",
        }}>
          {text}
        </span>
      )}
    </span>
  );
}
