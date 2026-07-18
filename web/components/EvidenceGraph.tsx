import type { Case } from "@/lib/types";
import { VERDICT_META } from "@/lib/format";

interface Node {
  id: string;
  label: string;
  kind: "step" | "entity" | "verdict";
  x: number;
  y: number;
}

interface Edge {
  from: string;
  to: string;
}

const ENTITY_RE = /\b[A-Z]{2,}(?:[-_][A-Z0-9]+)+\b|\bINV\d+\b/g;

function extractEntities(text: string): string[] {
  const matches = text.match(ENTITY_RE) ?? [];
  return Array.from(new Set(matches)).slice(0, 3);
}

function buildGraph(c: Case) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const stepSpacing = 180;
  const baseY = 130;

  c.evidence_chain.forEach((step, i) => {
    const stepId = `step-${i}`;
    const x = 90 + i * stepSpacing;
    nodes.push({ id: stepId, label: step.step, kind: "step", x, y: baseY });
    if (i > 0) edges.push({ from: `step-${i - 1}`, to: stepId });

    const text = step.evidence.map((e) => `${e.raw_value} ${e.source_path}`).join(" ");
    const entities = extractEntities(text.toUpperCase());
    entities.forEach((entity, j) => {
      const entityId = `${stepId}-e${j}`;
      const above = j % 2 === 0;
      nodes.push({
        id: entityId,
        label: entity,
        kind: "entity",
        x: x + (j - (entities.length - 1) / 2) * 34,
        y: above ? baseY - 62 : baseY + 62,
      });
      edges.push({ from: stepId, to: entityId });
    });
  });

  const verdictId = "verdict";
  const lastX = 90 + Math.max(c.evidence_chain.length - 1, 0) * stepSpacing + stepSpacing;
  nodes.push({ id: verdictId, label: c.verdict.replace("_", " "), kind: "verdict", x: lastX, y: baseY });
  if (c.evidence_chain.length > 0) {
    edges.push({ from: `step-${c.evidence_chain.length - 1}`, to: verdictId });
  }

  const width = lastX + 110;
  const height = 260;
  return { nodes, edges, width, height };
}

export default function EvidenceGraph({ c }: { c: Case }) {
  const { nodes, edges, width, height } = buildGraph(c);
  const meta = VERDICT_META[c.verdict];
  const byId = new Map(nodes.map((n) => [n.id, n]));

  if (c.evidence_chain.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-2)" }}>
        No evidence chain to visualize.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto border rounded-sm py-4" style={{ borderColor: "var(--hairline)" }}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block mx-auto"
        role="img"
        aria-label="Evidence chain graph"
      >
        {edges.map((e, i) => {
          const from = byId.get(e.from);
          const to = byId.get(e.to);
          if (!from || !to) return null;
          return (
            <line
              key={i}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="var(--hairline-strong)"
              strokeWidth={1.25}
              strokeDasharray={from.kind === "entity" || to.kind === "entity" ? "3 3" : undefined}
            />
          );
        })}

        {nodes.map((n) => {
          if (n.kind === "step") {
            return (
              <g key={n.id}>
                <rect
                  x={n.x - 46}
                  y={n.y - 16}
                  width={92}
                  height={32}
                  rx={3}
                  fill="var(--ink-2)"
                  stroke="var(--amber)"
                  strokeWidth={1.25}
                />
                <text
                  x={n.x}
                  y={n.y + 4}
                  textAnchor="middle"
                  fontSize={9.5}
                  fill="var(--text-1)"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {n.label.length > 20 ? n.label.slice(0, 18) + "…" : n.label}
                </text>
              </g>
            );
          }
          if (n.kind === "verdict") {
            return (
              <g key={n.id}>
                <circle cx={n.x} cy={n.y} r={26} fill={meta.glow} stroke={meta.border} strokeWidth={1.5} />
                <text
                  x={n.x}
                  y={n.y + 3}
                  textAnchor="middle"
                  fontSize={8.5}
                  fill={meta.color}
                  style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.05em" }}
                >
                  {n.label}
                </text>
              </g>
            );
          }
          return (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r={16} fill="var(--ink-3)" stroke="var(--steel)" strokeWidth={1} />
              <text
                x={n.x}
                y={n.y + 3}
                textAnchor="middle"
                fontSize={6.5}
                fill="var(--text-1)"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {n.label.length > 10 ? n.label.slice(0, 9) + "…" : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
