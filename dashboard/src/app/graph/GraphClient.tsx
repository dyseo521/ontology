"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import OntologyGraph from "@/components/OntologyGraph";
import type { GraphData } from "@/lib/data";

type Mode = "STRUCTURE" | "EVENTS" | "FACTORS";

const MODES: { key: Mode; label: string }[] = [
  { key: "EVENTS", label: "이벤트 전파" },
  { key: "STRUCTURE", label: "포트폴리오 구조" },
  { key: "FACTORS", label: "팩터 연결" },
];

const EVENT_TYPES = new Set(["DisclosureEvent", "EarningsEvent", "MacroEvent", "NewsEvent"]);

interface Props {
  graph: GraphData;
  colors: Record<string, string>;
  impactPaths: Record<string, string[][]>;
  sectors: { sectorId: string; nameKo?: string }[];
}

function filterGraph(graph: GraphData, mode: Mode, sectorId: string | null): GraphData {
  const keepTypes = new Set<string>(
    mode === "STRUCTURE"
      ? ["Portfolio", "Position", "Instrument", "Sector"]
      : mode === "FACTORS"
        ? ["Instrument", "Factor", "Sector"]
        : ["Portfolio", "Position", "Instrument", "Sector", ...EVENT_TYPES],
  );
  let nodes = graph.nodes.filter((n) => keepTypes.has(n.objectType));

  if (sectorId) {
    const instInSector = new Set(
      graph.edges
        .filter((e) => e.linkType === "instrumentInSector" && e.target === `Sector:${sectorId}`)
        .map((e) => e.source),
    );
    nodes = nodes.filter((n) => {
      if (n.objectType === "Instrument") return instInSector.has(n.id);
      if (n.objectType === "Position") return instInSector.has(`Instrument:${n.props.instrumentId}`);
      if (n.objectType === "Sector") return n.pk === sectorId;
      if (n.objectType === "Portfolio") return true;
      if (EVENT_TYPES.has(n.objectType) || n.objectType === "Factor") return true; // 엣지 기준 재정리 아래에서
      return false;
    });
  }
  const ids = new Set(nodes.map((n) => n.id));
  let edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  // 섹터 필터 시: 남은 종목과 연결되지 않은 이벤트/팩터 제거
  if (sectorId) {
    const connected = new Set<string>();
    for (const e of edges) {
      const st = e.source.split(":")[0];
      const tt = e.target.split(":")[0];
      if ((EVENT_TYPES.has(st) || st === "Factor") && (tt === "Instrument" || tt === "Sector")) {
        connected.add(e.source);
      }
      if ((EVENT_TYPES.has(tt) || tt === "Factor") && (st === "Instrument" || st === "Sector")) {
        connected.add(e.target);
      }
    }
    nodes = nodes.filter((n) =>
      !(EVENT_TYPES.has(n.objectType) || n.objectType === "Factor") || connected.has(n.id));
    const ids2 = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => ids2.has(e.source) && ids2.has(e.target));
  }
  // 이벤트 모드에서 팩터 엣지 제거 (다이어트), 팩터 모드에서 이벤트 엣지 제거
  if (mode === "EVENTS") edges = edges.filter((e) => e.linkType !== "exposure");
  if (mode === "FACTORS") {
    edges = edges.filter((e) => ["exposure", "instrumentInSector"].includes(e.linkType));
  }
  const finalIds = new Set<string>();
  for (const e of edges) { finalIds.add(e.source); finalIds.add(e.target); }
  // 고립 노드 정리 (포트폴리오 허브는 유지)
  nodes = nodes.filter((n) => finalIds.has(n.id) || n.objectType === "Portfolio");
  return { nodes, edges };
}

function GraphWithControls({ graph, colors, impactPaths, sectors }: Props) {
  const params = useSearchParams();
  const focusPk = params.get("focus");
  const [mode, setMode] = useState<Mode>("EVENTS");
  const [sectorId, setSectorId] = useState<string | null>(null);

  const filtered = useMemo(() => filterGraph(graph, mode, sectorId), [graph, mode, sectorId]);
  const focusNode = focusPk
    ? filtered.nodes.find((n) => n.pk === focusPk || n.id === focusPk) ?? null
    : null;
  const focusPaths = focusPk ? impactPaths[focusPk] ?? null : null;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {MODES.map((m) => (
          <button key={m.key} className="pill pill-tab" data-active={mode === m.key} aria-pressed={mode === m.key}
                  onClick={() => setMode(m.key)}>
            {m.label}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
        <button className="pill pill-tab" data-active={sectorId === null} aria-pressed={sectorId === null}
                style={{ fontSize: 14, padding: "5px 14px" }}
                onClick={() => setSectorId(null)}>
          모든 섹터
        </button>
        {sectors.map((s) => (
          <button key={s.sectorId} className="pill pill-tab" data-active={sectorId === s.sectorId} aria-pressed={sectorId === s.sectorId}
                  style={{ fontSize: 14, padding: "5px 14px" }}
                  onClick={() => setSectorId(sectorId === s.sectorId ? null : s.sectorId)}>
            {s.nameKo ?? s.sectorId}
          </button>
        ))}
      </div>
      <OntologyGraph graph={filtered} colors={colors} focusId={focusNode?.id ?? null}
                     focusPaths={focusPaths} height={680} />
      <p className="caption" style={{ marginTop: 10 }}>
        이벤트는 최근 7일 영향도 상위 12건만 표시. 전체는 이벤트 탭에서.
      </p>
    </div>
  );
}

export default function GraphClient(props: Props) {
  return (
    <Suspense fallback={<div className="hairline-card" style={{ height: 680 }} />}>
      <GraphWithControls {...props} />
    </Suspense>
  );
}
