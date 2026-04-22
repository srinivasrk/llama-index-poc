import { ChatWindow } from "@/components/ChatWindow";
import { IngestPanel } from "@/components/IngestPanel";

export default function Page() {
  return (
    <main className="app-shell">
      <header className="hero">
        <h1 className="hero-title">LlamaIndex + LangGraph RAG PoC</h1>
        <p className="hero-subtitle">
          Gemini-backed chatbot constrained to your local knowledge base (Chroma).
        </p>
      </header>

      <div className="panel-grid">
        <IngestPanel />
        <ChatWindow />
      </div>

      <footer className="footer-note">Tip: ingest first, then ask an in-KB and out-of-KB question to test refusal.</footer>
    </main>
  );
}

