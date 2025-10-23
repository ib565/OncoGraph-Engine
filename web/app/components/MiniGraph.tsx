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
  const becameVisibleRef = useRef<boolean>(false);
  const layoutNameRef = useRef<"cose-bilkent" | "grid">("grid");

  const getLayoutOptions = (name: "cose-bilkent" | "grid") => {
    if (name === "cose-bilkent") {
      return {
        name: "cose-bilkent",
        animate: "end" as const,
        nodeDimensionsIncludeLabels: true,
        fit: true,
        padding: 30,
        quality: "default",
        randomize: true,
        idealEdgeLength: 150,
        edgeElasticity: 0.45,
        nodeRepulsion: 8000,
        gravity: 0.9,
        numIter: 1000,
        tile: true,
        componentSpacing: 80,
      };
    }
    return { name: "grid", fit: true, padding: 30 } as const;
  };

  const elements = useMemo(() => {
    const nodeMap = new Map<string, { data: Record<string, unknown> }>();
    const edgeMap = new Map<string, { data: Record<string, unknown> }>();

    const safeId = (...parts: string[]): string =>
      parts
        .filter(Boolean)
        .join("|")
        .replace(/[^A-Za-z0-9._-]+/g, "_");

    const addNode = (id: string, label: string, kind: string) => {
      const sid = safeId(id);
      if (!nodeMap.has(sid)) {
        nodeMap.set(sid, { data: { id: sid, label, kind } });
      }
    };

    const addEdge = (id: string, source: string, target: string, label: string, meta: Record<string, unknown>) => {
      const sid = safeId(id);
      const sSource = safeId(source);
      const sTarget = safeId(target);
      if (!edgeMap.has(sid)) {
        edgeMap.set(sid, { data: { id: sid, source: sSource, target: sTarget, label, ...meta } });
      }
    };

    const getValueCI = (obj: Record<string, unknown>, candidates: string[]): unknown => {
      const lowerKeyToValue: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(obj)) lowerKeyToValue[k.toLowerCase()] = v;
      for (const key of candidates) {
        const v = lowerKeyToValue[key.toLowerCase()];
        if (v !== undefined && v !== null) return v;
      }
      return undefined;
    };

    for (const row of rows) {
      let geneSymbol = normalizeString(
        getValueCI(row, ["gene_symbol", "GeneSymbol", "genesymbol"]) as unknown
      );
      let variantName = normalizeString(
        getValueCI(row, ["variant_name", "VariantName", "variantname"]) as unknown
      );
      let therapyName = normalizeString(
        getValueCI(row, ["therapy_name", "TherapyName", "therapyname"]) as unknown
      );
      let diseaseName = normalizeString(
        getValueCI(row, ["disease_name", "DiseaseName", "diseasename"]) as unknown
      );
      let effect = normalizeString(
        getValueCI(row, ["effect", "RelationshipEffect", "relationship_effect", "relationshipeffect"]) as unknown
      );
      let pmids =
        asStringArray(
          getValueCI(row, ["pmids", "PMIDs", "pmid", "PMID", "pmid_list", "pmidlist"]) as unknown
        ) || [];
      const targetsMoa = normalizeString(
        getValueCI(row, ["targets_moa", "moa"]) as unknown
      );
      const hasTargetsProjection = Object.prototype.hasOwnProperty.call(
        row as Record<string, unknown>,
        "targets_moa"
      );

      // Support nested shapes: Biomarker, Therapy, and relationship objects/arrays
      const biomarkerVal = (row as Record<string, unknown>)["Biomarker"] as Record<string, unknown> | undefined;
      if (biomarkerVal && typeof biomarkerVal === "object") {
        const bSymbol = normalizeString((biomarkerVal as any)["symbol"]);
        const bName = normalizeString((biomarkerVal as any)["name"]);
        const bHgvs = normalizeString((biomarkerVal as any)["hgvs_p"]);
        if (!geneSymbol && bSymbol) geneSymbol = bSymbol;
        if (!variantName && (bName || bHgvs)) variantName = bName || bHgvs;
      }

      const therapyVal = (row as Record<string, unknown>)["Therapy"] as Record<string, unknown> | undefined;
      if (therapyVal && typeof therapyVal === "object") {
        const tName = normalizeString((therapyVal as any)["name"]);
        if (!therapyName && tName) therapyName = tName;
      }

      const relVal = (row as Record<string, unknown>)["AffectsResponseToRelationship"] as unknown;
      if (relVal) {
        if (Array.isArray(relVal)) {
          // Often serialized as [fromNode, type, toNode]
          const relType = normalizeString(relVal[1]);
          if (!effect && relType) effect = relType;
          // Pull names from the endpoints if missing
          const fromNode = relVal[0] as Record<string, unknown> | undefined;
          const toNode = relVal[2] as Record<string, unknown> | undefined;
          const fromSymbol = normalizeString((fromNode as any)?.symbol);
          const fromName = normalizeString((fromNode as any)?.name) || normalizeString((fromNode as any)?.hgvs_p);
          const toName = normalizeString((toNode as any)?.name);
          if (!geneSymbol && fromSymbol) geneSymbol = fromSymbol;
          if (!variantName && fromName) variantName = fromName;
          if (!therapyName && toName) therapyName = toName;
        } else if (typeof relVal === "object") {
          const relObj = relVal as Record<string, unknown>;
          const rEffect = normalizeString((relObj as any)["effect"]);
          const rDisease = normalizeString((relObj as any)["disease_name"] || (relObj as any)["disease"]);
          const rPmids = asStringArray((relObj as any)["pmids"]);
          if (!effect && rEffect) effect = rEffect;
          if (!diseaseName && rDisease) diseaseName = rDisease;
          if (pmids.length === 0 && rPmids) pmids = rPmids;
        }
      }

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

        // Draw predictive edges only when we have an effect value
        if (biomarkerNodeId && effect) {
          const labelParts = [effect];
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
        } else if (geneSymbol && hasTargetsProjection) {
          // Draw mechanism/targeting edges when the query projects targets_moa
          const geneId = `Gene:${geneSymbol}`;
          addNode(geneId, geneSymbol, "Gene");
          const label = "TARGETS";
          const edgeId = `TARGETS|${therapyId}|${geneId}|${label}`;
          addEdge(edgeId, therapyId, geneId, label, {
            relationship: "TARGETS",
            moa: targetsMoa,
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
      // Ensure we're on the client side
      if (typeof window === 'undefined') return;
      
      const cytoscapeMod: CytoscapeModule = await import("cytoscape");
      const cytoscape = (cytoscapeMod as any).default ?? (cytoscapeMod as any);
      let layoutName: "cose-bilkent" | "grid" = "grid";
      try {
        const coseBilkentMod: CytoscapeModule = await import("cytoscape-cose-bilkent");
        const coseBilkent = (coseBilkentMod as any).default ?? (coseBilkentMod as any);
        cytoscape.use(coseBilkent);
        layoutName = "cose-bilkent";
      } catch (err) {
        // Fallback if layout plugin unavailable
        layoutName = "grid";
      }

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
              "text-valign": "bottom",
              "text-halign": "center",
              "text-margin-y": -6,
              "text-wrap": "wrap",
              "text-max-width": 160,
              "text-background-color": "#ffffff",
              "text-background-opacity": 0.9,
              "text-background-padding": 2,
              "text-border-color": "#cbd5e1",
              "text-border-width": 1,
              "text-border-opacity": 1,
              "text-outline-color": "#ffffff",
              "text-outline-width": 2,
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
              "font-size": 10,
              "text-rotation": "autorotate",
              "text-wrap": "wrap",
              "text-max-width": 200,
              "text-background-color": "#ffffff",
              "text-background-opacity": 0.9,
              "text-background-padding": 2,
              "text-border-color": "#e5e7eb",
              "text-border-width": 1,
              "text-border-opacity": 1,
              "text-outline-color": "#ffffff",
              "text-outline-width": 2,
              width: 2,
              "line-color": "#94a3b8",
              "target-arrow-color": "#94a3b8",
              "curve-style": "bezier",
              "target-arrow-shape": "triangle",
            },
          },
          { selector: 'edge[relationship = "VARIANT_OF"]', style: { "text-opacity": 0 } },
          { selector: 'edge[effectCategory = "resistance"]', style: { "line-color": "#dc2626", "target-arrow-color": "#dc2626" } },
          { selector: 'edge[effectCategory = "sensitivity"]', style: { "line-color": "#16a34a", "target-arrow-color": "#16a34a" } },
        ],
        layout: getLayoutOptions(layoutName),
      });

      cyRef.current = cy;
      layoutNameRef.current = layoutName;
      cy.one("layoutstop", () => {
        try {
          cy.fit(undefined, 20);
        } catch {}
      });
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
    const layout = cy.layout(getLayoutOptions(layoutNameRef.current));
    layout.run();
  }, [elements]);

  useEffect(() => {
    if (!containerRef.current || typeof window === "undefined") return;
    const el = containerRef.current;
    let observer: ResizeObserver | null = null;
    if ("ResizeObserver" in window) {
      observer = new ResizeObserver(() => {
        if (!cyRef.current) return;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        cyRef.current.resize();
        if (!becameVisibleRef.current) {
          becameVisibleRef.current = true;
          try {
            cyRef.current.fit(undefined, 20);
          } catch {}
        }
      });
      observer.observe(el);
    }
    return () => {
      try {
        observer?.disconnect();
      } catch {}
      observer = null;
    };
  }, []);

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
      }}
    />
  );
}

export default MiniGraph;
