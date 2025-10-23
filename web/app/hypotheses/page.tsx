"use client";

import { useRouter } from "next/navigation";
import HypothesisAnalyzer from "../components/HypothesisAnalyzer";

export default function HypothesesPage() {
  const router = useRouter();

  const handleNavigateToQuery = (question: string) => {
    // Navigate to Graph Q&A tab with the question as a URL parameter
    // This will populate the text area but not run the query automatically
    router.push(`/?q=${encodeURIComponent(question)}`);
  };

  return (
    <section className="page-section">
      <HypothesisAnalyzer onNavigateToQuery={handleNavigateToQuery} />
    </section>
  );
}
