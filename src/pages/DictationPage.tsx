import React, { useState, useEffect, useCallback } from "react";
import Card from "../components/ui/Card";
import { useSettings } from "../context/SettingsContext";
import type { DictationTiming } from "../hooks/useGlobalHotkey";

type SidecarStatus = "checking" | "ready" | "error";

/** Format a millisecond value as "1.23s" or "—" if undefined/zero */
function fmtMs(ms: number | undefined, hideZero = false): string {
  if (ms === undefined) return "—";
  if (hideZero && ms === 0) return "—";
  return `${(ms / 1000).toFixed(2)}s`;
}

/** Single label → value row for the timing card */
function TimingRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className={`text-xs ${bold ? "text-jarvis-text font-medium" : "text-jarvis-muted"}`}>
        {label}
      </span>
      <span className={`text-xs font-mono ${
        value === "—" || value === "skipped" || value === "off"
          ? "text-jarvis-muted"
          : bold ? "text-jarvis-text font-semibold" : "text-jarvis-text"
      }`}>
        {value}
      </span>
    </div>
  );
}

export default function DictationPage() {
  const { settings } = useSettings();
  const [sidecarStatus, setSidecarStatus] = useState<SidecarStatus>("checking");
  const [sidecarError,  setSidecarError]  = useState("");
  // hudState mirrors the global HUD state machine — drives all button display
  const [hudState,      setHudState]      = useState<string>("idle");
  const [lastText,      setLastText]      = useState("");
  const [dictTiming,    setDictTiming]    = useState<DictationTiming | null>(null);
  const [axGranted,     setAxGranted]     = useState<boolean | null>(null);
  const [copied,        setCopied]        = useState(false);
  const [targetApp,     setTargetApp]     = useState<string | null>(null);

  useEffect(() => {
    checkSidecar();
    checkAccessibility();
    pollTargetApp();
    const interval = setInterval(pollTargetApp, 2000);
    return () => clearInterval(interval);
  }, []);

  // Mirror global hud-state → drives button label / color / disabled
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    import("@tauri-apps/api/event").then(({ listen }) => {
      listen<{ state: string }>("hud-state", (e) => {
        console.log("[dictation-button] hud-state =", e.payload.state);
        setHudState(e.payload.state);
      }).then(fn => { unlisten = fn; });
    }).catch(() => {});
    return () => { unlisten?.(); };
  }, []);

  // Last dictated text — emitted by useGlobalHotkey after each successful dictation
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    import("@tauri-apps/api/event").then(({ listen }) => {
      listen<string>("last-dictation-text", (e) => {
        setLastText(e.payload);
      }).then(fn => { unlisten = fn; });
    }).catch(() => {});
    return () => { unlisten?.(); };
  }, []);

  // Timing breakdown — emitted by useGlobalHotkey after each dictation cycle
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    import("@tauri-apps/api/event").then(({ listen }) => {
      listen<DictationTiming>("dictation-timing", (e) => {
        setDictTiming(e.payload);
      }).then(fn => { unlisten = fn; });
    }).catch(() => {});
    return () => { unlisten?.(); };
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

  // ── Copy to clipboard ────────────────────────────────────────────────────

  const copyText = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("copy_to_clipboard", { text });
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch { /* ignore */ }
    }
  }, []);

  // ── Button — routes through useGlobalHotkey state machine via events ──────
  //
  // Both start and stop emit events that useGlobalHotkey handles.
  // This ensures the button and the hotkey share a single recording state
  // machine and never call the sidecar from two places simultaneously.
  //
  // ui-start-recording → useGlobalHotkey.startRecording()
  // ui-stop-recording  → useGlobalHotkey.stopAndTranscribe() or cancelRecording()

  const effectiveRecording = hudState === "recording" || hudState === "wake_recording";
  const effectiveBusy      = hudState === "transcribing" || hudState === "cleanup" || hudState === "skipped";

  const handleButtonClick = async () => {
    console.log("[dictation-button] click  hudState=", hudState, " sidecarStatus=", sidecarStatus);
    try {
      const { emit } = await import("@tauri-apps/api/event");
      if (effectiveRecording) {
        console.log("[dictation-button] stop requested");
        await emit("ui-stop-recording", {});
      } else {
        console.log("[dictation-button] start requested");
        await emit("ui-start-recording", {});
      }
    } catch { /* browser preview */ }
  };

  // ── UI ────────────────────────────────────────────────────────────────────

  const statusDot = sidecarStatus === "ready"
    ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-success mr-2" />
    : sidecarStatus === "checking"
    ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-transcribing animate-pulse mr-2" />
    : <span className="inline-block w-2 h-2 rounded-full bg-red-400 mr-2" />;

  const isDisabled = effectiveBusy || sidecarStatus !== "ready";

  const label =
    sidecarStatus === "checking"  ? "Starting engine…" :
    sidecarStatus === "error"     ? "Engine unavailable" :
    effectiveBusy                 ? "Transcribing…" :
    effectiveRecording            ? "Stop Recording" :
                                    "Start Recording";

  const btnCls = isDisabled
    ? "bg-jarvis-surface text-jarvis-muted cursor-not-allowed"
    : effectiveRecording
    ? "bg-jarvis-recording hover:bg-red-600 text-white"
    : "bg-jarvis-accent hover:bg-jarvis-accent-hover text-white";

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Dictation</h2>
        <p className="text-sm text-jarvis-hint mt-1">Hold Right Option anywhere to dictate.</p>
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

      {/* Manual record button — shares state machine with hotkey via ui-start/stop-recording events */}
      <Card>
        <button
          onClick={handleButtonClick}
          disabled={isDisabled}
          className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all ${btnCls}`}
        >
          {label}
        </button>

        {/* Target app indicator */}
        <div className="mt-2 text-center">
          {targetApp ? (
            <p className="text-xs text-jarvis-muted">
              Will paste into: <span className="text-jarvis-text">{targetApp.split(" (")[0]}</span>
            </p>
          ) : (
            <p className="text-xs text-jarvis-hint leading-relaxed">
              Hold{" "}
              <kbd className="px-1.5 py-0.5 bg-jarvis-surface border border-jarvis-border rounded text-[11px]">Right Option</kbd>
              {" "}anywhere to dictate, or click into your target app first and use the button above.
            </p>
          )}
        </div>
      </Card>

      {/* Last transcript */}
      {lastText && (
        <Card title="Last Transcript">
          <p className="text-sm text-jarvis-text leading-relaxed">{lastText}</p>
          <div className="flex items-center gap-3 mt-3 pt-3 border-t border-jarvis-border">
            <button
              onClick={() => copyText(lastText)}
              className="text-xs px-2.5 py-1 rounded-lg border border-jarvis-border bg-jarvis-surface text-jarvis-muted hover:text-jarvis-text transition-colors shrink-0"
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>
        </Card>
      )}

      {/* Last Dictation Timing — always visible; shows placeholders before first dictation */}
      <Card title="Last Dictation Timing">
        {!dictTiming ? (
          // Pre-dictation placeholder
          <div className="flex flex-col gap-0">
            <p className="text-xs text-jarvis-muted mb-2 pb-2 border-b border-jarvis-border">
              Timing will appear here after your first dictation.
            </p>
            <TimingRow label="Model"              value="—" />
            <TimingRow label="Recording"          value="—" />
            <TimingRow label="Stop processing"    value="—" />
            <TimingRow label="Transcription"      value="—" />
            <TimingRow label="Cleanup"            value="—" />
            <TimingRow label="Paste"              value="—" />
            <div className="border-t border-jarvis-border my-1.5" />
            <TimingRow label="Total after release" value="—" bold />
            <TimingRow label="Total cycle"         value="—" bold />
          </div>
        ) : (
          <div className="flex flex-col gap-0">
            {/* Header row: model + profile + status */}
            <div className="flex items-center gap-3 mb-2 pb-2 border-b border-jarvis-border">
              {dictTiming.model && (
                <span className="text-xs font-mono bg-jarvis-sidebar border border-jarvis-border rounded px-2 py-0.5 text-jarvis-text">
                  {dictTiming.model}
                </span>
              )}
              {dictTiming.profile && (
                <span className="text-xs text-jarvis-muted">{dictTiming.profile}</span>
              )}
              {dictTiming.status && (
                <span className={`ml-auto text-xs font-medium ${
                  dictTiming.status === "pasted"       ? "text-green-400" :
                  dictTiming.status === "paste_failed" ? "text-red-400"   :
                  "text-jarvis-muted"
                }`}>
                  {dictTiming.status}
                </span>
              )}
            </div>

            {/* Timing rows — Python label convention */}
            <TimingRow label="Recording"          value={fmtMs(dictTiming.recordingMs, true)} />
            <TimingRow label="Stop processing"    value={fmtMs(dictTiming.stopMs)} />
            <TimingRow label="Transcription"      value={fmtMs(dictTiming.transcriptionMs)} />
            <TimingRow
              label="Cleanup"
              value={
                dictTiming.cleanupStatus === "off"     ? "off" :
                dictTiming.cleanupStatus === "skipped" ? "skipped" :
                fmtMs(dictTiming.cleanupMs)
              }
            />
            <TimingRow label="Paste"              value={fmtMs(dictTiming.pasteMs, true)} />
            <div className="border-t border-jarvis-border my-1.5" />
            <TimingRow label="Total after release" value={fmtMs(dictTiming.totalAfterReleaseMs)} bold />
            <TimingRow label="Total cycle"         value={fmtMs(dictTiming.totalCycleMs, true)} bold />
          </div>
        )}
      </Card>
    </div>
  );
}
