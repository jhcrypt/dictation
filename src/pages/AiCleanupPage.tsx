import React from "react";
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

export default function AiCleanupPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">AI Cleanup</h2>
        <p className="text-sm text-jarvis-muted mt-1">Configure Ollama AI cleanup and correction strength.</p>
      </div>

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
