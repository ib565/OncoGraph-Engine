"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAppContext } from "../contexts/AppContext";

const tabs = [
  { href: "/", label: "Graph Q&A" },
  { href: "/hypotheses", label: "Hypothesis Analyzer" },
];

export default function TopBar() {
  const pathname = usePathname();
  const { clearAllState } = useAppContext();

  return (
    <div className="top-bar">
      <h1 className="top-bar-title">OncoGraph</h1>

      <nav className="top-bar-nav" aria-label="Primary">
        {tabs.map((tab) => {
          const isActive = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={isActive ? "top-bar-tab active" : "top-bar-tab"}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div className="top-bar-actions">
        <button
          onClick={clearAllState}
          className="clear-button"
          title="Clear all data and start fresh"
        >
          Clear All
        </button>
        <div className="top-bar-status" aria-live="polite">
          Ready
        </div>
      </div>
    </div>
  );
}
