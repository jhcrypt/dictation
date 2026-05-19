import React, { useState, useEffect, useCallback } from "react";
import Card from "../components/ui/Card";
import { useSettings } from "../context/SettingsContext";

type RecordingState = "idle" | "recording" | "transcribing";
type SidecarStatus  = "checking" | "ready" | "error";

export default function DictationPage() {
  const { settings } = useSettings();
  const [sidecarStatus, setSidecarStatus] = useState<SidecarStatus>("checking");
  const [sidecarError,  setSidecarError]  = useState("");
  const [state,         setState]         = useState<RecordingState>("idle");
  const [lastText,      setLastText]      = useState("");
  const [timing,        setTiming]        = useState<{ whisper: number; ollama: number; total: number } | null>(null);
  const [axGranted,     setAxGranted]     = useState<boolean | null>(null);
  const [copied,        setCopied]        = useState(false);
  const [targetApp,     setTargetApp]     = useState<string | null>(null);
  const [pasteError,    setPasteError]    = useState("");

  useEffect(() => {
    checkSidecar();
    checkAccessibility();
    pollTargetApp();
    const interval = setInterval(pollTargetApp, 2000);
    return () => clearInterval(interval);
  }, []);

  async function pollTargetApp() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const app = await invoke<string | null>("get_last_target_app");
      setTargetApp(app);
    } catch { /* preview */ }
  }

  // ── Accessibility ─────────────────────────────────────────────────────────

  async function checkAccessibility() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const ok = await invoke<boolean>("get_accessibility_status");
      setAxGranted(ok);
      console.log("[accessibility] granted:", ok);
    } catch { setAxGranted(null); }
  }

  // ── Sidecar ───────────────────────────────────────────────────────────────

  async function checkSidecar() {
    setSidecarStatus("checking");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("sidecar_ping");
      setSidecarStatus("ready");
    } catch {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("sidecar_start");
        await invoke("sidecar_ping");
        setSidecarStatus("ready");
      } catch (e2) {
        setSidecarStatus("error");
        setSidecarError(String(e2));
      }
    }
  }

  // ── HUD helper ────────────────────────────────────────────────────────────

  async function hudEmit(hudState: string, payload?: { subtext?: string; profile?: string; status?: string }) {
    try {
      const { emit } = await import("@tauri-apps/api/event");
      emit("hud-state", { state: hudState, ...payload });
    } catch { /* browser preview */ }
  }

  // ── Copy to clipboard ────────────────────────────────────────────────────

  const copyText = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: ask Tauri to copy via arboard
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("copy_to_clipboard", { text });
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch { /* ignore */ }
    }
  }, []);

  // ── Manual record button ──────────────────────────────────────────────────

  const handleRecord = async () => {
    if (state === "idle") {
      setState("recording");
      hudEmit("recording");
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("sidecar_start_recording");
      } catch (e) {
        setSidecarError(String(e));
        setSidecarStatus("error");
        setState("idle");
        hudEmit("error", { subtext: String(e) });
        setTimeout(() => hudEmit("idle"), 4000);
      }

    } else if (state === "recording") {
      setState("transcribing");
      hudEmit("transcribing");
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("sidecar_stop_recording");

        const result = await invoke<{
          ok: boolean; text: string;
          timing: { whisper: number; ollama: number; total: number };
          error?: string;
          profile?: string;
          status?: string;
          skipped_cleanup?: boolean;
          skip_reason?: string;
        }>("sidecar_transcribe_last");

        if (result.ok && result.text) {
          setLastText(result.text);
          setTiming(result.timing);

          // Show cleanup state briefly if Ollama ran
          if (!result.skipped_cleanup && settings.use_ollama && settings.ai_cleanup_mode !== "off") {
            hudEmit("cleanup");
            await new Promise((r) => setTimeout(r, 600));
          }

          // Show skipped state if cleanup was skipped
          if (result.skipped_cleanup && result.skip_reason) {
            hudEmit("skipped", { subtext: result.skip_reason });
            await new Promise((r) => setTimeout(r, 1200));
          }

          let pasteStatus = "transcribed";
          setPasteError("");
          if (!settings.safe_mode) {
            try {
              await invoke("paste_text", { text: result.text });
              pasteStatus = "pasted";
            } catch (pe) {
              pasteStatus = "paste_failed";
              setPasteError(String(pe));
            }
          }

          const profile = result.profile ?? settings.writing_profile ?? "General";
          hudEmit("inserted", {
            subtext: result.text.slice(0, 55),
            status:  pasteStatus,
            profile: settings.show_active_profile ? profile : undefined,
          });

          try {
            await invoke("save_history_entry", {
              entry: {
                timestamp: new Date().toISOString(),
                final_text: result.text,
                status: pasteStatus,
                profile,
                source: "tauri",
                timing: result.timing ?? null,
              },
            });
          } catch (he) { console.error("[history] save failed:", he); }

          setTimeout(() => hudEmit("idle"), 3500);
        } else {
          setSidecarError(result.error ?? "Transcription failed");
          hudEmit("error", { subtext: result.error ?? "Transcription failed" });
          setTimeout(() => hudEmit("idle"), 4000);
        }
      } catch (e) {
        setSidecarError(String(e));
        hudEmit("error", { subtext: String(e) });
        setTimeout(() => hudEmit("idle"), 4000);
      }
      setState("idle");
    }
  };

  // ── UI ────────────────────────────────────────────────────────────────────

  const statusDot = sidecarStatus === "ready"
    ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-success mr-2" />
    : sidecarStatus === "checking"
    ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-transcribing animate-pulse mr-2" />
    : <span className="inline-block w-2 h-2 rounded-full bg-red-400 mr-2" />;

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Dictation</h2>
        <p className="text-sm text-jarvis-muted mt-1">Hold Right Option anywhere to dictate.</p>
      </div>

      {/* Engine status */}
      <Card title="Engine Status">
        <div className="flex items-center">
          {statusDot}
          <span className="text-sm text-jarvis-muted">
            {sidecarStatus === "checking" && "Starting Python engine…"}
            {sidecarStatus === "ready"    && "Python engine running"}
            {sidecarStatus === "error"    && "Engine error"}
          </span>
          {sidecarStatus !== "checking" && (
            <button onClick={checkSidecar}
              className="ml-auto text-xs text-jarvis-muted hover:text-jarvis-text transition-colors">
              Retry
            </button>
          )}
        </div>
        {sidecarStatus === "error" && sidecarError && (
          <p className="text-xs text-red-400 mt-2 font-mono break-all">{sidecarError}</p>
        )}
      </Card>

      {/* Accessibility warning */}
      {axGranted === false && (
        <div className="px-3 py-2.5 rounded-lg border border-red-500/30 bg-red-500/10 flex items-start gap-2">
          <span className="text-red-400 text-xs font-semibold mt-0.5 shrink-0">PERMISSION</span>
          <p className="text-xs text-jarvis-muted leading-relaxed">
            Accessibility permission required for global hotkey and auto-paste.
            Open <strong className="text-jarvis-text">Setup → Accessibility Permission</strong> to grant it.
          </p>
        </div>
      )}

      {/* Safe mode notice */}
      {settings.safe_mode && (
        <div className="px-3 py-2.5 rounded-lg border border-jarvis-border bg-jarvis-surface flex items-start gap-2">
          <span className="text-jarvis-transcribing text-xs font-semibold mt-0.5 shrink-0">SAFE MODE</span>
          <p className="text-xs text-jarvis-muted leading-relaxed">
            Text copied to clipboard only — auto-paste is disabled.
          </p>
        </div>
      )}

      {/* Manual record button */}
      <Card>
        <button
          onClick={handleRecord}
          disabled={state === "transcribing" || sidecarStatus !== "ready"}
          className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all ${
            sidecarStatus !== "ready"
              ? "bg-jarvis-surface text-jarvis-muted cursor-not-allowed"
              : state === "idle"
              ? "bg-jarvis-accent hover:bg-jarvis-accent-hover text-white"
              : state === "recording"
              ? "bg-jarvis-recording hover:bg-red-600 text-white"
              : "bg-jarvis-surface text-jarvis-muted cursor-not-allowed"
          }`}
        >
          {sidecarStatus === "checking"  ? "Starting engine…"
          : sidecarStatus === "error"    ? "Engine unavailable"
          : state === "idle"             ? "Start Recording"
          : state === "recording"        ? "Stop Recording"
          :                               "Transcribing…"}
        </button>
        {/* Target app indicator */}
        <div className="mt-2 text-center">
          {targetApp ? (
            <p className="text-xs text-jarvis-muted">
              Will paste into: <span className="text-jarvis-text">{targetApp.split(" (")[0]}</span>
            </p>
          ) : (
            <p className="text-xs text-jarvis-muted leading-relaxed">
              Hold{" "}
              <kbd className="px-1.5 py-0.5 bg-jarvis-surface border border-jarvis-border rounded text-[11px]">Right Option</kbd>
              {" "}anywhere to dictate, or click into your target app first and use the button above.
            </p>
          )}
        </div>

        {/* Paste error */}
        {pasteError && (
          <div className="mt-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30">
            <p className="text-xs text-red-400 leading-relaxed">{pasteError}</p>
          </div>
        )}
      </Card>

      {/* Last transcript */}
      {lastText && (
        <Card title="Last Transcript">
          <p className="text-sm text-jarvis-text leading-relaxed">{lastText}</p>
          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-jarvis-border">
            <button
              onClick={() => copyText(lastText)}
              className="text-xs px-2.5 py-1 rounded-lg border border-jarvis-border bg-jarvis-surface text-jarvis-muted hover:text-jarvis-text transition-colors shrink-0"
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
            {timing && (
              <div className="flex gap-4 flex-wrap">
                <span className="text-xs text-jarvis-muted">Whisper: <span className="text-jarvis-text">{timing.whisper}ms</span></span>
                {timing.ollama > 0 && (
                  <span className="text-xs text-jarvis-muted">Ollama: <span className="text-jarvis-text">{timing.ollama}ms</span></span>
                )}
                <span className="text-xs text-jarvis-muted">Total: <span className="text-jarvis-text">{timing.total}ms</span></span>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
