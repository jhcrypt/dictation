import React, { useState, useEffect, useCallback } from "react";
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
const OLLAMA_API        = "http://localhost:11434/api/chat";
// Sample phrase used by the Python app's _do_test_cleanup
const TEST_SAMPLE = "this is a test of the local ai cleanup feature its working great";

// ── Ollama status ─────────────────────────────────────────────────────────────
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

// Matches Python STATUS_DETAIL exactly
const STATUS_DETAIL: Record<OllamaStatus, string> = {
  checking:
    "Checking Ollama availability…",
  ready:
    `Ollama is installed, running, and the recommended model (${RECOMMENDED_MODEL}) is available. `
    + "Dictated text will be polished automatically.",
  not_installed:
    "Ollama is not installed on this Mac. "
    + "Dictation still works normally without it — you just won't get AI cleanup.",
  not_running:
    "Ollama is installed but the server is not running. "
    + "Start Ollama from your Applications folder, then click Check Again.",
  model_missing:
    `Ollama is running but the recommended model (${RECOMMENDED_MODEL}) is not downloaded yet. `
    + "Click Install Recommended Model below.",
  installing:
    "Do not close the app. The download runs in the background and may take a minute.",
  install_error:
    "Make sure Ollama is running and you have a network connection, then try again.",
};

// ── Test Cleanup state ────────────────────────────────────────────────────────
type TestState = "idle" | "running" | "passed" | "failed";

// ── Ollama readiness card ─────────────────────────────────────────────────────
function OllamaReadinessCard() {
  const [status,        setStatus]        = useState<OllamaStatus>("checking");
  const [installError,  setInstallError]  = useState("");
  const [testState,     setTestState]     = useState<TestState>("idle");
  const [testOutput,    setTestOutput]    = useState("");
  const [testErrorMsg,  setTestErrorMsg]  = useState("");

  const runCheck = useCallback(async () => {
    setStatus("checking");
    setTestState("idle");
    setTestOutput("");
    setTestErrorMsg("");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const s = await invoke<string>("check_ollama_status");
      setStatus(s as OllamaStatus);
    } catch {
      setStatus("not_installed");
    }
  }, []);

  useEffect(() => { runCheck(); }, [runCheck]);

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
      await runCheck();
    } catch (e) {
      setInstallError(String(e));
      setStatus("install_error");
    }
  }

  // Test Cleanup — hits the Ollama HTTP API directly (same endpoint as the sidecar).
  // Mirrors Python _do_test_cleanup: sends a sample phrase, shows cleaned output.
  async function testCleanup() {
    setTestState("running");
    setTestOutput("");
    setTestErrorMsg("");
    try {
      const resp = await fetch(OLLAMA_API, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model:  RECOMMENDED_MODEL,
          messages: [
            {
              role:    "system",
              content: "You are a dictation cleanup engine. Fix grammar, punctuation, and capitalisation. Keep the same meaning. Output only the corrected text.",
            },
            { role: "user", content: TEST_SAMPLE },
          ],
          stream: false,
          options: { repeat_penalty: 1.15, num_predict: 180, temperature: 0.35 },
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const out  = (data?.message?.content ?? "").trim();
      setTestOutput(out);
      setTestState("passed");
    } catch (e) {
      setTestErrorMsg(String(e));
      setTestState("failed");
    }
  }

  const isBusy    = status === "checking" || status === "installing";
  const canTest   = status === "ready" && testState !== "running";
  const canInstall = status === "model_missing" || status === "install_error";

  // Overlay status label with test result when a test has run
  const displayLabel =
    testState === "running" ? "⏳  Testing cleanup…" :
    testState === "passed"  ? "✓  Test passed" :
    testState === "failed"  ? "✗  Test failed" :
    STATUS_LABEL[status];

  const displayColor =
    testState === "running" ? "#0a84ff" :
    testState === "passed"  ? "#30d158" :
    testState === "failed"  ? "#ff3b30" :
    STATUS_COLOR[status];

  return (
    <Card title="Local AI Cleanup (Ollama)">
      {/* Status / test result label */}
      <div className="mb-1">
        <div className="text-sm font-semibold" style={{ color: displayColor }}>
          {displayLabel}
        </div>
      </div>

      {/* Detail text */}
      {testState === "idle" && (
        <p className="text-xs text-jarvis-hint leading-relaxed mb-3">
          {STATUS_DETAIL[status]}
        </p>
      )}
      {testState === "running" && (
        <p className="text-xs text-jarvis-hint leading-relaxed mb-3">
          Input: &ldquo;{TEST_SAMPLE}&rdquo;
        </p>
      )}
      {testState === "passed" && (
        <p className="text-xs text-jarvis-hint leading-relaxed mb-3">
          Output: &ldquo;{testOutput}&rdquo;
        </p>
      )}
      {testState === "failed" && (
        <p className="text-xs text-red-400 leading-relaxed font-mono break-all mb-3">
          {testErrorMsg}
        </p>
      )}

      {/* Install error detail */}
      {status === "install_error" && installError && testState === "idle" && (
        <p className="text-xs font-mono text-red-400 break-all leading-relaxed mb-3">
          {installError}
        </p>
      )}

      {/* Fallback note — matches Python fallback_lbl */}
      {(status === "not_installed" || status === "not_running") && (
        <p className="text-xs text-jarvis-hint italic mb-3">
          Dictation still works without Local AI Cleanup.
        </p>
      )}

      {/* Action buttons — 2×2 grid matching Python layout */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={runCheck}
          disabled={isBusy}
          className="py-2 px-4 rounded-lg text-sm font-medium border border-jarvis-border bg-jarvis-sidebar text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors disabled:opacity-40"
        >
          Check Again
        </button>

        <button
          onClick={openDownload}
          className="py-2 px-4 rounded-lg text-sm font-medium border border-jarvis-border bg-jarvis-sidebar text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors"
        >
          Open Ollama Download Page
        </button>

        <button
          onClick={testCleanup}
          disabled={!canTest}
          title={status !== "ready" ? "Ollama must be ready to test" : undefined}
          className="py-2 px-4 rounded-lg text-sm font-medium border border-jarvis-border bg-jarvis-sidebar text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors disabled:opacity-40"
        >
          {testState === "running" ? "Testing…" : "Test Cleanup"}
        </button>

        <button
          onClick={installModel}
          disabled={!canInstall || isBusy}
          title={!canInstall ? `Install available when model is missing` : undefined}
          className={`py-2 px-4 rounded-lg text-sm font-medium border transition-colors ${
            canInstall
              ? "bg-jarvis-accent border-jarvis-accent hover:bg-jarvis-accent-hover text-white"
              : "border-jarvis-border bg-jarvis-sidebar text-jarvis-muted opacity-40 cursor-not-allowed"
          }`}
        >
          {status === "installing" ? `Downloading ${RECOMMENDED_MODEL}…` : "Install Recommended Model"}
        </button>
      </div>

      {/* Recommended model footer */}
      <p className="mt-3 text-xs text-jarvis-hint">
        Recommended model:{" "}
        <span className="font-mono text-jarvis-text">{RECOMMENDED_MODEL}</span>
      </p>
    </Card>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function AiCleanupPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      {/* Header — matches Python page title + subtitle */}
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Local AI Cleanup</h2>
        <p className="text-sm text-jarvis-hint mt-1">
          Polish dictated text with a local Ollama model after transcription.
        </p>
      </div>

      {/* English-only caveat — matches Python description text */}
      <div className="px-3 py-2.5 rounded-lg border border-jarvis-border bg-jarvis-surface">
        <p className="text-xs text-jarvis-hint leading-relaxed">
          Local AI Cleanup currently improves English dictation. For other spoken languages,
          Quill skips cleanup automatically to avoid accidental translation.
        </p>
      </div>

      {/* Ollama readiness — always first */}
      <OllamaReadinessCard />

      {/* AI Cleanup Mode — full 3-line explanation always visible, matches Python helper_text */}
      <Card title="Local AI Cleanup Mode">
        <div className="flex gap-2 mb-3">
          {(["auto", "on", "off"] as AiCleanupMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => updateSetting("ai_cleanup_mode", mode)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border capitalize transition-colors ${
                settings.ai_cleanup_mode === mode
                  ? "bg-jarvis-accent border-jarvis-accent text-white"
                  : "bg-jarvis-sidebar border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        {/* All three descriptions always shown — matches Python helper_text block */}
        <div className="text-xs text-jarvis-hint leading-relaxed space-y-1 font-mono">
          <p>
            <span className={settings.ai_cleanup_mode === "auto" ? "text-jarvis-text font-semibold" : ""}>auto</span>
            {" — "}use Local AI Cleanup if available, skip silently if not{" "}
            <span className="text-jarvis-hint">(recommended)</span>.
          </p>
          <p>
            <span className={settings.ai_cleanup_mode === "on" ? "text-jarvis-text font-semibold" : ""}>on</span>
            {" — "}always try to use it; show a warning in the HUD if unavailable.
          </p>
          <p>
            <span className={settings.ai_cleanup_mode === "off" ? "text-jarvis-text font-semibold" : ""}>off</span>
            {" — "}never use Local AI Cleanup.
          </p>
        </div>
      </Card>

      {/* Correction Strength — with "Recommended: Standard" note matching Python */}
      <Card title="Correction Strength">
        <div className="flex flex-col gap-2 mb-3">
          {STRENGTHS.map((s) => (
            <button
              key={s}
              onClick={() => updateSetting("correction_strength", s)}
              className={`flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors ${
                settings.correction_strength === s
                  ? "bg-jarvis-accent/10 border-jarvis-accent"
                  : "bg-jarvis-sidebar border-jarvis-border hover:border-jarvis-muted"
              }`}
            >
              <span className={`text-sm font-medium ${settings.correction_strength === s ? "text-jarvis-text" : "text-jarvis-muted"}`}>
                {s}
              </span>
              <span className="text-xs text-jarvis-muted">{STRENGTH_DESC[s]}</span>
            </button>
          ))}
        </div>
        {/* Note matching Python helper_text */}
        <p className="text-xs text-jarvis-hint leading-relaxed">
          Recommended: Standard. Short phrases and unsafe AI rewrites are always protected.
        </p>
      </Card>

      {/* Ollama toggles */}
      <Card title="Ollama">
        <div className="flex flex-col gap-3">
          <Toggle
            checked={settings.use_ollama}
            onChange={(v) => updateSetting("use_ollama", v)}
            label="Enable Ollama"
            description="Requires Ollama running locally with qwen2.5:3b"
          />
          <div className="border-t border-jarvis-border" />
          {/* Safe Mode description matches Python: "Pure dictation: disables Local AI Cleanup…" */}
          <Toggle
            checked={settings.safe_mode}
            onChange={(v) => updateSetting("safe_mode", v)}
            label="Safe Mode"
            description="Pure dictation — disables Local AI Cleanup, Jarvis commands, and cloud transcription"
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

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
