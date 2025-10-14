"use client";

import { useEffect, useMemo, useRef } from "react";

type Row = Record<string, unknown>;

type MiniGraphProps = {
  rows: Row[];
  height?: number;
};

type CytoscapeModule = {
  default?: any;
};

function normalizeString(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value.trim();
  return undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!value) return undefined;
  if (Array.isArray(value)) return value.map((v) => String(v));
  return [String(value)];
}

function inferEffectCategory(effect: string | undefined): "resistance" | "sensitivity" | "unknown" {
  if (!effect) return "unknown";
  const e = effect.toLowerCase();
  if (e.includes("resist")) return "resistance";
  if (e.includes("sensit") || e.includes("responsive") || e.includes("benefit") || e.includes("response")) return "sensitivity";
  return "unknown";
}

export function MiniGraph({ rows, height = 320 }: MiniGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<any>(null);

  const elements = useMemo(() => {
    const nodeMap = new Map<string, { data: Record<string, unknown> }>();
    const edgeMap = new Map<string, { data: Record<string, unknown> }>();

    const addNode = (id: string, label: string, kind: string) => {
      if (!nodeMap.has(id)) {
        nodeMap.set(id, { data: { id, label, kind } });
      }
    };

    const addEdge = (id: string, source: string, target: string, label: string, meta: Record<string, unknown>) => {
      if (!edgeMap.has(id)) {
        edgeMap.set(id, { data: { id, source, target, label, ...meta } });
      }
    };

    for (const row of rows) {
      const geneSymbol = normalizeString(row["gene_symbol"]);
      const variantName = normalizeString(row["variant_name"]);
      const therapyName = normalizeString(row["therapy_name"]);
      const diseaseName = normalizeString(row["disease_name"]);
      const effect = normalizeString(row["effect"]);
      const pmids = asStringArray(row["pmids"]) || [];

      const effectCategory = inferEffectCategory(effect);

      let biomarkerNodeId: string | undefined;

      if (variantName) {
        const variantId = `Variant:${variantName}`;
        addNode(variantId, variantName, "Variant");
        biomarkerNodeId = variantId;

        if (geneSymbol) {
          const geneId = `Gene:${geneSymbol}`;
          addNode(geneId, geneSymbol, "Gene");
          const edgeId = `VARIANT_OF|${variantId}|${geneId}`;
          addEdge(edgeId, variantId, geneId, "VARIANT_OF", { relationship: "VARIANT_OF" });
        }
      } else if (geneSymbol) {
        const geneId = `Gene:${geneSymbol}`;
        addNode(geneId, geneSymbol, "Gene");
        biomarkerNodeId = geneId;
      }

      if (therapyName) {
        const therapyId = `Therapy:${therapyName}`;
        addNode(therapyId, therapyName, "Therapy");
        if (biomarkerNodeId) {
          const labelParts = [effect || "AFFECTS_RESPONSE_TO"];
          if (diseaseName) labelParts.push(`(${diseaseName})`);
          const label = labelParts.join(" ");
          const edgeId = `AFFECTS_RESPONSE_TO|${biomarkerNodeId}|${therapyId}|${label}`;
          addEdge(edgeId, biomarkerNodeId, therapyId, label, {
            relationship: "AFFECTS_RESPONSE_TO",
            effect,
            effectCategory,
            disease: diseaseName,
            pmidCount: pmids.length,
          });
        }
      }
    }

    return {
      nodes: Array.from(nodeMap.values()),
      edges: Array.from(edgeMap.values()),
    };
  }, [rows]);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      const cytoscapeMod: CytoscapeModule = await import("cytoscape");
      const cytoscape = (cytoscapeMod as any).default ?? (cytoscapeMod as any);
      const coseBilkentMod: CytoscapeModule = await import("cytoscape-cose-bilkent");
      const coseBilkent = (coseBilkentMod as any).default ?? (coseBilkentMod as any);
      cytoscape.use(coseBilkent);

      if (cancelled || !containerRef.current) return;

      const cy = cytoscape({
        container: containerRef.current,
        elements: [...elements.nodes, ...elements.edges],
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "font-size": 12,
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": 120,
              "background-color": "#e5e7eb",
              color: "#0f172a",
              "border-width": 1,
              "border-color": "#cbd5e1",
              width: 28,
              height: 28,
            },
          },
          { selector: 'node[kind = "Gene"]', style: { shape: "ellipse", "background-color": "#bfdbfe", "border-color": "#60a5fa" } },
          { selector: 'node[kind = "Variant"]', style: { shape: "diamond", "background-color": "#ddd6fe", "border-color": "#a78bfa" } },
          { selector: 'node[kind = "Therapy"]', style: { shape: "round-rectangle", "background-color": "#fed7aa", "border-color": "#fb923c" } },

          {
            selector: "edge",
            style: {
              label: "data(label)",
              "font-size": 11,
              "text-rotation": "autorotate",
              "text-wrap": "wrap",
              "text-max-width": 160,
              width: 2,
              "line-color": "#94a3b8",
              "target-arrow-color": "#94a3b8",
              "curve-style": "bezier",
              "target-arrow-shape": "triangle",
            },
          },
          { selector: 'edge[effectCategory = "resistance"]', style: { "line-color": "#dc2626", "target-arrow-color": "#dc2626" } },
          { selector: 'edge[effectCategory = "sensitivity"]', style: { "line-color": "#16a34a", "target-arrow-color": "#16a34a" } },
        ],
        layout: { name: "cose-bilkent", animate: "end", nodeDimensionsIncludeLabels: true },
      });

      cyRef.current = cy;
    }

    init();

    return () => {
      cancelled = true;
      try {
        cyRef.current?.destroy();
      } catch {
        // ignore
      }
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!cyRef.current) return;
    const cy = cyRef.current as any;
    cy.elements().remove();
    cy.add([...elements.nodes, ...elements.edges]);
    const layout = cy.layout({ name: "cose-bilkent", animate: "end", nodeDimensionsIncludeLabels: true });
    layout.run();
  }, [elements]);

  if (!rows || rows.length === 0) {
    return (
      <div
        style={{
          height,
          borderRadius: "0.5rem",
          border: "1px dashed #e5e7eb",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#6b7280",
          background: "#fafafa",
        }}
      >
        No rows to visualize
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        height,
        width: "100%",
        background: "#ffffff",
        border: "1px solid #e5e7eb",
        borderRadius: "0.75rem",
      }}
    />
  );
}

export default MiniGraph;
