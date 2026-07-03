import { loadEvents, loadGraph, loadSchemaDoc } from "@/lib/data";
import GraphClient from "./GraphClient";

export default function GraphPage() {
  const graph = loadGraph();
  const schema = loadSchemaDoc();
  const colors: Record<string, string> = {};
  for (const ot of schema.objectTypes) if (ot.color) colors[ot.apiName] = ot.color;
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
        <h1 className="display-lg" style={{ margin: "12px 0 8px" }}>전파 그래프</h1>
        <p className="body-lg" style={{ maxWidth: 720 }}>
          이벤트 → 종목/팩터 → 포지션 → 포트폴리오. 노드를 클릭하면 이웃이 밝혀지고,
          이벤트 노드에서는 포트폴리오까지의 도달 경로가 하이라이트됩니다.
        </p>
      </section>
      <section className="section-sm">
        <GraphClient graph={graph} colors={colors} impactPaths={impactPaths} />
      </section>
    </div>
  );
}
