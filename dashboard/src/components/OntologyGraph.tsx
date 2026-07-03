"use client";

// 온톨로지 그래프 — Cytoscape.js + dagre (계층형 LR: Event → Factor/Instrument → Position → Portfolio)
// 노드 색 = DESIGN.md 파스텔 토큰 (schema.json color 필드)
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphData } from "@/lib/data";
import { fmtPct } from "@/lib/format";

cytoscape.use(dagre);

const TOKEN_HEX: Record<string, string> = {
  "block-lime": "#dceeb1", "block-lilac": "#c5b0f4", "block-cream": "#f4ecd6",
  "block-pink": "#efd4d4", "block-mint": "#c8e6cd", "block-coral": "#f3c9b6",
  "block-navy": "#1f1d3d", "surface-soft": "#f7f7f5",
};

const TYPE_LABELS: Record<string, string> = {
  Portfolio: "포트폴리오", Position: "포지션", Instrument: "종목", Factor: "팩터",
  Sector: "섹터",
  DisclosureEvent: "공시", EarningsEvent: "실적", MacroEvent: "매크로", NewsEvent: "뉴스",
  Insight: "인사이트",
};

export interface GraphSelection {
  id: string; objectType: string; pk: string; label: string;
  props: Record<string, unknown>;
}

export default function OntologyGraph({
  graph, colors, focusId, focusPaths, height = 640,
}: {
  graph: GraphData;
  colors: Record<string, string>; // objectType → 토큰명
  focusId?: string | null;
  focusPaths?: string[][] | null; // 전파 경로 노드 id 시퀀스 (impacts.paths[].nodes)
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [selected, setSelected] = useState<GraphSelection | null>(null);

  const elements = useMemo(() => {
    const nodeIds = new Set(graph.nodes.map((n) => n.id));
    return [
      ...graph.nodes.map((n) => {
        const token = (n.objectType === "Sector" && typeof n.props.colorToken === "string")
          ? n.props.colorToken
          : colors[n.objectType] ?? "";
        return {
          data: {
            id: n.id, label: n.label, objectType: n.objectType, pk: n.pk,
            props: n.props,
            bg: TOKEN_HEX[token] ?? "#f7f7f5",
            fg: token === "block-navy" ? "#ffffff" : "#000000",
          },
        };
      }),
      ...graph.edges
        .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e, i) => {
          const beta = e.props?.beta as number | undefined;
          const relevance = e.props?.relevance as number | undefined;
          return {
            data: {
              id: `e${i}`, source: e.source, target: e.target, linkType: e.linkType,
              width: e.linkType === "exposure"
                ? Math.min(4, 0.8 + Math.abs(beta ?? 0) * 1.6)
                : e.linkType.startsWith("event")
                  ? Math.min(4, 0.8 + (relevance ?? 0) * 2.5)
                  : 1,
              style: e.linkType === "exposure" ? "dashed" : "solid",
              color: e.linkType.startsWith("event") ? "#c98484" : "#c4c4c4",
            },
          };
        }),
    ];
  }, [graph, colors]);

  useEffect(() => {
    if (!ref.current) return;
    const cy = cytoscape({
      container: ref.current,
      elements,
      wheelSensitivity: 0.2,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(bg)",
            color: "data(fg)",
            label: "data(label)",
            "font-size": 11,
            "font-family": "var(--font-sans), var(--font-kr), sans-serif",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "110px",
            shape: "round-rectangle",
            width: "label",
            height: "label",
            "padding": "10px",
            "border-width": 1,
            "border-color": "#00000022",
            "corner-radius": "8px",
          } as never,
        },
        {
          selector: "edge",
          style: {
            width: "data(width)",
            "line-color": "data(color)",
            "line-style": "data(style)" as never,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "data(color)",
            "arrow-scale": 0.7,
          } as never,
        },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#000000" } },
        { selector: ".dim", style: { opacity: 0.15 } },
        { selector: ".hot", style: { "border-width": 3, "border-color": "#ff3d8b" } },
      ],
      layout: {
        name: "dagre", rankDir: "LR", nodeSep: 18, rankSep: 120, edgeSep: 10,
      } as never,
    });
    cyRef.current = cy;

    cy.on("tap", "node", (evt) => {
      const d = evt.target.data();
      setSelected({ id: d.id, objectType: d.objectType, pk: d.pk, label: d.label, props: d.props ?? {} });
      // 연결 경로 하이라이트
      cy.elements().addClass("dim");
      const hood = evt.target.closedNeighborhood();
      hood.removeClass("dim");
      evt.target.removeClass("dim");
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        cy.elements().removeClass("dim").removeClass("hot");
        setSelected(null);
      }
    });

    if (focusId) {
      const node = cy.getElementById(focusId);
      if (node.nonempty()) {
        node.select();
        cy.elements().addClass("dim");
        let lit = node.closedNeighborhood();
        // 전파 경로(임팩트 리포트)가 있으면 포트폴리오까지의 정확한 경로를 밝힌다
        if (focusPaths && focusPaths.length) {
          for (const path of focusPaths) {
            for (let i = 0; i < path.length; i++) {
              const n = cy.getElementById(path[i]);
              if (n.nonempty()) lit = lit.union(n);
              if (i > 0) {
                const a = path[i - 1], b = path[i];
                const edge = cy.edges().filter((e) =>
                  (e.source().id() === a && e.target().id() === b) ||
                  (e.source().id() === b && e.target().id() === a));
                if (edge.nonempty()) lit = lit.union(edge);
              }
            }
          }
        }
        lit.removeClass("dim");
        node.addClass("hot");
        cy.animate({ fit: { eles: lit, padding: 60 }, duration: 400 });
      }
    }
    return () => { cy.destroy(); };
  }, [elements, focusId, focusPaths]);

  return (
    <div style={{ position: "relative" }}>
      <div ref={ref} style={{ height, background: "var(--canvas)", borderRadius: "var(--r-lg)", border: "1px solid var(--hairline)" }} />
      <div style={{ position: "absolute", left: 16, bottom: 16, display: "flex", gap: 8, flexWrap: "wrap", maxWidth: "70%" }}>
        {Object.entries(colors)
          .filter(([t]) => TYPE_LABELS[t])
          .map(([t, token]) => (
            <span key={t} className="caption" style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              background: "#ffffffdd", padding: "4px 10px", borderRadius: 999, border: "1px solid var(--hairline)",
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: 3,
                background: TOKEN_HEX[token] ?? "#eee", border: "1px solid #00000022",
              }} />
              {TYPE_LABELS[t]}
            </span>
          ))}
      </div>
      {selected && (
        <aside className="hairline-card" style={{
          position: "absolute", right: 16, top: 16, width: 300, maxHeight: "80%",
          overflowY: "auto", background: "#fffffff5",
        }}>
          <div className="caption">{TYPE_LABELS[selected.objectType] ?? selected.objectType}</div>
          <div className="card-title" style={{ margin: "6px 0 10px" }}>{selected.label}</div>
          <dl className="body-sm" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px" }}>
            {Object.entries(selected.props)
              .filter(([, v]) => v != null && typeof v !== "object")
              .slice(0, 8)
              .map(([k, v]) => (
                <FragmentRow key={k} k={k} v={v} />
              ))}
          </dl>
          {selected.objectType === "Instrument" && (
            <Link className="pill pill-primary" style={{ marginTop: 14, fontSize: 14, padding: "6px 14px" }}
                  href={`/instruments/${selected.pk.replace(/:/g, "_")}/`}>
              종목 상세 →
            </Link>
          )}
        </aside>
      )}
    </div>
  );
}

function FragmentRow({ k, v }: { k: string; v: unknown }) {
  let display = String(v);
  if (typeof v === "number" && ["weight", "severity", "relevance"].includes(k)) display = fmtPct(v, 1);
  else if (typeof v === "number") display = v.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
  return (
    <>
      <dt className="caption" style={{ alignSelf: "center" }}>{k}</dt>
      <dd style={{ fontWeight: 480, wordBreak: "break-all" }}>{display}</dd>
    </>
  );
}
