import React, { useState, useEffect } from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";
import type { AiCleanupMode, CorrectionStrength } from "../types/settings";

const STRENGTHS: CorrectionStrength[] = ["Light", "Standard", "Strong", "Off"];
const STRENGTH_DESC: Record<CorrectionStrength, string> = {
  Light:    "Light touch — fix only obvious errors",
  Standard: "Balanced cleanup — recommended",
  Strong:   "Thorough rewrite — may change phrasing",
  Off:      "No corrections applied to output",
};

const RECOMMENDED_MODEL = "qwen2.5:3b";

// ── Ollama status types ────────────────────────────────────────────────────────
type OllamaStatus =
  | "checking"
  | "ready"
  | "not_installed"
  | "not_running"
  | "model_missing"
  | "installing"
  | "install_error";

const STATUS_LABEL: Record<OllamaStatus, string> = {
  checking:      "Checking…",
  ready:         "✓  Local AI Cleanup ready",
  not_installed: "⚠  Ollama not installed",
  not_running:   "⚠  Ollama installed but not running",
  model_missing: "⚠  Recommended model not installed",
  installing:    `⏳  Downloading ${RECOMMENDED_MODEL}…`,
  install_error: "✗  Download failed",
};

const STATUS_COLOR: Record<OllamaStatus, string> = {
  checking:      "#6a6a6a",
  ready:         "#30d158",
  not_installed: "#ff9f0a",
  not_running:   "#ff9f0a",
  model_missing: "#ff9f0a",
  installing:    "#0a84ff",
  install_error: "#ff3b30",
};

const STATUS_DETAIL: Record<OllamaStatus, string> = {
  checking:
    "Checking Ollama availability…",
  ready:
    `Ollama is installed, running, and ${RECOMMENDED_MODEL} is available. Dictated text will be polished automatically.`,
  not_installed:
    "Ollama is not installed on this Mac. Dictation still works normally without it — you just won't get AI cleanup.",
  not_running:
    "Ollama is installed but the server is not running. Start Ollama from your Applications folder, then click Check Again.",
  model_missing:
    `Ollama is running but ${RECOMMENDED_MODEL} is not downloaded yet. Click Install Recommended Model below.`,
  installing:
    "Do not close the app. The download runs in the background and may take a minute.",
  install_error:
    "Make sure Ollama is running and you have a network connection, then try again.",
};

// ── Ollama readiness card component ───────────────────────────────────────────
function OllamaReadinessCard() {
  const [status,       setStatus]       = useState<OllamaStatus>("checking");
  const [installError, setInstallError] = useState("");

  useEffect(() => { runCheck(); }, []);

  async function runCheck() {
    setStatus("checking");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const s = await invoke<string>("check_ollama_status");
      setStatus(s as OllamaStatus);
    } catch {
      setStatus("not_installed");
    }
  }

  async function openDownload() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_url", { url: "https://ollama.com/download" });
    } catch {
      window.open("https://ollama.com/download", "_blank");
    }
  }

  async function installModel() {
    setStatus("installing");
    setInstallError("");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("install_ollama_model");
      // Re-probe after pull completes
      await runCheck();
    } catch (e) {
      setInstallError(String(e));
      setStatus("install_error");
    }
  }

  const isBusy = status === "checking" || status === "installing";

  return (
    <Card title="Local AI Cleanup (Ollama)">
      {/* Status row */}
      <div className="mb-3">
        <div
          className="text-sm font-semibold mb-1"
          style={{ color: STATUS_COLOR[status] }}
        >
          {STATUS_LABEL[status]}
        </div>
        <div className="text-xs text-jarvis-muted leading-relaxed">
          {STATUS_DETAIL[status]}
        </div>
        {status === "install_error" && installError && (
          <div className="mt-1 text-xs font-mono text-red-400 break-all leading-relaxed">
            {installError}
          </div>
        )}
      </div>

      {/* Fallback note */}
      {(status === "not_installed" || status === "not_running") && (
        <p className="text-xs text-jarvis-muted italic mb-3">
          Dictation still works without Local AI Cleanup.
        </p>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        {/* Always available: Check Again */}
        <button
          onClick={runCheck}
          disabled={isBusy}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border border-jarvis-border bg-jarvis-surface text-jarvis-muted hover:text-jarvis-text transition-colors disabled:opacity-40"
        >
          Check Again
        </button>

        {/* Not installed: offer download link */}
        {status === "not_installed" && (
          <button
            onClick={openDownload}
            className="px-3 py-1.5 rounded-lg text-xs font-medium border border-jarvis-border bg-jarvis-surface text-jarvis-muted hover:text-jarvis-text transition-colors"
          >
            Download Ollama
          </button>
        )}

        {/* Model missing (or error): offer install */}
        {(status === "model_missing" || status === "install_error") && (
          <button
            onClick={installModel}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-jarvis-accent hover:bg-jarvis-accent-hover text-white transition-colors"
          >
            Install Recommended Model
          </button>
        )}
      </div>

      {/* Recommended model label */}
      <p className="mt-3 text-xs text-jarvis-muted">
        Recommended model: <span className="font-mono text-jarvis-text">{RECOMMENDED_MODEL}</span>
      </p>
    </Card>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function AiCleanupPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">AI Cleanup</h2>
        <p className="text-sm text-jarvis-muted mt-1">Configure Ollama AI cleanup and correction strength.</p>
      </div>

      {/* Ollama readiness — always shown first so users know the state */}
      <OllamaReadinessCard />

      <Card title="AI Cleanup Mode">
        <p className="text-xs text-jarvis-muted mb-3">
          Ollama cleans up raw Whisper output — fixing grammar, punctuation, and formatting.
        </p>
        <div className="flex gap-2">
          {(["auto", "on", "off"] as AiCleanupMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => updateSetting("ai_cleanup_mode", mode)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border capitalize transition-colors ${
                settings.ai_cleanup_mode === mode
                  ? "bg-jarvis-accent border-jarvis-accent text-white"
                  : "bg-jarvis-surface border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        <div className="mt-2 text-xs text-jarvis-muted">
          {settings.ai_cleanup_mode === "auto" && "Smart mode — skips cleanup for short phrases, commands, and questions."}
          {settings.ai_cleanup_mode === "on"   && "Always runs Ollama on every dictation."}
          {settings.ai_cleanup_mode === "off"  && "Raw Whisper output only — no AI cleanup."}
        </div>
      </Card>

      <Card title="Ollama">
        <div className="flex flex-col gap-3">
          <Toggle
            checked={settings.use_ollama}
            onChange={(v) => updateSetting("use_ollama", v)}
            label="Enable Ollama"
            description="Requires Ollama running locally with qwen2.5:3b"
          />
          <div className="border-t border-jarvis-border" />
          <Toggle
            checked={settings.safe_mode}
            onChange={(v) => updateSetting("safe_mode", v)}
            label="Safe mode"
            description="Extra conservative cleanup — never changes meaning"
          />
          <div className="border-t border-jarvis-border" />
          <Toggle
            checked={settings.context_format}
            onChange={(v) => updateSetting("context_format", v)}
            label="Context-aware formatting"
            description="Detects the active app and adjusts output format accordingly"
          />
        </div>
      </Card>

      <Card title="Correction Strength">
        <div className="flex flex-col gap-2">
          {STRENGTHS.map((s) => (
            <button
              key={s}
              onClick={() => updateSetting("correction_strength", s)}
              className={`flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors ${
                settings.correction_strength === s
                  ? "bg-jarvis-accent/10 border-jarvis-accent"
                  : "bg-jarvis-surface border-jarvis-border hover:border-jarvis-muted"
              }`}
            >
              <span className={`text-sm font-medium ${settings.correction_strength === s ? "text-jarvis-text" : "text-jarvis-muted"}`}>
                {s}
              </span>
              <span className="text-xs text-jarvis-muted">{STRENGTH_DESC[s]}</span>
            </button>
          ))}
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
