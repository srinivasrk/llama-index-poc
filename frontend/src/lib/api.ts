export type IngestResponse = {
  status: string;
  mode: "full" | "incremental";
  documents_indexed: number;
  documents_refreshed: number;
  documents_deleted: number;
  collection_name: string;
  source_dir: string;
};

export type ChatResponse = {
  answer: string;
  citations: Array<{ source: string; score: number; node_id: string }>;
  graph_facts?: Array<{
    fact: string;
    uuid?: string | null;
    valid_at?: string | null;
    invalid_at?: string | null;
  }>;
};

export type GraphNode = {
  data: {
    id: string;
    label: string;
    kind: "entity" | "episode";
    summary?: string | null;
    source?: string | null;
  };
};
export type GraphEdge = {
  data: {
    id: string;
    source: string;
    target: string;
    label: string;
    kind: "relates_to" | "mentions";
    fact?: string | null;
    valid_at?: string | null;
    invalid_at?: string | null;
  };
};
export type GraphSnapshot = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  enabled: boolean;
  error?: string;
};

export type UploadResponse = {
  status: string;
  uploaded_count: number;
  uploaded_files: string[];
  source_dir?: string;
};

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function health(): Promise<{ status: string }> {
  return await http("/health");
}

export async function listKbFiles(docsDir?: string): Promise<{ files: string[] }> {
  const qs = docsDir ? `?docs_dir=${encodeURIComponent(docsDir)}` : "";
  return await http(`/kb/files${qs}`);
}

export type KbDebugResponse = {
  status: string;
  docs_dir: string;
  collection_name: string;
  files_on_disk_count: number;
  files_on_disk: string[];
  vector_count?: number;
  indexed_sources_count?: number;
  indexed_sources?: string[];
  vector_store_error?: string;
};

export async function getKbDebug(docsDir?: string): Promise<KbDebugResponse> {
  const qs = docsDir ? `?docs_dir=${encodeURIComponent(docsDir)}` : "";
  return await http(`/kb/debug${qs}`);
}

export async function ingest(docsDir?: string): Promise<IngestResponse> {
  return await http("/ingest", {
    method: "POST",
    body: JSON.stringify({ docs_dir: docsDir ?? null })
  });
}

export async function chat(question: string, history?: string[]): Promise<ChatResponse> {
  return await http("/chat", {
    method: "POST",
    body: JSON.stringify({ question, history: history ?? [] })
  });
}

export async function getGraphSnapshot(): Promise<GraphSnapshot> {
  return await http("/graph/snapshot");
}

/** Server-Sent Events URL for live graph change notifications. */
export const GRAPH_STREAM_URL = `${BACKEND_URL}/graph/stream`;

export async function uploadKbFiles(files: File[], docsDir?: string): Promise<UploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  if (docsDir?.trim()) {
    formData.append("docs_dir", docsDir.trim());
  }

  const res = await fetch(`${BACKEND_URL}/upload`, {
    method: "POST",
    body: formData
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? "";
    } catch {
      detail = await res.text();
    }
    throw new Error(detail || `Upload failed: ${res.status}`);
  }
  return (await res.json()) as UploadResponse;
}
