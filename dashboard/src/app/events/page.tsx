import Link from "next/link";
import { loadEvents } from "@/lib/data";
import EventFilter from "./EventFilter";

export default function EventsPage() {
  const events = loadEvents();
  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">EVENT FEED · DART / SEC / FRED / RSS</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>이벤트</h1>
        <p className="body-lg" style={{ maxWidth: 720 }}>
          공시·실적·매크로·뉴스 이벤트. 각 이벤트의 <strong>영향도</strong>는
          전파 경로 점수(연관도 × |베타| × 비중)의 합입니다.
        </p>
      </section>
      {events.length === 0 ? (
        <section className="section-sm">
          <div className="color-block" style={{ background: "var(--block-pink)" }}>
            <h2 className="headline">아직 수집된 이벤트가 없습니다</h2>
            <p className="body" style={{ marginTop: 8, maxWidth: 640 }}>
              파이프라인 events 스테이지가 DART 공시, SEC 8-K, FRED 급변동, RSS 뉴스를
              수집하면 이 피드가 채워집니다.
            </p>
          </div>
        </section>
      ) : (
        <section className="section-sm">
          <EventFilter events={events} />
        </section>
      )}
      <div style={{ marginTop: 24 }}>
        <Link href="/graph/" className="pill pill-secondary">전파 그래프에서 보기</Link>
      </div>
    </div>
  );
}
