import type { Metadata } from "next";
import "./globals.css";
import TopBar from "./components/TopBar";

export const metadata: Metadata = {
  title: "OncoGraph",
  description: "Answers oncology questions using knowledge graph backed citations.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" style={{ colorScheme: 'dark' }}>
      <body
        style={{
          height: "100%",
          background: "var(--bg-app)",
          color: "var(--text-1)",
          margin: 0,
          fontSmooth: "antialiased",
          WebkitFontSmoothing: "antialiased",
          MozOsxFontSmoothing: "grayscale",
        }}
      >
        <div className="app-shell">
          <TopBar />
          <main className="workspace">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

