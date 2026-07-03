"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import OntologyGraph from "@/components/OntologyGraph";
import type { GraphData } from "@/lib/data";

interface Props {
  graph: GraphData;
  colors: Record<string, string>;
  impactPaths: Record<string, string[][]>;
}

function GraphWithFocus({ graph, colors, impactPaths }: Props) {
  const params = useSearchParams();
  const focusPk = params.get("focus");
  // focus 파라미터는 eventId(pk) — 노드 id 는 "{Type}:{pk}" 이므로 탐색
  const focusNode = focusPk
    ? graph.nodes.find((n) => n.pk === focusPk || n.id === focusPk) ?? null
    : null;
  const focusPaths = focusPk ? impactPaths[focusPk] ?? null : null;
  return (
    <OntologyGraph graph={graph} colors={colors} focusId={focusNode?.id ?? null}
                   focusPaths={focusPaths} height={680} />
  );
}

export default function GraphClient(props: Props) {
  return (
    <Suspense fallback={<div className="hairline-card" style={{ height: 680 }} />}>
      <GraphWithFocus {...props} />
    </Suspense>
  );
}
