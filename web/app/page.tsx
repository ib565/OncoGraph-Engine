import GraphPanel from "./components/GraphPanel";

type PageProps = {
  searchParams?: {
    q?: string;
  };
};

export default function GraphPage({ searchParams }: PageProps) {
  const initialQuestion = searchParams?.q ?? null;

  return (
    <section className="page-section">
      <GraphPanel rows={[]} initialQuestion={initialQuestion} />
    </section>
  );
}

