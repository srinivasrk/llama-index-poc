"use client";

import { useEffect, useState } from "react";

import { ingest, listKbFiles, uploadKbFiles } from "@/lib/api";

export function IngestPanel() {
  const [docsDir, setDocsDir] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);

  async function onRefreshFiles() {
    setBusy(true);
    setStatus("");
    try {
      const res = await listKbFiles(docsDir.trim() ? docsDir.trim() : undefined);
      setFiles(res.files);
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
      setStatus(
        `Uploaded ${res.uploaded_count} file(s): ${res.uploaded_files.join(", ")}. ` +
        `${modeLabel}: ${parts.join(", ")} — ${ingestRes.documents_indexed} total docs in "${ingestRes.collection_name}".`
      );
      setSelectedFiles([]);
      const kb = await listKbFiles(dir);
      setFiles(kb.files);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void onRefreshFiles()
  }, []);

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
        <div style={styles.filesTitle}>
          INDEXED FILES{files.length > 0 ? ` · ${files.length}` : ""}
        </div>
        {files.length === 0 ? (
          <p style={styles.emptyFiles}>No files indexed yet.</p>
        ) : (
          <div style={styles.chipRow}>
            {files.map((f) => (
              <span key={f} className="chip">{f}</span>
            ))}
          </div>
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
  filesTitle: {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.06em",
    color: "var(--md-on-surface-variant)",
    marginBottom: 10,
  },
  emptyFiles: {
    fontSize: 13,
    color: "var(--md-on-surface-variant)",
  },
};
