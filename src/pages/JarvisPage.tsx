// FUTURE SIDECAR FEATURE GAP
// Jarvis settings (wake_enabled, jarvis_enabled, timing values) are saved to
// ~/.dictation_settings.json and are readable by the stable Python Quill app.
// However, the Tauri sidecar (jarvis_sidecar.py) does NOT yet implement
// continuous wake-word listening or voice command dispatch.
// Until the sidecar gains a "start_wake_listen" / "stop_wake_listen" action,
// these settings have no effect on Tauri dictation behavior.
import React from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";

export default function JarvisPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Jarvis</h2>
        <p className="text-sm text-jarvis-muted mt-1">Wake word and voice command settings.</p>
      </div>

      <Card title="Wake Word">
        <div className="flex flex-col gap-3">
          <Toggle
            checked={settings.wake_enabled}
            onChange={(v) => updateSetting("wake_enabled", v)}
            label="Wake word"
            description="Say 'Hey Jarvis' to start recording"
          />
          <div className="border-t border-jarvis-border" />
          <Toggle
            checked={settings.jarvis_enabled}
            onChange={(v) => updateSetting("jarvis_enabled", v)}
            label="Jarvis commands"
            description="Recognize and execute voice commands like 'open Safari'"
          />
        </div>
      </Card>

      <Card title="Wake Dictation Timing">
        <p className="text-xs text-jarvis-muted mb-4">
          Fine-tune how long Jarvis waits before and after your speech.
        </p>
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-jarvis-text">Grace period</div>
              <div className="text-xs text-jarvis-muted mt-0.5">Seconds to wait after wake word before recording starts</div>
            </div>
            <input
              type="number"
              min={0.5}
              max={10}
              step={0.5}
              value={settings.wake_dictation_grace_seconds}
              onChange={(e) => updateSetting("wake_dictation_grace_seconds", parseFloat(e.target.value))}
              className="w-20 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-1.5 text-sm text-jarvis-text text-center focus:outline-none focus:border-jarvis-accent"
            />
          </div>

          <div className="border-t border-jarvis-border" />

          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-jarvis-text">Silence cutoff</div>
              <div className="text-xs text-jarvis-muted mt-0.5">Seconds of silence before recording auto-stops</div>
            </div>
            <input
              type="number"
              min={0.5}
              max={15}
              step={0.5}
              value={settings.wake_dictation_silence_seconds}
              onChange={(e) => updateSetting("wake_dictation_silence_seconds", parseFloat(e.target.value))}
              className="w-20 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-1.5 text-sm text-jarvis-text text-center focus:outline-none focus:border-jarvis-accent"
            />
          </div>

          <div className="border-t border-jarvis-border" />

          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-jarvis-text">Max recording length</div>
              <div className="text-xs text-jarvis-muted mt-0.5">Hard cap in seconds for a single wake dictation</div>
            </div>
            <input
              type="number"
              min={10}
              max={300}
              step={5}
              value={settings.wake_dictation_max_seconds}
              onChange={(e) => updateSetting("wake_dictation_max_seconds", parseFloat(e.target.value))}
              className="w-20 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-1.5 text-sm text-jarvis-text text-center focus:outline-none focus:border-jarvis-accent"
            />
          </div>
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
