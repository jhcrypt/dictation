import React, { useState, useEffect } from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";

interface MicDevice { index: number; name: string; default_sample_rate: number; }
interface MicListResult { ok: boolean; devices?: MicDevice[]; selected?: number | null; default_index?: number; selected_exists?: boolean; error?: string; }
interface MicTestResult { ok: boolean; device?: number | null; sample_rate?: number; bytes_read?: number; error?: string; }

export default function SetupPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();
  const [micList,       setMicList]       = useState<MicListResult | null>(null);
  const [micTest,       setMicTest]       = useState<MicTestResult | null>(null);
  const [micBusy,       setMicBusy]       = useState(false);
  const [axGranted,     setAxGranted]     = useState<boolean | null>(null);
  const [axChecking,    setAxChecking]    = useState(false);
  const [launchAtLogin, setLaunchAtLogin] = useState<boolean>(false);
  const [lalBusy,       setLalBusy]       = useState(false);

  useEffect(() => { checkAx(); loadLaunchAtLogin(); }, []);

  async function loadLaunchAtLogin() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const v = await invoke<boolean>("get_launch_at_login");
      setLaunchAtLogin(v);
    } catch { /* preview */ }
  }

  async function toggleLaunchAtLogin(enabled: boolean) {
    setLalBusy(true);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("set_launch_at_login", { enabled });
      setLaunchAtLogin(enabled);
    } catch (e) {
      console.error("[setup] set_launch_at_login failed:", e);
    }
    setLalBusy(false);
  }

  async function checkAx() {
    setAxChecking(true);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const ok = await invoke<boolean>("get_accessibility_status");
      setAxGranted(ok);
    } catch { setAxGranted(null); }
    setAxChecking(false);
  }

  async function openAxSettings() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_accessibility_settings");
    } catch { /* preview */ }
  }

  async function runListMics() {
    setMicBusy(true);
    setMicList(null);
    setMicTest(null);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const result = await invoke<MicListResult>("sidecar_list_microphones");
      setMicList(result);
    } catch (e) {
      setMicList({ ok: false, error: String(e) });
    }
    setMicBusy(false);
  }

  async function runTestMic() {
    setMicBusy(true);
    setMicTest(null);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const result = await invoke<MicTestResult>("sidecar_test_microphone");
      setMicTest(result);
    } catch (e) {
      setMicTest({ ok: false, error: String(e) });
    }
    setMicBusy(false);
  }

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Setup</h2>
        <p className="text-sm text-jarvis-hint mt-1">Basic configuration to get started.</p>
      </div>

      <Card title="Recording Hotkey">
        <p className="text-sm text-jarvis-hint mb-3">
          Current hotkey: <span className="text-jarvis-text font-medium">{settings.hotkey_label}</span>
        </p>
        <div className="flex gap-2 flex-wrap">
          {(["Right Option", "F13", "F14", "F15"] as const).map((key) => (
            <button
              key={key}
              onClick={() => updateSetting("hotkey_label", key)}
              className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                settings.hotkey_label === key
                  ? "bg-jarvis-accent border-jarvis-accent text-white"
                  : "bg-jarvis-sidebar border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted"
              }`}
            >
              {key}
            </button>
          ))}
        </div>
      </Card>

      <Card title="Behavior">
        <Toggle
          checked={settings.toggle_mode}
          onChange={(v) => updateSetting("toggle_mode", v)}
          label="Toggle Mode"
          description="Tap to start, tap to stop (instead of hold-to-record)"
        />
        <div className="border-t border-jarvis-border my-1" />
        <Toggle
          checked={settings.show_hud}
          onChange={(v) => updateSetting("show_hud", v)}
          label="Show HUD"
          description="Floating overlay showing recording state"
        />
        <div className="border-t border-jarvis-border my-1" />
        <Toggle
          checked={settings.safe_mode}
          onChange={(v) => updateSetting("safe_mode", v)}
          label="Safe Mode"
          description="Copy to clipboard only — no auto-paste"
        />
        <div className="border-t border-jarvis-border my-1" />
        <Toggle
          checked={settings.play_sounds}
          onChange={(v) => updateSetting("play_sounds", v)}
          label="Play Sounds"
          description="Audio feedback on start/stop"
        />
      </Card>

      <Card title="Accessibility Permission">
        <p className="text-sm text-jarvis-hint mb-3">
          Required for global hotkey (Right Option) and auto-paste into other apps.
        </p>
        <div className="flex items-center gap-2 mb-3">
          {axChecking
            ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-muted animate-pulse" />
            : axGranted
            ? <span className="inline-block w-2 h-2 rounded-full bg-jarvis-success" />
            : <span className="inline-block w-2 h-2 rounded-full bg-red-400" />}
          <span className="text-sm text-jarvis-muted">
            {axChecking  ? "Checking…"
            : axGranted  ? "Permission granted"
            : axGranted === false ? "Permission not granted"
            : "Unknown"}
          </span>
          <button onClick={checkAx}
            className="ml-auto text-xs text-jarvis-muted hover:text-jarvis-text transition-colors">
            Re-check
          </button>
        </div>
        {axGranted === false && (
          <p className="text-xs text-jarvis-hint mb-3 leading-relaxed">
            Go to <strong className="text-jarvis-text">System Settings → Privacy & Security → Accessibility</strong> and enable Jarvis Dictation.
          </p>
        )}
        <button onClick={openAxSettings}
          className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors">
          Open Accessibility Settings
        </button>
      </Card>

      <Card title="Wake Word">
        <Toggle
          checked={settings.wake_enabled}
          onChange={(v) => updateSetting("wake_enabled", v)}
          label="Hey Jarvis Wake Word"
          description="Say 'Hey Jarvis' to start recording hands-free"
        />
      </Card>

      <Card title="Launch at Login">
        <Toggle
          checked={launchAtLogin}
          onChange={toggleLaunchAtLogin}
          label="Start at Login"
          description={lalBusy ? "Updating…" : "Automatically launch Quill when you log in to macOS"}
        />
      </Card>

      <Card title="Microphone Diagnostics">
        <p className="text-xs text-jarvis-hint mb-3">
          Configured device index: <span className="text-jarvis-text font-medium">{settings.mic_device ?? "default"}</span>
        </p>
        <div className="flex gap-2 mb-3">
          <button
            onClick={runListMics}
            disabled={micBusy}
            className="px-4 py-2 bg-jarvis-sidebar border border-jarvis-border rounded-lg text-sm font-medium text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors disabled:opacity-50"
          >
            List Microphones
          </button>
          <button
            onClick={runTestMic}
            disabled={micBusy}
            className="px-4 py-2 bg-jarvis-sidebar border border-jarvis-border rounded-lg text-sm font-medium text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors disabled:opacity-50"
          >
            Test Microphone
          </button>
        </div>

        {micList && (
          <div className="mb-3">
            {micList.ok ? (
              <>
                {!micList.selected_exists && micList.selected !== null && (
                  <p className="text-xs text-red-400 mb-2">
                    Device index {micList.selected} not found — select a valid device below.
                  </p>
                )}
                <div className="flex flex-col gap-1 mb-2">
                  {(micList.devices ?? []).map((d) => {
                    const isActive = settings.mic_device === d.index;
                    return (
                      <div key={d.index} className={`flex items-center justify-between px-2 py-1.5 rounded ${isActive ? "bg-jarvis-accent/15" : "bg-jarvis-surface"}`}>
                        <span className={`text-xs font-mono ${isActive ? "text-jarvis-text" : "text-jarvis-muted"}`}>
                          [{d.index}] {d.name} ({d.default_sample_rate} Hz)
                        </span>
                        {!isActive && (
                          <button
                            onClick={() => { updateSetting("mic_device", d.index); saveSettings(); }}
                            className="text-xs text-jarvis-accent hover:text-jarvis-accent-hover ml-3 shrink-0"
                          >
                            Use
                          </button>
                        )}
                        {isActive && <span className="text-xs text-jarvis-accent ml-3">✓ active</span>}
                      </div>
                    );
                  })}
                  {(micList.devices ?? []).length === 0 && (
                    <p className="text-xs text-red-400">No input devices found.</p>
                  )}
                </div>
                {settings.mic_device !== null && (
                  <button
                    onClick={() => { updateSetting("mic_device", null); saveSettings(); }}
                    className="text-xs text-jarvis-muted hover:text-jarvis-text transition-colors"
                  >
                    Use system default
                  </button>
                )}
                {settings.mic_device === null && (
                  <span className="text-xs text-jarvis-success">Using system default mic</span>
                )}
              </>
            ) : (
              <p className="text-xs text-red-400 font-mono break-all">{micList.error}</p>
            )}
          </div>
        )}

        {micTest && (
          <div className={`text-xs px-3 py-2 rounded-lg font-mono break-all ${micTest.ok ? "bg-jarvis-success/10 text-jarvis-success" : "bg-red-500/10 text-red-400"}`}>
            {micTest.ok
              ? `OK — device ${micTest.device ?? "default"} @ ${micTest.sample_rate} Hz, read ${micTest.bytes_read} bytes`
              : `FAIL — ${micTest.error}`}
          </div>
        )}
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
