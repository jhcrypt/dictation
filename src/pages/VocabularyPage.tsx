import React, { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import Card from "../components/ui/Card";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";

interface Correction {
  wrong: string;
  right: string;
}

interface VocabFile {
  corrections: Record<string, string>;
  manual_vocabulary: string;
}

export default function VocabularyPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();
  const [wrong, setWrong] = useState("");
  const [right, setRight] = useState("");
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [corrStatus, setCorrStatus] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    invoke<VocabFile>("load_vocab")
      .then((v) => {
        const list = Object.entries(v.corrections ?? {}).map(([w, r]) => ({ wrong: w, right: r }));
        setCorrections(list);
      })
      .catch(() => setCorrections([]))
      .finally(() => setLoading(false));
  }, []);

  const flash = (msg: string) => {
    setCorrStatus(msg);
    setTimeout(() => setCorrStatus(""), 2500);
  };

  const persistCorrections = async (list: Correction[]) => {
    const corrMap = Object.fromEntries(list.map((c) => [c.wrong, c.right]));
    await invoke("save_vocab", { vocab: { corrections: corrMap, manual_vocabulary: settings.manual_vocabulary } });
  };

  const addCorrection = async () => {
    if (!wrong.trim() || !right.trim()) return;
    const updated = [...corrections, { wrong: wrong.trim(), right: right.trim() }];
    setCorrections(updated);
    setWrong(""); setRight("");
    await persistCorrections(updated);
    flash("Added.");
  };

  const deleteCorrection = async (i: number) => {
    const updated = corrections.filter((_, idx) => idx !== i);
    setCorrections(updated);
    await persistCorrections(updated);
    flash("Deleted.");
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Vocabulary &amp; Corrections</h2>
        <p className="text-sm text-jarvis-muted mt-1">Teach Quill your preferred words and fix recurring mistakes.</p>
      </div>

      <Card title="Manual Vocabulary">
        <p className="text-xs text-jarvis-muted mb-2">
          One word or phrase per line. Passed to Whisper as hints — improves accuracy for names, brands, and technical terms.
        </p>
        <textarea
          value={settings.manual_vocabulary}
          onChange={(e) => updateSetting("manual_vocabulary", e.target.value)}
          rows={6}
          placeholder={"n8n\nSpotify\nPlaylist\nAPI"}
          className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted resize-none font-mono"
        />
        <div className="flex justify-end mt-2">
          <SaveButton onClick={saveSettings} saved={saved} />
        </div>
      </Card>

      <Card title="Personal Corrections">
        <p className="text-xs text-jarvis-muted mb-3">
          Automatic find-and-replace applied after every transcription. Use for words Whisper consistently mishears.
        </p>

        <div className="flex gap-2 mb-3">
          <input
            placeholder="Whisper hears…"
            value={wrong}
            onChange={(e) => setWrong(e.target.value)}
            className="flex-1 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <span className="self-center text-jarvis-muted">→</span>
          <input
            placeholder="Should be…"
            value={right}
            onChange={(e) => setRight(e.target.value)}
            className="flex-1 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <button
            onClick={addCorrection}
            className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors"
          >
            Add
          </button>
        </div>

        {corrStatus && <p className="text-xs text-jarvis-hint mb-2">{corrStatus}</p>}

        {loading ? (
          <p className="text-sm text-jarvis-muted">Loading…</p>
        ) : corrections.length === 0 ? (
          <p className="text-sm text-jarvis-muted">No corrections yet.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {corrections.map((c, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 bg-jarvis-surface rounded-lg">
                <span className="text-sm text-jarvis-muted">
                  <span className="line-through">{c.wrong}</span>
                  {" → "}
                  <span className="text-jarvis-text">{c.right}</span>
                </span>
                <button
                  onClick={() => deleteCorrection(i)}
                  className="text-xs text-jarvis-muted hover:text-jarvis-danger transition-colors px-2"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
