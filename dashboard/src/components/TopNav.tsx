"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "홈" },
  { href: "/signals/", label: "신호" },
  { href: "/graph/", label: "그래프" },
  { href: "/sectors/", label: "섹터" },
  { href: "/events/", label: "이벤트" },
  { href: "/insights/", label: "인사이트" },
  { href: "/proposals/", label: "제안" },
  { href: "/scenarios/", label: "시나리오" },
  { href: "/decisions/", label: "결정 기록" },
  { href: "/models/", label: "검증" },
];

export default function TopNav() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href.replace(/\/$/, ""));

  return (
    <nav className="top-nav">
      <div className="top-nav-inner">
        <Link href="/" className="brand">OntoQuant</Link>
        <div className="nav-links">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} data-active={isActive(l.href)}>
              {l.label}
            </Link>
          ))}
        </div>
        <Link href="/graph/" className="pill pill-primary" style={{ fontSize: 15, padding: "7px 16px" }}>
          전파 그래프
        </Link>
      </div>
    </nav>
  );
}
