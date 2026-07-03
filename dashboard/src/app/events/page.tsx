import Link from "next/link";
import { loadEvents } from "@/lib/data";
import EventFilter from "./EventFilter";

export default function EventsPage() {
  const events = loadEvents();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">EVENTS · 공시 / 실적 / 시장 / 뉴스</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>이벤트</h1>
        <p className="body-lg" style={{ maxWidth: 700 }}>
          내 종목과 시장에서 벌어진 일들입니다. 영향 숫자가 클수록
          내 포트폴리오에 더 크게 닿는 사건입니다.
        </p>
      </section>
      {events.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-pink)" }}>
            <h2 className="headline">아직 수집된 이벤트가 없습니다</h2>
            <p className="body" style={{ marginTop: 8, maxWidth: 640 }}>
              매일 아침 공시와 뉴스를 모아 여기에 채웁니다.
            </p>
          </div>
        </section>
      ) : (
        <section className="section-sm">
          <EventFilter events={events} />
        </section>
      )}
      <div style={{ marginTop: 24 }}>
        <Link href="/graph/" className="pill pill-secondary">그래프에서 보기</Link>
      </div>
    </div>
  );
}
