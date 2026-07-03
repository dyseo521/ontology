import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Noto_Sans_KR } from "next/font/google";
import "./globals.css";
import TopNav from "@/components/TopNav";
import { loadMeta } from "@/lib/data";
import { fmtDateTime } from "@/lib/format";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", axes: ["opsz"], display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });
// 한글 글리프: Inter/JetBrains Mono 에 없음 — 셀프호스팅 Noto Sans KR 로 보장
// (unicode-range 분할로 실제 쓰인 조각만 로드됨. preload 는 라틴만)
const kr = Noto_Sans_KR({ subsets: ["latin"], variable: "--font-kr", display: "swap", preload: false });

export const metadata: Metadata = {
  title: "OntoQuant · 내 포트폴리오에 닿는 모든 신호",
  description: "종목, 섹터, 공시, 뉴스를 하나로 연결해 무엇이 내 포트폴리오를 움직이는지 보여주는 리스크 대시보드",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = loadMeta();
  const sourceNames = Object.keys(meta.sources).length
    ? Object.entries(meta.sources).map(([k, v]) => {
        const status = (v as { status?: string }).status ?? "ok";
        return `${k.toUpperCase()} ${String(status).startsWith("ok") ? "●" : "○"}`;
      })
    : ["NAVER", "TIINGO", "FRED", "KEN FRENCH", "DART", "SEC EDGAR"];
  const ticker = [...sourceNames, `AS OF ${meta.asOf ?? "-"}`, `GENERATED ${fmtDateTime(meta.generatedAt)} UTC`];

  return (
    <html lang="ko" className={`${sans.variable} ${mono.variable} ${kr.variable}`}>
      <body>
        <a href="#main" className="skip-link">본문으로 건너뛰기</a>
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
        <p className="sr-only">데이터 기준일 {meta.asOf ?? "미상"}, 생성 시각 {fmtDateTime(meta.generatedAt)} UTC</p>
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="container" style={{ padding: 0 }}>
            <div className="wordmark">OntoQuant</div>
            <p className="body-sm" style={{ marginTop: 12, maxWidth: 560 }}>
              종목, 섹터, 공시, 뉴스를 하나로 연결해 무엇이 내 포트폴리오를
              움직이는지 보여줍니다. 근거가 검증된 제안만 승인으로 이어집니다.
            </p>
            <p className="caption" style={{ marginTop: 24 }}>
              데이터: Naver Finance · Tiingo · FRED · Ken French · DART · SEC EDGAR / 투자 조언이 아닙니다
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
