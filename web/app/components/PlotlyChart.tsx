"use client";

import dynamic from "next/dynamic";
import { useState, useEffect } from "react";

// Dynamic import with better error handling
const Plot = dynamic(() => import("react-plotly.js"), { 
  ssr: false,
  loading: () => (
    <div style={{ 
      height: "600px", 
      display: "flex", 
      alignItems: "center", 
      justifyContent: "center",
      backgroundColor: "#f8f9fa",
      border: "1px solid #e9ecef",
      borderRadius: "4px"
    }}>
      <div style={{ textAlign: "center", color: "#6c757d" }}>
        <div style={{ 
          width: "40px", 
          height: "40px", 
          border: "4px solid #f3f3f3",
          borderTop: "4px solid #007bff",
          borderRadius: "50%",
          animation: "spin 1s linear infinite",
          margin: "0 auto 16px"
        }}></div>
        <p>Loading visualization...</p>
      </div>
    </div>
  )
});

// Add CSS for spinner animation
const spinnerStyle = `
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
`;

type PlotlyChartProps = {
  data: any[];
  layout: any;
  onClick?: (event: any) => void;
};

export default function PlotlyChart({ data, layout, onClick }: PlotlyChartProps) {
  const [isClient, setIsClient] = useState(false);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    setIsClient(true);
  }, []);

  // Add spinner styles to head
  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = spinnerStyle;
    document.head.appendChild(style);
    return () => document.head.removeChild(style);
  }, []);

  if (!isClient) {
    return (
      <div style={{ 
        height: "600px", 
        display: "flex", 
        alignItems: "center", 
        justifyContent: "center",
        backgroundColor: "#f8f9fa",
        border: "1px solid #e9ecef",
        borderRadius: "4px"
      }}>
        <div style={{ textAlign: "center", color: "#6c757d" }}>
          <div style={{ 
            width: "40px", 
            height: "40px", 
            border: "4px solid #f3f3f3",
            borderTop: "4px solid #007bff",
            borderRadius: "50%",
            animation: "spin 1s linear infinite",
            margin: "0 auto 16px"
          }}></div>
          <p>Loading visualization...</p>
        </div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div style={{ 
        height: "600px", 
        display: "flex", 
        alignItems: "center", 
        justifyContent: "center",
        backgroundColor: "#f8f9fa",
        border: "1px solid #e9ecef",
        borderRadius: "4px"
      }}>
        <div style={{ textAlign: "center", color: "#6c757d" }}>
          <p>Unable to load visualization</p>
          <p style={{ fontSize: "14px", marginTop: "8px" }}>
            Please refresh the page to try again
          </p>
          <button 
            onClick={() => window.location.reload()}
            style={{
              marginTop: "16px",
              padding: "8px 16px",
              backgroundColor: "#007bff",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer"
            }}
          >
            Refresh Page
          </button>
        </div>
      </div>
    );
  }

  try {
    return (
      <Plot
        data={data || []}
        layout={layout || {}}
        style={{ width: "100%", height: "600px" }}
        config={{
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToRemove: ["pan2d", "lasso2d", "select2d"],
        }}
        onClick={onClick}
        onError={(error) => {
          console.error("Plotly error:", error);
          setHasError(true);
        }}
      />
    );
  } catch (error) {
    console.error("Error rendering Plotly chart:", error);
    setHasError(true);
    return null;
  }
}
