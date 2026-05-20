import React, { useState } from "react";
import Card from "../components/ui/Card";

interface DiagnosticsReport {
  app_path: string;
  bundle_id: string;
  accessibility_trusted: boolean;
  sidecar_running: boolean;
  sidecar_pid: number | null;
  python_path: string | null;
  sidecar_ping: string;
  mic_device: number | null;
  mic_list: string;
  mic_test: string;
  hotkey_listener: string;
  paste_target: string;
}

export default function HelpPage() {
  const [storageStatus, setStorageStatus] = useState("");
  const [diag, setDiag] = useState<DiagnosticsReport | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagError, setDiagError] = useState("");

  async function runDiagnostics() {
    setDiagBusy(true);
    setDiagError("");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const result = await invoke<DiagnosticsReport>("get_diagnostics");
      setDiag(result);
    } catch (e) {
      setDiagError(String(e));
    }
    setDiagBusy(false);
  }

  async function clearVocab() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("clear_vocabulary");
      setStorageStatus("Vocabulary cleared.");
    } catch { setStorageStatus("Vocabulary cleared (preview)."); }
    setTimeout(() => setStorageStatus(""), 2000);
  }

  async function clearLog() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("clear_log");
      setStorageStatus("Log cleared.");
    } catch { setStorageStatus("Log cleared (preview)."); }
    setTimeout(() => setStorageStatus(""), 2000);
  }

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Help</h2>
        <p className="text-sm text-jarvis-hint mt-1">Reference, troubleshooting, and storage management.</p>
      </div>

      <Card title="About">
        <div className="text-xs text-jarvis-hint space-y-1">
          <p className="text-sm text-jarvis-text font-semibold">Jarvis Dictation Tauri Preview</p>
          <p>Bundle ID: <span className="font-mono text-jarvis-text">com.jarvis.dictation.tauri</span></p>
          <p>Version: <span className="font-mono text-jarvis-text">0.1.0</span></p>
          <p className="text-jarvis-hint pt-1">This is the Tauri port — a separate app from the stable Python version at <span className="font-mono">/Applications/Jarvis Dictation.app</span>.</p>
        </div>
      </Card>

      <Card title="Quick Reference">
        <div className="text-xs text-jarvis-hint space-y-2 leading-relaxed">
          <div className="flex gap-3">
            <span className="text-jarvis-text font-mono bg-jarvis-surface px-2 py-0.5 rounded whitespace-nowrap">Right Option</span>
            <span>Hold to record, release to transcribe</span>
          </div>
          <div className="flex gap-3">
            <span className="text-jarvis-text font-mono bg-jarvis-surface px-2 py-0.5 rounded whitespace-nowrap">Esc</span>
            <span>Cancel active recording or wake-word session</span>
          </div>
          <div className="flex gap-3">
            <span className="text-jarvis-text font-mono bg-jarvis-surface px-2 py-0.5 rounded whitespace-nowrap">Hey Jarvis</span>
            <span>Hands-free recording (if wake word is enabled)</span>
          </div>
        </div>
      </Card>

      <Card title="Permissions Required">
        <div className="text-xs text-jarvis-hint space-y-1.5">
          <p><span className="text-jarvis-text font-medium">Microphone</span> — to record audio</p>
          <p><span className="text-jarvis-text font-medium">Accessibility</span> — to detect the hotkey and paste text</p>
          <p><span className="text-jarvis-text font-medium">Automation</span> — to control Mail.app and Reminders via AppleScript</p>
        </div>
        <button
          onClick={() => { try { (window as any).__TAURI__?.shell?.open("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"); } catch {} }}
          className="mt-3 text-xs text-jarvis-accent hover:underline"
        >
          Open System Settings → Privacy
        </button>
      </Card>

      <Card title="Data Files">
        <div className="text-xs text-jarvis-hint space-y-1 font-mono">
          <p>~/.dictation_settings.json</p>
          <p>~/.dictation_contacts.json</p>
          <p>~/.dictation_history.json</p>
          <p>~/.dictation_vocabulary.json</p>
          <p>~/.dictation_custom_commands.json</p>
          <p>~/.dictation_snippets.json</p>
        </div>
      </Card>

      <Card title="Storage &amp; Cleanup">
        {storageStatus && <p className="text-xs text-jarvis-success mb-2">{storageStatus}</p>}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-jarvis-text">Vocabulary data</p>
              <p className="text-xs text-jarvis-hint">Word frequency counts learned from dictations</p>
            </div>
            <button
              onClick={clearVocab}
              className="text-xs text-jarvis-muted hover:text-jarvis-recording border border-jarvis-border rounded-lg px-3 py-1.5 transition-colors"
            >
              Clear
            </button>
          </div>
          <div className="border-t border-jarvis-border" />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-jarvis-text">Startup debug log</p>
              <p className="text-xs text-jarvis-hint">~/jarvis_startup_debug.log</p>
            </div>
            <button
              onClick={clearLog}
              className="text-xs text-jarvis-muted hover:text-jarvis-recording border border-jarvis-border rounded-lg px-3 py-1.5 transition-colors"
            >
              Clear
            </button>
          </div>
        </div>
      </Card>

      <Card title="Diagnostics">
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={runDiagnostics}
            disabled={diagBusy}
            className="px-3 py-1.5 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            {diagBusy ? "Running…" : "Run Diagnostics"}
          </button>
          {diagError && <span className="text-xs text-red-400">{diagError}</span>}
        </div>
        {diag && (
          <div className="text-xs font-mono space-y-1.5">
            {[
              ["App path",       diag.app_path],
              ["Bundle ID",      diag.bundle_id],
              ["Accessibility",  diag.accessibility_trusted ? "✅ granted" : "❌ not granted"],
              ["Sidecar",        diag.sidecar_running ? `✅ running (PID ${diag.sidecar_pid})` : "❌ not running"],
              ["Python",         diag.python_path ?? "unknown"],
              ["Sidecar ping",   diag.sidecar_ping],
              ["Mic device",     diag.mic_device !== null && diag.mic_device !== undefined ? String(diag.mic_device) : "system default"],
              ["Mic list",       diag.mic_list],
              ["Mic test",       diag.mic_test],
              ["Paste target",   diag.paste_target],
              ["Hotkey",         diag.hotkey_listener],
            ].map(([label, value]) => (
              <div key={label} className="flex flex-col gap-0.5">
                <span className="text-jarvis-muted uppercase tracking-wide text-[10px]">{label}</span>
                <span className={`text-jarvis-text break-all ${
                  String(value).includes("ERROR") || String(value).includes("❌") ? "text-red-400" : ""
                }`}>{value}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Debug">
        <p className="text-xs text-jarvis-hint leading-relaxed">
          Enable <span className="text-jarvis-text">Debug Logging</span> in Setup if Jarvis isn't behaving as expected.
          Logs are written to <span className="font-mono text-jarvis-text">~/jarvis_startup_debug.log</span>.
        </p>
      </Card>
    </div>
  );
}
