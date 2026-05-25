import React, { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";
import type { CleanupProvider } from "../types/settings";

// ── Sub-components ────────────────────────────────────────────────────────────

function RadioGroup<T extends string>({
  value,
  options,
  onChange,
  disabled,
}: {
  value: T;
  options: { value: T; label: string; description?: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {options.map((opt) => (
        <label
          key={opt.value}
          className={`flex items-start gap-3 cursor-pointer group ${disabled ? "opacity-40 pointer-events-none" : ""}`}
        >
          <input
            type="radio"
            name={`radio-${opt.value}`}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            className="mt-0.5 accent-jarvis-accent"
          />
          <div>
            <div className="text-sm text-jarvis-text">{opt.label}</div>
            {opt.description && (
              <div className="text-xs text-jarvis-muted mt-0.5">{opt.description}</div>
            )}
          </div>
        </label>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CloudPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  // Key field state — we never load the key back from Keychain for display.
  // The field starts blank; a saved-indicator shows if a key exists in Keychain.
  const [keyInput,    setKeyInput]    = useState("");
  const [showKey,     setShowKey]     = useState(false);
  const [keyExists,   setKeyExists]   = useState(false);
  const [keySaving,   setKeySaving]   = useState(false);
  const [keyError,    setKeyError]    = useState<string | null>(null);
  const [keySuccess,  setKeySuccess]  = useState(false);

  // Check Keychain on mount (and whenever saved fires) to show the ✓ indicator.
  useEffect(() => {
    invoke<boolean>("keychain_has_api_key", { provider: "openai" })
      .then(setKeyExists)
      .catch(() => setKeyExists(false));
  }, [saved]);

  const isCloud    = settings.transcription_engine === "cloud";
  const isSafeModeOn = settings.safe_mode;
  // Safe Mode locks engine to local.
  const effectiveEngine = isSafeModeOn ? "local" : settings.transcription_engine;

  // ── Save API key to Keychain ──────────────────────────────────────────────
  async function handleSaveKey() {
    if (!keyInput.trim()) {
      // Empty field + existing key = delete
      if (keyExists) {
        setKeySaving(true);
        try {
          await invoke("keychain_delete_api_key", { provider: "openai" });
          setKeyExists(false);
          setKeySuccess(true);
          setTimeout(() => setKeySuccess(false), 2000);
        } catch (e: unknown) {
          setKeyError(String(e));
        } finally {
          setKeySaving(false);
        }
      }
      return;
    }
    setKeySaving(true);
    setKeyError(null);
    try {
      await invoke("keychain_save_api_key", { provider: "openai", key: keyInput.trim() });
      setKeyExists(true);
      setKeyInput("");          // clear field — key is now in Keychain only
      setKeySuccess(true);
      setTimeout(() => setKeySuccess(false), 2000);
    } catch (e: unknown) {
      setKeyError(String(e));
    } finally {
      setKeySaving(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Cloud</h2>
        <p className="text-sm text-jarvis-hint mt-1 leading-relaxed">
          Choose where audio is transcribed. Local Whisper runs on your Mac. Cloud sends
          audio to OpenAI for transcription — faster on older hardware, requires an API key.
        </p>
      </div>

      {/* ── Transcription Engine ────────────────────────────────────────── */}
      <Card title="Transcription Engine">
        {isSafeModeOn && (
          <div className="text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-lg px-3 py-2 mb-3">
            Safe Mode is on — transcription is forced to Local Whisper.
          </div>
        )}
        <RadioGroup<"local" | "cloud">
          value={effectiveEngine as "local" | "cloud"}
          disabled={isSafeModeOn}
          onChange={(v) => updateSetting("transcription_engine", v)}
          options={[
            {
              value: "local",
              label: "Local Whisper",
              description: "All audio processed on this Mac. No data leaves the device.",
            },
            {
              value: "cloud",
              label: "Cloud — OpenAI Whisper API",
              description: "Audio sent to OpenAI for transcription. Requires an API key.",
            },
          ]}
        />
      </Card>

      {/* ── Local Model (read-only hint) ────────────────────────────────── */}
      {!isCloud && (
        <div className="px-3 py-2.5 rounded-lg border border-jarvis-border bg-jarvis-surface text-xs text-jarvis-muted">
          Local model: <span className="text-jarvis-text font-medium">
            {settings.model || `${settings.dictation_quality === "Fast" ? "tiny" : settings.dictation_quality === "Accurate" ? "medium" : "small"}.en`}
          </span>
          {" — "}
          <span className="text-jarvis-hint">change in Audio &amp; Language</span>
        </div>
      )}

      {/* ── Cloud Provider / API Key ─────────────────────────────────────── */}
      {isCloud && (
        <Card title="OpenAI API Key">
          <p className="text-xs text-jarvis-muted mb-3">
            Required for cloud transcription. Get your key at{" "}
            <span className="text-jarvis-accent">platform.openai.com</span>.
            Your key is stored in macOS Keychain — never written to disk in plaintext.
          </p>

          {keyExists && (
            <div className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded-lg px-3 py-2 mb-3">
              ✓ API key saved in macOS Keychain. Enter a new key below to replace it,
              or clear the field and click Save Key to remove it.
            </div>
          )}

          {keyError && (
            <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2 mb-3">
              {keyError}
            </div>
          )}

          <div className="flex gap-2 mb-2">
            <input
              type={showKey ? "text" : "password"}
              placeholder={keyExists ? "Enter new key to replace…" : "sk-…"}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              className="flex-1 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted font-mono"
            />
            <button
              onClick={() => setShowKey((v) => !v)}
              className="px-3 py-2 border border-jarvis-border rounded-lg text-xs text-jarvis-muted hover:text-jarvis-text transition-colors"
            >
              {showKey ? "Hide" : "Show"}
            </button>
          </div>

          <button
            onClick={handleSaveKey}
            disabled={keySaving}
            className="px-4 py-2 bg-jarvis-accent text-white text-sm rounded-lg hover:bg-jarvis-accent/80 disabled:opacity-50 transition-colors"
          >
            {keySaving ? "Saving…" : keySuccess ? "✓ Saved" : "Save Key"}
          </button>
          <p className="text-xs text-jarvis-muted mt-2">
            If Cloud transcription fails, Jarvis will fall back to Local Whisper automatically
            and show a warning in the HUD.
          </p>
        </Card>
      )}

      {/* ── Cleanup Provider ─────────────────────────────────────────────── */}
      <Card title="AI Cleanup">
        <RadioGroup<CleanupProvider>
          value={settings.cleanup_provider}
          onChange={(v) => updateSetting("cleanup_provider", v)}
          options={[
            {
              value: "ollama",
              label: "Ollama Local",
              description: "Run AI cleanup on-device using your local Ollama model.",
            },
            {
              value: "off",
              label: "Off",
              description: "Skip AI cleanup. Raw Whisper output only.",
            },
          ]}
        />
      </Card>

      {/* ── Privacy Note ─────────────────────────────────────────────────── */}
      <Card title="Privacy">
        <div
          className="rounded-lg px-4 py-3 text-xs text-jarvis-muted leading-relaxed"
          style={{ background: "#1a3a5c" }}
        >
          <div className="text-jarvis-hint font-medium mb-1">
            {effectiveEngine === "local" ? "On-device — no data leaves this Mac" : "Cloud mode — audio sent to OpenAI"}
          </div>
          {effectiveEngine === "local" ? (
            "All audio is transcribed locally by Whisper running on your Mac. Nothing is sent to any server."
          ) : (
            "Audio is sent to OpenAI servers for transcription. Your API key is stored in macOS Keychain and is never written to ~/.dictation_settings.json or shared with Quill."
          )}
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
