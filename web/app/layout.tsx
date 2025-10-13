import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OncoGraph Demo",
  description: "Ask oncology biomarker questions backed by Neo4j",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

