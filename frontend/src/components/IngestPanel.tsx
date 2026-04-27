"use client";

import { useEffect, useMemo, useState } from "react";

import { getKbDebug, ingest, listKbFiles, uploadKbFiles } from "@/lib/api";

type FileRow = {
  /** Filename on disk (relative to docs_dir). */
  name: string;
  /** True if this file's basename is in Chroma's indexed_sources set. */
  indexed: boolean;
};

export function IngestPanel() {
  const [docsDir, setDocsDir] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [filesOnDisk, setFilesOnDisk] = useState<string[]>([]);
  const [indexedSources, setIndexedSources] = useState<string[]>([]);
  const [vectorCount, setVectorCount] = useState<number | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);

  async function onRefreshFiles() {
    setBusy(true);
    setStatus("");
    try {
      const dir = docsDir.trim() ? docsDir.trim() : undefined;
      // Both calls in parallel: on-disk listing AND Chroma's actual indexed sources.
      const [filesRes, debugRes] = await Promise.all([
        listKbFiles(dir),
        getKbDebug(dir).catch(() => null),
      ]);
      setFilesOnDisk(filesRes.files);
      setIndexedSources(debugRes?.indexed_sources ?? []);
      setVectorCount(debugRes?.vector_count ?? null);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUpload() {
    if (selectedFiles.length === 0) {
      setStatus("Select at least one .md, .txt, or .pdf file to upload.");
      return;
    }
    setBusy(true);
    setStatus("Uploading files…");
    try {
      const dir = docsDir.trim() ? docsDir.trim() : undefined;
      const res = await uploadKbFiles(selectedFiles, dir);
      setStatus("Indexing documents…");
      const ingestRes = await ingest(dir);
      const modeLabel = ingestRes.mode === "full" ? "Full index built" : "Incremental update";
      const parts = [`${ingestRes.documents_refreshed} refreshed`];
      if (ingestRes.documents_deleted > 0) parts.push(`${ingestRes.documents_deleted} removed`);
      const graphitiTail =
        (ingestRes as { graphiti_status?: string }).graphiti_status === "queued"
          ? " Graphiti is extracting entities in the background — watch the graph panel below."
          : "";
      setStatus(
        `Uploaded ${res.uploaded_count} file(s): ${res.uploaded_files.join(", ")}. ` +
          `${modeLabel}: ${parts.join(", ")} — ${ingestRes.documents_indexed} total docs in "${ingestRes.collection_name}".` +
          graphitiTail
      );
      setSelectedFiles([]);
      await onRefreshFiles();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onIngestExisting() {
    setBusy(true);
    setStatus("Indexing existing files into Chroma…");
    try {
      const dir = docsDir.trim() ? docsDir.trim() : undefined;
      const ingestRes = await ingest(dir);
      const modeLabel = ingestRes.mode === "full" ? "Full index built" : "Incremental update";
      const parts = [`${ingestRes.documents_refreshed} refreshed`];
      if (ingestRes.documents_deleted > 0) parts.push(`${ingestRes.documents_deleted} removed`);
      const graphitiTail =
        (ingestRes as { graphiti_status?: string }).graphiti_status === "queued"
          ? " Graphiti is extracting entities in the background — watch the graph panel below."
          : "";
      setStatus(
        `${modeLabel}: ${parts.join(", ")} — ${ingestRes.documents_indexed} total docs in "${ingestRes.collection_name}".` +
          graphitiTail
      );
      await onRefreshFiles();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void onRefreshFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Match on-disk basenames against the indexed_sources set returned by /kb/debug. */
  const rows: FileRow[] = useMemo(() => {
    const indexedSet = new Set(indexedSources);
    return filesOnDisk.map((path) => {
      const base = path.split(/[\\/]/).pop() ?? path;
      return { name: path, indexed: indexedSet.has(base) || indexedSet.has(path) };
    });
  }, [filesOnDisk, indexedSources]);

  const pendingCount = rows.filter((r) => !r.indexed).length;

  return (
    <section className="card">
      <h2 className="card-title">Knowledge Base</h2>
      <p className="card-subtitle">
        Upload files to index into Chroma. Backend reads from <code>DOCS_DIR</code>{" "}
        (default <code>backend/data</code>).
      </p>

      {/* Dir override row */}
      <div style={styles.row}>
        <input
          className="input"
          placeholder="Optional docs_dir override"
          value={docsDir}
          onChange={(e) => setDocsDir(e.target.value)}
        />
        <button className="button" onClick={onRefreshFiles} disabled={busy}>
          Refresh
        </button>
      </div>

      {/* File picker row */}
      <div style={styles.row}>
        <label className="button" style={styles.filePickerButton}>
          Choose files
          <input
            type="file"
            style={styles.hiddenFileInput}
            multiple
            accept=".md,.txt,.pdf"
            onChange={(e) => setSelectedFiles(Array.from(e.target.files ?? []))}
          />
        </label>
        <span style={styles.selectedCount}>
          {selectedFiles.length > 0
            ? `${selectedFiles.length} file(s) selected`
            : "No files selected"}
        </span>
        <button className="button button-primary" onClick={onUpload} disabled={busy}>
          {busy ? "Working…" : "Upload + Index"}
        </button>
      </div>

      {/* Selected file chips */}
      {selectedFiles.length > 0 && (
        <div style={styles.chipRow}>
          {selectedFiles.map((f) => (
            <span key={f.name} className="chip">{f.name}</span>
          ))}
        </div>
      )}

      {/* Status */}
      {status && (
        <div style={styles.status} className="mono">{status}</div>
      )}

      {/* File list */}
      <div className="soft-box" style={styles.filesBox}>
        <div style={styles.filesHeader}>
          <span style={styles.filesTitle}>
            FILES IN FOLDER{rows.length > 0 ? ` · ${rows.length}` : ""}
          </span>
          {vectorCount !== null && (
            <span style={styles.metaInline}>
              Chroma vectors: {vectorCount} · indexed: {indexedSources.length}
              {pendingCount > 0 && ` · pending: ${pendingCount}`}
            </span>
          )}
        </div>

        {rows.length === 0 ? (
          <p style={styles.emptyFiles}>No files in folder yet.</p>
        ) : (
          <>
            <div style={styles.chipRow}>
              {rows.map((r) => (
                <span
                  key={r.name}
                  className={`chip ${r.indexed ? "chip-primary" : ""}`}
                  title={r.indexed ? "Indexed in Chroma" : "On disk but not yet ingested — click 'Index folder' to ingest"}
                  style={r.indexed ? undefined : styles.pendingChip}
                >
                  {r.indexed ? "● " : "○ "}{r.name}
                </span>
              ))}
            </div>
            {pendingCount > 0 && (
              <div style={styles.pendingRow}>
                <span style={styles.pendingNote}>
                  {pendingCount} file(s) on disk are not in the Chroma index yet.
                </span>
                <button className="button" onClick={onIngestExisting} disabled={busy}>
                  Index folder
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

const styles: Record<string, React.CSSProperties> = {
  row: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    marginBottom: 10,
  },
  filePickerButton: {
    position: "relative",
    overflow: "hidden",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minWidth: 130,
    flexShrink: 0,
  },
  hiddenFileInput: {
    position: "absolute",
    inset: 0,
    opacity: 0,
    width: "100%",
    height: "100%",
    cursor: "pointer",
  },
  selectedCount: {
    flex: 1,
    fontSize: 13,
    color: "var(--md-on-surface-variant)",
  },
  chipRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
    marginBottom: 10,
  },
  status: {
    marginTop: 2,
    marginBottom: 10,
    padding: "10px 14px",
    borderRadius: 12,
    background: "var(--md-surface-container)",
    border: "1px solid var(--md-outline-variant)",
    color: "var(--md-on-surface)",
    lineHeight: 1.55,
  },
  filesBox: {
    marginTop: 4,
    padding: 14,
  },
  filesHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
    flexWrap: "wrap",
    gap: 8,
  },
  filesTitle: {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.06em",
    color: "var(--md-on-surface-variant)",
  },
  metaInline: {
    fontSize: 11,
    color: "var(--md-on-surface-variant)",
  },
  emptyFiles: {
    fontSize: 13,
    color: "var(--md-on-surface-variant)",
  },
  pendingChip: {
    background: "var(--md-surface-container-high)",
    color: "var(--md-on-surface-variant)",
    border: "1px dashed var(--md-outline)",
  },
  pendingRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    marginTop: 4,
    flexWrap: "wrap",
  },
  pendingNote: {
    flex: 1,
    fontSize: 12,
    color: "var(--md-on-surface-variant)",
  },
};
