import type { QueryResponse } from "../contexts/AppContext";

export type ExampleQueryTab = "therapy_targets" | "biomarkers_resistance" | "evidence_precision";

export interface ExampleQueryCachedResponse {
  answer: string;
  cypher: string;
  rows: Array<Record<string, unknown>>;
  updatedAt: string;
}

export interface ExampleQuery {
  id: string;
  tab: ExampleQueryTab;
  question: string;
  cachedResponse: ExampleQueryCachedResponse | null;
}

export interface ExampleQueriesByTab {
  therapy_targets: ExampleQuery[];
  biomarkers_resistance: ExampleQuery[];
  evidence_precision: ExampleQuery[];
}

export function groupByTab(queries: ExampleQuery[]): ExampleQueriesByTab {
  const grouped: ExampleQueriesByTab = {
    therapy_targets: [],
    biomarkers_resistance: [],
    evidence_precision: [],
  };

  queries.forEach((query) => {
    grouped[query.tab].push(query);
  });

  return grouped;
}

export function findExampleById(queries: ExampleQuery[], id: string): ExampleQuery | undefined {
  return queries.find((q) => q.id === id);
}

export function findExampleByQuestion(queries: ExampleQuery[], question: string): ExampleQuery | undefined {
  return queries.find((q) => q.question.trim() === question.trim());
}

