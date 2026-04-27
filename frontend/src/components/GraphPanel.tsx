"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type cytoscape from "cytoscape";

import {
  GRAPH_STREAM_URL,
  getGraphSnapshot,
  type GraphEdge,
  type GraphNode,
  type GraphSnapshot,
} from "@/lib/api";

// react-cytoscapejs bundles a DOM canvas — must render client-only.
const CytoscapeComponent = dynamic(() => import("react-cytoscapejs"), {
  ssr: false,
});

const STYLES: cytoscape.Stylesheet[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-size": 11,
      color: "#E2E2E6",
      "text-outline-color": "#1A1C1E",
      "text-outline-width": 2,
      "text-valign": "center",
      "text-halign": "center",
      "background-color": "#A8C8FF",
      width: 36,
      height: 36,
    },
  },
  {
    selector: 'node[kind = "episode"]',
    style: {
      "background-color": "#BBC7DB",
      shape: "round-rectangle",
      width: 70,
      height: 28,
      "font-size": 9,
      "text-wrap": "ellipsis",
      "text-max-width": "62px",
    },
  },
  {
    selector: "edge",
    style: {
      label: "data(label)",
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "line-color": "#8C9198",
      "target-arrow-color": "#8C9198",
      "font-size": 9,
      color: "#C2C7CF",
      "text-rotation": "autorotate",
      "text-background-color": "#1A1C1E",
      "text-background-opacity": 0.85,
      "text-background-padding": "2px",
      width: 1.4,
    },
  },
  {
    selector: 'edge[kind = "mentions"]',
    style: {
      "line-style": "dashed",
      "line-color": "#42474E",
      "target-arrow-color": "#42474E",
      width: 1,
    },
  },
  {
    selector: "edge[?invalid_at]",
    style: {
      "line-style": "dotted",
      "line-color": "#FFB4AB",
      "target-arrow-color": "#FFB4AB",
    },
  },
  {
    selector: ".flash",
    style: {
      "background-color": "#D6E4FF",
      "line-color": "#D6E4FF",
      "target-arrow-color": "#D6E4FF",
      width: 3,
    },
  },
];

const LAYOUT: cytoscape.LayoutOptions = {
  name: "cose",
  animate: true,
  animationDuration: 600,
  // @ts-expect-error - cose accepts these even if not in the lean TS type
  nodeRepulsion: 8000,
  idealEdgeLength: 90,
  fit: true,
  padding: 20,
};

type SelectedKind =
  | { kind: "node"; data: GraphNode["data"] }
  | { kind: "edge"; data: GraphEdge["data"] }
  | null;

export function GraphPanel() {
  const [snapshot, setSnapshot] = useState<GraphSnapshot>({
    nodes: [],
    edges: [],
    enabled: true,
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [selected, setSelected] = useState<SelectedKind>(null);
  // Live ingest progress, driven by SSE events from /graph/stream.
  const [ingestProgress, setIngestProgress] = useState<{
    total: number;
    done: number;
    active: boolean;
  }>({ total: 0, done: 0, active: false });
  const cyRef = useRef<cytoscape.Core | null>(null);
  const prevIdsRef = useRef<{ nodes: Set<string>; edges: Set<string> }>({
    nodes: new Set(),
    edges: new Set(),
  });

  const refresh = useCallback(async () => {
    try {
      const snap = await getGraphSnapshot();
      setSnapshot(snap);
      setError(snap.error ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    refresh();
  }, [refresh]);

  // SSE: refetch when the backend emits a change event
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(GRAPH_STREAM_URL);
      es.addEventListener("hello", () => setStreaming(true));
      es.addEventListener("episode_added", () => {
        // Small delay so Graphiti's writes are visible by the time we re-query
        setTimeout(refresh, 250);
        setIngestProgress((p) => (p.active ? { ...p, done: p.done + 1 } : p));
      });
      es.addEventListener("ingest_started", (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data ?? "{}");
          setIngestProgress({ total: data.total ?? 0, done: 0, active: true });
        } catch {
          setIngestProgress({ total: 0, done: 0, active: true });
        }
      });
      es.addEventListener("ingest_complete", () => {
        setIngestProgress((p) => ({ ...p, active: false }));
      });
      es.addEventListener("ping", () => {
        /* heartbeat — keep alive */
      });
      es.onerror = () => {
        setStreaming(false);
      };
    } catch {
      setStreaming(false);
    }
    return () => es?.close();
  }, [refresh]);

  // Flash newly-arrived nodes/edges so the user can see what changed
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const newNodeIds = new Set(snapshot.nodes.map((n) => n.data.id));
    const newEdgeIds = new Set(snapshot.edges.map((e) => e.data.id));
    const addedNodes = [...newNodeIds].filter((id) => !prevIdsRef.current.nodes.has(id));
    const addedEdges = [...newEdgeIds].filter((id) => !prevIdsRef.current.edges.has(id));
    addedNodes.concat(addedEdges).forEach((id) => {
      const el = cy.getElementById(id);
      if (el && el.length) {
        el.addClass("flash");
        setTimeout(() => el.removeClass("flash"), 1400);
      }
    });
    prevIdsRef.current = { nodes: newNodeIds, edges: newEdgeIds };
  }, [snapshot]);

  const elements = useMemo(
    () => [...snapshot.nodes, ...snapshot.edges],
    [snapshot]
  );

  const onCyInit = useCallback((cy: cytoscape.Core) => {
    cyRef.current = cy;
    cy.on("tap", "node", (evt) => {
      setSelected({ kind: "node", data: evt.target.data() });
    });
    cy.on("tap", "edge", (evt) => {
      setSelected({ kind: "edge", data: evt.target.data() });
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelected(null);
    });
  }, []);

  const counts = useMemo(() => {
    const entities = snapshot.nodes.filter((n) => n.data.kind === "entity").length;
    const episodes = snapshot.nodes.filter((n) => n.data.kind === "episode").length;
    const relates = snapshot.edges.filter((e) => e.data.kind === "relates_to").length;
    const invalidated = snapshot.edges.filter((e) => !!e.data.invalid_at).length;
    return { entities, episodes, relates, invalidated };
  }, [snapshot]);

  return (
    <section className="card" style={{ gridColumn: "1 / -1" }}>
      <h2 className="card-title">Graphiti knowledge graph</h2>
      <p className="card-subtitle">
        Live view of entities and relationships extracted by Graphiti. Edges flash on arrival;
        invalidated facts (superseded over time) are dotted red.
      </p>

      <div style={statsRowStyle}>
        <Stat label="Entities" value={counts.entities} />
        <Stat label="Episodes" value={counts.episodes} />
        <Stat label="Relates-to" value={counts.relates} />
        <Stat label="Invalidated" value={counts.invalidated} />
        <span
          className="chip"
          title={streaming ? "Live updates connected" : "Live updates offline"}
          style={{
            marginLeft: "auto",
            background: streaming ? "var(--md-primary-container)" : "var(--md-error-container)",
            color: streaming ? "var(--md-on-primary-container)" : "var(--md-on-error-container)",
          }}
        >
          {streaming ? "● live" : "○ offline"}
        </span>
      </div>

      {ingestProgress.active && (
        <div style={progressBoxStyle}>
          Graphiti is extracting entities… {ingestProgress.done}
          {ingestProgress.total > 0 ? ` / ${ingestProgress.total}` : ""} doc(s) processed.
        </div>
      )}

      {!snapshot.enabled && (
        <div style={infoBox}>
          Graphiti is disabled on the backend. Set <code>ENABLE_GRAPHITI=true</code> in
          <code> backend/.env</code> and run <code>docker compose up neo4j</code>.
        </div>
      )}
      {error && <div style={errorBox} className="mono">{error}</div>}

      <div style={canvasWrapStyle}>
        <CytoscapeComponent
          elements={elements}
          stylesheet={STYLES}
          layout={LAYOUT}
          cy={onCyInit}
          style={{ width: "100%", height: "100%" }}
          minZoom={0.2}
          maxZoom={2.5}
        />
        {loading && (
          <div style={overlayStyle}>Loading graph…</div>
        )}
        {!loading && elements.length === 0 && snapshot.enabled && (
          <div style={overlayStyle}>
            Empty graph. Ingest a doc or send a chat — entities will appear here.
          </div>
        )}
      </div>

      {selected && <SelectionPanel selected={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div style={statStyle}>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--md-on-surface-variant)" }}>{label}</div>
    </div>
  );
}

function SelectionPanel({
  selected,
  onClose,
}: {
  selected: NonNullable<SelectedKind>;
  onClose: () => void;
}) {
  const { kind, data } = selected;
  return (
    <div style={selectionStyle}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>
          {kind === "node" ? "Node" : "Edge"} • {data.kind ?? ""}
        </strong>
        <button onClick={onClose} className="button" style={{ marginLeft: "auto", padding: "2px 10px" }}>
          ×
        </button>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.5 }}>
        <div><b>Label:</b> {(data as GraphNode["data"] | GraphEdge["data"]).label}</div>
        {kind === "node" && (data as GraphNode["data"]).summary && (
          <div style={{ marginTop: 4 }}>
            <b>Summary:</b> {(data as GraphNode["data"]).summary}
          </div>
        )}
        {kind === "edge" && (data as GraphEdge["data"]).fact && (
          <div style={{ marginTop: 4 }}>
            <b>Fact:</b> {(data as GraphEdge["data"]).fact}
          </div>
        )}
        {kind === "edge" && (data as GraphEdge["data"]).valid_at && (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--md-on-surface-variant)" }}>
            valid_at: {(data as GraphEdge["data"]).valid_at}
          </div>
        )}
        {kind === "edge" && (data as GraphEdge["data"]).invalid_at && (
          <div style={{ fontSize: 12, color: "var(--md-error)" }}>
            invalid_at: {(data as GraphEdge["data"]).invalid_at}
          </div>
        )}
      </div>
    </div>
  );
}

const statsRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  marginTop: 6,
  marginBottom: 10,
};
const statStyle: React.CSSProperties = {
  background: "var(--md-surface-container-high)",
  padding: "6px 12px",
  borderRadius: 10,
  border: "1px solid var(--md-outline-variant)",
  textAlign: "center",
  minWidth: 70,
};
const canvasWrapStyle: React.CSSProperties = {
  position: "relative",
  height: 460,
  borderRadius: 12,
  background: "var(--md-surface-container-lowest)",
  border: "1px solid var(--md-outline-variant)",
  overflow: "hidden",
};
const overlayStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "var(--md-on-surface-variant)",
  fontSize: 13,
  pointerEvents: "none",
};
const infoBox: React.CSSProperties = {
  padding: "10px 14px",
  borderRadius: 12,
  background: "var(--md-surface-container)",
  marginBottom: 10,
  fontSize: 13,
};
const errorBox: React.CSSProperties = {
  padding: "10px 14px",
  borderRadius: 12,
  background: "var(--md-error-container)",
  color: "var(--md-on-error-container)",
  marginBottom: 10,
  fontSize: 13,
};
const selectionStyle: React.CSSProperties = {
  marginTop: 12,
  padding: "12px 14px",
  borderRadius: 12,
  background: "var(--md-surface-container)",
  border: "1px solid var(--md-outline-variant)",
};
const progressBoxStyle: React.CSSProperties = {
  padding: "8px 14px",
  marginBottom: 10,
  borderRadius: 12,
  background: "var(--md-primary-container)",
  color: "var(--md-on-primary-container)",
  fontSize: 13,
};
