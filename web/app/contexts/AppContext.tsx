"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

// Types for Graph Q&A state
type QueryResponse = {
  answer: string;
  cypher: string;
  rows: Array<Record<string, unknown>>;
};

type GraphState = {
  question: string;
  result: QueryResponse | null;
  error: string | null;
  isLoading: boolean;
  progress: string | null;
  lastQuery: string | null;
};

// Types for Hypothesis Analyzer state
type EnrichmentResponse = {
  summary: string;
  valid_genes: string[];
  invalid_genes: string[];
  warnings: string[];
  enrichment_results: Array<{
    term: string;
    library: string;
    p_value: number;
    adjusted_p_value: number;
    odds_ratio?: number;
    gene_count: number;
    genes: string[];
    description: string;
  }>;
  plot_data: any;
  followUpQuestions: string[];
};

type PartialEnrichmentResult = {
  valid_genes: string[];
  invalid_genes: string[];
  warnings: string[];
  enrichment_results: Array<{
    term: string;
    library: string;
    p_value: number;
    adjusted_p_value: number;
    odds_ratio?: number;
    gene_count: number;
    genes: string[];
    description: string;
  }>;
  plot_data: any;
};

type SummaryResult = {
  summary: string;
  followUpQuestions: string[];
};

type HypothesisState = {
  genes: string;
  result: EnrichmentResponse | null;
  partialResult: PartialEnrichmentResult | null;
  summaryResult: SummaryResult | null;
  error: string | null;
  isLoading: boolean;
  isLoadingPreset: boolean;
  isSummaryLoading: boolean;
};

type AppState = {
  graphState: GraphState;
  hypothesisState: HypothesisState;
  setGraphState: (state: Partial<GraphState>) => void;
  setHypothesisState: (state: Partial<HypothesisState>) => void;
  clearGraphState: () => void;
  clearHypothesisState: () => void;
  clearAllState: () => void;
};

const initialState: AppState = {
  graphState: {
    question: '',
    result: null,
    error: null,
    isLoading: false,
    progress: null,
    lastQuery: null,
  },
  hypothesisState: {
    genes: '',
    result: null,
    partialResult: null,
    summaryResult: null,
    error: null,
    isLoading: false,
    isLoadingPreset: false,
    isSummaryLoading: false,
  },
  setGraphState: () => {},
  setHypothesisState: () => {},
  clearGraphState: () => {},
  clearHypothesisState: () => {},
  clearAllState: () => {},
};

const AppContext = createContext<AppState>(initialState);

// Storage keys
const GRAPH_STATE_KEY = 'oncograph_graph_state';
const HYPOTHESIS_STATE_KEY = 'oncograph_hypothesis_state';

// Helper functions for localStorage
const saveToStorage = (key: string, data: any) => {
  try {
    localStorage.setItem(key, JSON.stringify(data));
  } catch (error) {
    console.warn('Failed to save to localStorage:', error);
  }
};

const loadFromStorage = (key: string) => {
  try {
    const item = localStorage.getItem(key);
    return item ? JSON.parse(item) : null;
  } catch (error) {
    console.warn('Failed to load from localStorage:', error);
    return null;
  }
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [graphState, setGraphStateInternal] = useState<GraphState>(initialState.graphState);
  const [hypothesisState, setHypothesisStateInternal] = useState<HypothesisState>(initialState.hypothesisState);

  // Load state from localStorage on mount
  useEffect(() => {
    const savedGraphState = loadFromStorage(GRAPH_STATE_KEY);
    const savedHypothesisState = loadFromStorage(HYPOTHESIS_STATE_KEY);

    if (savedGraphState) {
      setGraphStateInternal(savedGraphState);
    }
    if (savedHypothesisState) {
      setHypothesisStateInternal(savedHypothesisState);
    }
  }, []);

  // Save state to localStorage whenever it changes
  useEffect(() => {
    saveToStorage(GRAPH_STATE_KEY, graphState);
  }, [graphState]);

  useEffect(() => {
    saveToStorage(HYPOTHESIS_STATE_KEY, hypothesisState);
  }, [hypothesisState]);

  const setGraphState = (newState: Partial<GraphState>) => {
    setGraphStateInternal(prev => ({ ...prev, ...newState }));
  };

  const setHypothesisState = (newState: Partial<HypothesisState>) => {
    setHypothesisStateInternal(prev => ({ ...prev, ...newState }));
  };

  const clearGraphState = () => {
    setGraphStateInternal(initialState.graphState);
    localStorage.removeItem(GRAPH_STATE_KEY);
  };

  const clearHypothesisState = () => {
    setHypothesisStateInternal(initialState.hypothesisState);
    localStorage.removeItem(HYPOTHESIS_STATE_KEY);
  };

  const clearAllState = () => {
    clearGraphState();
    clearHypothesisState();
  };

  const value: AppState = {
    graphState,
    hypothesisState,
    setGraphState,
    setHypothesisState,
    clearGraphState,
    clearHypothesisState,
    clearAllState,
  };

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
}

// Export types for use in components
export type { QueryResponse, GraphState, EnrichmentResponse, PartialEnrichmentResult, SummaryResult, HypothesisState };
