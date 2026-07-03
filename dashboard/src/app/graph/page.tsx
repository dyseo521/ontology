import { loadEvents, loadGraph, loadSchemaDoc, loadSectors } from "@/lib/data";
import GraphClient from "./GraphClient";

export default function GraphPage() {
  const graph = loadGraph();
  const schema = loadSchemaDoc();
  const colors: Record<string, string> = {};
  for (const ot of schema.objectTypes) if (ot.color) colors[ot.apiName] = ot.color;
  const sectors = loadSectors()
    .filter((s) => s.weight > 0)
    .map((s) => ({ sectorId: s.sectorId, nameKo: s.nameKo }));
  // 이벤트별 전파 경로 노드 시퀀스 (그래프 하이라이트용)
  const impactPaths: Record<string, string[][]> = {};
  for (const e of loadEvents()) {
    const paths = (e.impact?.paths ?? []) as { nodes?: string[] }[];
    const nodes = paths.map((p) => p.nodes ?? []).filter((n) => n.length > 0);
    if (nodes.length) impactPaths[e.eventId] = nodes;
  }

  return (
    <div className="container">
      <section className="section-sm" style={{ marginTop: 48 }}>
        <div className="eyebrow">ONTOLOGY GRAPH</div>
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>연결 그래프</h1>
        <p className="body-lg" style={{ maxWidth: 700 }}>
          이벤트가 어느 종목을 거쳐 내 포트폴리오까지 오는지 한눈에 봅니다.
          노드를 클릭하면 연결된 것만 밝아집니다.
        </p>
      </section>
      <section className="section-sm">
        <GraphClient graph={graph} colors={colors} impactPaths={impactPaths} sectors={sectors} />
      </section>
    </div>
  );
}
