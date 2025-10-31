"use client";

import { useEffect } from "react";
import TopBar from "./components/TopBar";
import { AppProvider } from "./contexts/AppContext";

// Wake-up ping on page load to start backend wake-up process early
function WakeUpPing() {
  useEffect(() => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (API_URL) {
      // Fire and forget - just start the wake-up process
      fetch(`${API_URL}/healthz`).catch(() => {
        // Ignore errors - this is just a wake-up ping
      });
    }
  }, []);

  return null;
}

export default function ClientWrapper({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <WakeUpPing />
      <div className="app-shell">
        <TopBar />
        <div
          style={{
            background: "#3a2f09",
            color: "#ffd666",
            padding: "6px 12px",
            textAlign: "center",
            fontSize: "12px",
            borderBottom: "1px solid rgba(255, 214, 102, 0.25)",
          }}
        >
          Backend is temporarily down due to running out of free Render credits 😅. Will be back up shortly!
        </div>
        <main className="workspace">
          {children}
        </main>
      </div>
    </AppProvider>
  );
}

