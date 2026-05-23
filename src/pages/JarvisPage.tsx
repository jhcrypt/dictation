import React, { useState, useEffect } from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import NumericStepper from "../components/ui/NumericStepper";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";

type WakeStatus = "idle" | "checking" | "listening" | "error";

export default function JarvisPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  const [wakeStatus, setWakeStatus] = useState<WakeStatus>("idle");
  const [wakeError,  setWakeError]  = useState("");

  // Sync the status badge with settings.wake_enabled.
  // Runs on mount (replacing the old one-shot effect) and whenever the value
  // changes — e.g., tray menu toggle → loadSettings() → React state update.
  // handleWakeToggle sets wakeStatus directly; this effect keeps it correct
  // when an external source (tray) changes the setting.
  useEffect(() => {
    if (settings.wake_enabled) {
      // Only promote idle/error → listening; leave "checking" alone so an
      // in-flight sidecar call isn't overwritten.
      setWakeStatus((prev) =>
        prev === "idle" || prev === "error" ? "listening" : prev
      );
    } else {
      setWakeStatus((prev) =>
        prev === "listening" || prev === "checking" ? "idle" : prev
      );
      setWakeError("");
    }
  }, [settings.wake_enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Wake toggle ─────────────────────────────────────────────────────────────

  const handleWakeToggle = async (enabled: boolean) => {
    updateSetting("wake_enabled", enabled);
    setWakeError("");

    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const { emit }   = await import("@tauri-apps/api/event");

      if (enabled) {
        setWakeStatus("checking");
        const raw  = await invoke<string>("sidecar_start_wake_listen");
        const resp = JSON.parse(raw) as { ok: boolean; status?: string; error?: string };
        if (resp.ok) {
          setWakeStatus("listening");
          // Keep the tray menu checkmark in sync.
          await emit("wake-menu-sync", true);
        } else {
          const msg = resp.error ?? "Failed to start wake listener";
          setWakeError(msg);
          setWakeStatus("error");
          updateSetting("wake_enabled", false); // revert toggle
          await emit("wake-menu-sync", false);
        }
      } else {
        setWakeStatus("idle");
        await invoke("sidecar_stop_wake_listen");
        // Keep the tray menu checkmark in sync.
        await emit("wake-menu-sync", false);
      }
    } catch (e) {
      const msg = String(e);
      setWakeError(msg);
      setWakeStatus("error");
      if (enabled) {
        updateSetting("wake_enabled", false); // revert toggle
        const { emit } = await import("@tauri-apps/api/event");
        await emit("wake-menu-sync", false);
      }
    }
  };

  // ── Status badge ─────────────────────────────────────────────────────────────

  const statusBadge = () => {
    if (wakeStatus === "checking")  return (
      <span className="flex items-center gap-1.5 text-xs text-jarvis-transcribing">
        <span className="w-2 h-2 rounded-full bg-jarvis-transcribing animate-pulse inline-block" />
        Starting…
      </span>
    );
    if (wakeStatus === "listening") return (
      <span className="flex items-center gap-1.5 text-xs text-jarvis-success">
        <span className="w-2 h-2 rounded-full bg-jarvis-success inline-block" />
        Listening
      </span>
    );
    if (wakeStatus === "error") return (
      <span className="text-xs text-red-400">Error</span>
    );
    return null;
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Jarvis</h2>
        <p className="text-sm text-jarvis-hint mt-1">Wake word and voice command settings.</p>
      </div>

      <Card title="Wake Word">
        {/* Wake word toggle + live status */}
        <div className="flex items-center justify-between">
          <div className="flex-1">
            <Toggle
              checked={settings.wake_enabled}
              onChange={handleWakeToggle}
              label="Wake word"
              description="Say 'Hey Jarvis' to start recording"
            />
          </div>
          <div className="ml-4 shrink-0">{statusBadge()}</div>
        </div>

        {/* Inline error */}
        {wakeStatus === "error" && wakeError && (
          <div className="mt-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30">
            <p className="text-xs text-red-400 leading-relaxed font-mono break-all">{wakeError}</p>
            {wakeError.includes("openwakeword") && (
              <p className="text-xs text-jarvis-muted mt-1">
                Install with:{" "}
                <code className="text-jarvis-text">pip install openwakeword</code>
                {" "}in the dictation environment.
              </p>
            )}
          </div>
        )}

        <div className="border-t border-jarvis-border my-1" />

        {/* Jarvis commands toggle (future feature — no sidecar hook yet) */}
        <Toggle
          checked={settings.jarvis_enabled}
          onChange={(v) => updateSetting("jarvis_enabled", v)}
          label="Jarvis commands"
          description="Recognize and execute voice commands — coming in a future update"
        />
      </Card>

      <Card title="Wake Dictation Timing">
        <p className="text-xs text-jarvis-hint mb-3">
          Fine-tune how long Jarvis waits before and after your speech.
        </p>
        <div className="flex items-center justify-between gap-4 py-2">
          <div>
            <div className="text-sm font-medium text-jarvis-text">Grace period</div>
            <div className="text-xs text-jarvis-hint mt-0.5">Seconds to wait after wake word before recording starts</div>
          </div>
          <NumericStepper
            value={settings.wake_dictation_grace_seconds}
            min={0.5} max={10} step={0.5}
            onChange={(v) => updateSetting("wake_dictation_grace_seconds", v)}
          />
        </div>
        <div className="border-t border-jarvis-border my-1" />
        <div className="flex items-center justify-between gap-4 py-2">
          <div>
            <div className="text-sm font-medium text-jarvis-text">Silence cutoff</div>
            <div className="text-xs text-jarvis-hint mt-0.5">Seconds of silence before recording auto-stops</div>
          </div>
          <NumericStepper
            value={settings.wake_dictation_silence_seconds}
            min={0.5} max={15} step={0.5}
            onChange={(v) => updateSetting("wake_dictation_silence_seconds", v)}
          />
        </div>
        <div className="border-t border-jarvis-border my-1" />
        <div className="flex items-center justify-between gap-4 py-2">
          <div>
            <div className="text-sm font-medium text-jarvis-text">Max recording length</div>
            <div className="text-xs text-jarvis-hint mt-0.5">Hard cap in seconds for a single wake dictation</div>
          </div>
          <NumericStepper
            value={settings.wake_dictation_max_seconds}
            min={10} max={300} step={5}
            onChange={(v) => updateSetting("wake_dictation_max_seconds", v)}
          />
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
