"use client";

import { useMemo } from "react";
import { useInvestigation } from "@/lib/investigation-context";

const KIND_STYLE: Record<string, { fill: string; stroke: string; r: number }> = {
  entity: { fill: "var(--ink-3)", stroke: "var(--steel)", r: 20 },
  event: { fill: "var(--ink-2)", stroke: "var(--text-2)", r: 16 },
  hypothesis: { fill: "var(--amber-glow)", stroke: "var(--amber)", r: 26 },
};

export default function InvestigationGraphView() {
  const { graph } = useInvestigation();

  const layout = useMemo(() => {
    const cols = Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length)));
    const spacingX = 130;
    const spacingY = 90;
    const positioned = graph.nodes.map((n, i) => ({
      ...n,
      x: 70 + (i % cols) * spacingX,
      y: 60 + Math.floor(i / cols) * spacingY,
    }));
    const width = 70 + cols * spacingX;
    const height = 60 + Math.ceil(graph.nodes.length / cols) * spacingY;
    return { nodes: positioned, width, height };
  }, [graph]);

  if (graph.nodes.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-2)" }}>
        No evidence graph available yet.
      </p>
    );
  }

  const byId = new Map(layout.nodes.map((n) => [n.id, n]));

  return (
    <div className="overflow-x-auto border rounded-sm py-4" style={{ borderColor: "var(--hairline)" }}>
      <svg width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} className="block mx-auto" role="img" aria-label="Evidence graph">
        {graph.edges.map((e, i) => {
          const from = byId.get(e.from);
          const to = byId.get(e.to);
          if (!from || !to) return null;
          return (
            <g key={i}>
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="var(--hairline-strong)" strokeWidth={1.25} />
              {e.label && (
                <text
                  x={(from.x + to.x) / 2}
                  y={(from.y + to.y) / 2 - 4}
                  textAnchor="middle"
                  fontSize={7.5}
                  fill="var(--text-2)"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {e.label}
                </text>
              )}
            </g>
          );
        })}
        {layout.nodes.map((n) => {
          const style = KIND_STYLE[n.kind] ?? KIND_STYLE.entity;
          return (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r={style.r} fill={style.fill} stroke={style.stroke} strokeWidth={1.25} />
              <text
                x={n.x}
                y={n.y + 3}
                textAnchor="middle"
                fontSize={8}
                fill="var(--text-1)"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {n.label.length > 12 ? n.label.slice(0, 11) + "…" : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
