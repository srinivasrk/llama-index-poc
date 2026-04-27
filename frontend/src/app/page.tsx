import { ChatWindow } from "@/components/ChatWindow";
import { GraphPanel } from "@/components/GraphPanel";
import { IngestPanel } from "@/components/IngestPanel";

export default function Page() {
  return (
    <main className="app-shell">
      <header className="hero">
        <h1 className="hero-title">LlamaIndex + LangGraph + Graphiti RAG PoC</h1>
        <p className="hero-subtitle">
          Gemini-backed chatbot grounded in Chroma vectors and a live Graphiti knowledge graph.
        </p>
      </header>

      <div className="panel-grid">
        <IngestPanel />
        <ChatWindow />
        <GraphPanel />
      </div>

      <footer className="footer-note">
        Tip: ingest first, then chat — watch the graph below grow as Graphiti extracts entities and edges.
      </footer>
    </main>
  );
}
