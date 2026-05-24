import React, { useState, useEffect } from "react";
import Card from "../components/ui/Card";

interface HistoryEntry {
  timestamp: string;
  app: string;
  final_text: string;
  status: string;
  profile: string;
  whisper_text?: string | null;
  ollama_text?: string | null;
}


function fmtTime(iso: string): string {
  if (!iso) return "No date";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "No date";
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60000)    return "just now";
  if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString();
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = !!(entry.whisper_text || entry.ollama_text);

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-3">
      <p className="text-sm text-jarvis-text leading-relaxed mb-2">{entry.final_text}</p>
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs text-jarvis-muted">{fmtTime(entry.timestamp)}</span>
        {entry.app && <span className="text-xs text-jarvis-muted">{entry.app}</span>}
        {entry.profile && <span className="text-xs text-jarvis-muted">{entry.profile}</span>}
        <span className={`text-xs ${entry.status === "pasted" ? "text-jarvis-success" : "text-jarvis-muted"}`}>
          {entry.status}
        </span>
        {hasDetail && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="ml-auto text-xs text-jarvis-accent hover:text-jarvis-text transition-colors"
          >
            {expanded ? "Hide detail ▲" : "Show detail ▼"}
          </button>
        )}
      </div>

      {expanded && hasDetail && (
        <div className="mt-3 space-y-2 border-t border-jarvis-border pt-2">
          {entry.whisper_text && entry.whisper_text !== entry.final_text && (
            <div>
              <p className="text-[11px] text-jarvis-muted mb-1 font-medium uppercase tracking-wide">Whisper raw</p>
              <p className="text-xs text-jarvis-hint leading-relaxed font-mono bg-jarvis-sidebar px-2 py-1.5 rounded-lg">
                {entry.whisper_text}
              </p>
            </div>
          )}
          {entry.ollama_text && (
            <div>
              <p className="text-[11px] text-jarvis-muted mb-1 font-medium uppercase tracking-wide">Ollama suggestion</p>
              <p className="text-xs text-jarvis-hint leading-relaxed font-mono bg-jarvis-sidebar px-2 py-1.5 rounded-lg">
                {entry.ollama_text}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    loadHistory();
  }, []);

  async function loadHistory() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const loaded = await invoke<HistoryEntry[]>("load_history");
      if (loaded.length > 0) setHistory(loaded);
    } catch { /* preview */ }
  }

  async function clearHistory() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("clear_history");
    } catch { /* preview */ }
    setHistory([]);
  }

  const filtered = search
    ? history.filter((h) => h.final_text.toLowerCase().includes(search.toLowerCase()))
    : history;

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-jarvis-text">History</h2>
          <p className="text-sm text-jarvis-hint mt-1">Recent dictations. {history.length} entries.</p>
        </div>
        <button
          onClick={clearHistory}
          className="px-4 py-2 text-sm font-medium text-jarvis-muted hover:text-jarvis-recording bg-jarvis-sidebar border border-jarvis-border rounded-lg hover:border-jarvis-muted transition-colors"
        >
          Clear All
        </button>
      </div>

      <div>
        <input
          placeholder="Search history…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
        />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <p className="text-sm text-jarvis-muted">{search ? "No results." : "No dictation history yet."}</p>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((entry, i) => (
            <HistoryRow key={i} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
