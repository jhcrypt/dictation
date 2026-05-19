import React, { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import Card from "../components/ui/Card";

interface Snippet {
  trigger: string;
  expansion: string;
}

export default function SnippetsPage() {
  const [snippets, setSnippets] = useState<Snippet[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [trigger, setTrigger] = useState("");
  const [expansion, setExpansion] = useState("");
  const [newTrigger, setNewTrigger] = useState("");
  const [newExpansion, setNewExpansion] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSnippets();
  }, []);

  const loadSnippets = async () => {
    try {
      const raw = await invoke<Record<string, string>>("load_snippets");
      const list: Snippet[] = Object.entries(raw).map(([t, e]) => ({ trigger: t, expansion: e }));
      setSnippets(list);
    } catch {
      setSnippets([]);
    } finally {
      setLoading(false);
    }
  };

  const toDict = (list: Snippet[]): Record<string, string> =>
    Object.fromEntries(list.map((s) => [s.trigger, s.expansion]));

  const flash = (msg: string) => {
    setStatus(msg);
    setTimeout(() => setStatus(""), 2500);
  };

  const selectSnippet = (s: Snippet) => {
    setSelected(s.trigger);
    setTrigger(s.trigger);
    setExpansion(s.expansion);
  };

  const saveEdit = async () => {
    if (!trigger.trim() || !expansion.trim()) return;
    const updated = snippets
      .filter((s) => s.trigger !== selected)
      .concat({ trigger: trigger.trim(), expansion: expansion.trim() });
    await invoke("save_snippets", { snippets: toDict(updated) });
    setSnippets(updated);
    setSelected(null); setTrigger(""); setExpansion("");
    flash("Saved.");
  };

  const deleteSelected = async () => {
    if (!selected) return;
    const updated = snippets.filter((s) => s.trigger !== selected);
    await invoke("save_snippets", { snippets: toDict(updated) });
    setSnippets(updated);
    setSelected(null); setTrigger(""); setExpansion("");
    flash("Deleted.");
  };

  const addNew = async () => {
    if (!newTrigger.trim() || !newExpansion.trim()) return;
    const updated = [...snippets.filter((s) => s.trigger !== newTrigger.trim()), { trigger: newTrigger.trim(), expansion: newExpansion.trim() }];
    await invoke("save_snippets", { snippets: toDict(updated) });
    setSnippets(updated);
    setNewTrigger(""); setNewExpansion("");
    flash("Snippet added.");
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Snippets</h2>
        <p className="text-sm text-jarvis-muted mt-1">Say the trigger phrase and it expands to the full text.</p>
      </div>

      <Card title="New Snippet">
        <div className="flex flex-col gap-3">
          <input
            type="text"
            placeholder="Trigger phrase"
            value={newTrigger}
            onChange={(e) => setNewTrigger(e.target.value)}
            className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <textarea
            placeholder="Expansion text…"
            value={newExpansion}
            onChange={(e) => setNewExpansion(e.target.value)}
            rows={3}
            className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted resize-none"
          />
          {status && <p className="text-xs text-jarvis-hint">{status}</p>}
          <div className="flex justify-end">
            <button
              onClick={addNew}
              className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors"
            >
              New Snippet
            </button>
          </div>
        </div>
      </Card>

      {selected && (
        <Card title="Edit Snippet">
          <div className="flex flex-col gap-3">
            <input
              type="text"
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent"
            />
            <textarea
              value={expansion}
              onChange={(e) => setExpansion(e.target.value)}
              rows={4}
              className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent resize-none"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={deleteSelected}
                className="px-4 py-2 border border-jarvis-danger text-jarvis-danger rounded-lg text-sm font-medium hover:bg-jarvis-danger/10 transition-colors"
              >
                Delete
              </button>
              <button
                onClick={() => { setSelected(null); setTrigger(""); setExpansion(""); }}
                className="px-4 py-2 border border-jarvis-border text-jarvis-muted rounded-lg text-sm font-medium hover:text-jarvis-text transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors"
              >
                Save changes
              </button>
            </div>
          </div>
        </Card>
      )}

      <Card title={`Snippets (${snippets.length})`}>
        {loading ? (
          <p className="text-sm text-jarvis-muted">Loading…</p>
        ) : snippets.length === 0 ? (
          <p className="text-sm text-jarvis-muted">No snippets yet.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {snippets.map((s) => (
              <button
                key={s.trigger}
                onClick={() => selectSnippet(s)}
                className={`flex items-start justify-between px-3 py-2.5 rounded-lg border text-left transition-colors ${
                  selected === s.trigger
                    ? "bg-jarvis-accent/10 border-jarvis-accent"
                    : "bg-jarvis-surface border-jarvis-border hover:border-jarvis-muted"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-jarvis-text truncate">"{s.trigger}"</div>
                  <div className="text-xs text-jarvis-muted mt-0.5 truncate">{s.expansion}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
