import React, { useState } from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";

export default function CloudPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();
  const [showKey, setShowKey] = useState(false);

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Cloud</h2>
        <p className="text-sm text-jarvis-muted mt-1">Use OpenAI Whisper API instead of local transcription.</p>
      </div>

      <Card title="Cloud Mode">
        <Toggle
          checked={settings.cloud_mode}
          onChange={(v) => updateSetting("cloud_mode", v)}
          label="Cloud mode"
          description="Use OpenAI Whisper API instead of local model"
        />
      </Card>

      <Card title="OpenAI API Key">
        <p className="text-xs text-jarvis-muted mb-3">
          Required for cloud mode. Get your key at platform.openai.com.
        </p>
        <div className="flex gap-2">
          <input
            type={showKey ? "text" : "password"}
            placeholder="sk-..."
            value={settings.openai_key}
            onChange={(e) => updateSetting("openai_key", e.target.value)}
            className="flex-1 bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted font-mono"
          />
          <button
            onClick={() => setShowKey((v) => !v)}
            className="px-3 py-2 border border-jarvis-border rounded-lg text-xs text-jarvis-muted hover:text-jarvis-text transition-colors"
          >
            {showKey ? "Hide" : "Show"}
          </button>
        </div>
      </Card>

      <Card title="Privacy">
        <div
          className="rounded-lg px-4 py-3 text-xs text-jarvis-muted leading-relaxed"
          style={{ background: "#1a3a5c" }}
        >
          <div className="text-jarvis-hint font-medium mb-1">Cloud mode privacy note</div>
          Audio is sent to OpenAI servers for transcription. Your API key and audio data are
          never shared with Quill or stored anywhere except your local settings file.
          Disable cloud mode to keep all processing fully on-device.
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
