import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import TopNav from "@/components/TopNav";
import { loadMeta } from "@/lib/data";
import { fmtDateTime } from "@/lib/format";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", axes: ["opsz"] });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "OntoQuant — 온톨로지 포트폴리오 리스크",
  description: "온톨로지로 종목·팩터·이벤트·포트폴리오를 연결한 퀀트 리스크 대시보드",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = loadMeta();
  const sourceNames = Object.keys(meta.sources).length
    ? Object.entries(meta.sources).map(([k, v]) => {
        const status = (v as { status?: string }).status ?? "ok";
        return `${k.toUpperCase()} ${String(status).startsWith("ok") ? "●" : "○"}`;
      })
    : ["NAVER", "TIINGO", "FRED", "KEN FRENCH", "DART", "SEC EDGAR"];
  const ticker = [...sourceNames, `AS OF ${meta.asOf ?? "—"}`, `GENERATED ${fmtDateTime(meta.generatedAt)} UTC`];

  return (
    <html lang="ko" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <TopNav />
        <div className="marquee-strip" aria-hidden>
          <div className="marquee-track">
            {[0, 1].map((rep) => (
              <span key={rep}>
                {ticker.map((t, i) => (
                  <span key={i} style={{ marginRight: 48 }}>{t}</span>
                ))}
              </span>
            ))}
          </div>
        </div>
        <main>{children}</main>
        <footer className="site-footer">
          <div className="container" style={{ padding: 0 }}>
            <div className="wordmark">OntoQuant</div>
            <p className="body-sm" style={{ marginTop: 12, maxWidth: 560 }}>
              종목·팩터·이벤트를 하나의 온톨로지로 연결하고, 검증된 근거가 있는
              인사이트와 제안만 결재로 이어지는 퀀트 포트폴리오 리스크 시스템.
            </p>
            <p className="caption" style={{ marginTop: 24 }}>
              데이터: Naver Finance · Tiingo · FRED · Ken French · DART · SEC EDGAR — 투자 조언이 아님
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
