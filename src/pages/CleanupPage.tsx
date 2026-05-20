import React from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";
import type { AiCleanupMode, CorrectionStrength, WritingProfile } from "../types/settings";

const PROFILES: WritingProfile[] = ["General", "Professional", "Email", "Developer", "Medical", "Legal", "Sales", "Notes", "Creative", "Verbatim"];
const STRENGTHS: CorrectionStrength[] = ["Light", "Standard", "Strong", "Off"];
const STRENGTH_DESC: Record<CorrectionStrength, string> = {
  Light:    "Light touch — fix only obvious errors",
  Standard: "Balanced cleanup — recommended",
  Strong:   "Thorough rewrite — may change phrasing",
  Off:      "No corrections applied",
};

export default function CleanupPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Writing Cleanup</h2>
        <p className="text-sm text-jarvis-hint mt-1">Configure Ollama AI cleanup and writing profiles.</p>
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
          {settings.ai_cleanup_mode === "on" && "Always runs Ollama on every dictation."}
          {settings.ai_cleanup_mode === "off" && "Raw Whisper output only — no AI cleanup."}
        </div>
        <div className="mt-3">
          <Toggle
            checked={settings.use_ollama}
            onChange={(v) => updateSetting("use_ollama", v)}
            label="Enable Ollama"
            description="Requires Ollama running locally"
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
                  ? "bg-jarvis-accent/15 border-jarvis-accent"
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

      <Card title="Writing Profile">
        <p className="text-xs text-jarvis-muted mb-3">
          Profile adjusts how Ollama formats and phrases the output.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          {PROFILES.map((p) => (
            <button
              key={p}
              onClick={() => updateSetting("writing_profile", p)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                settings.writing_profile === p
                  ? "bg-jarvis-accent border-jarvis-accent text-white"
                  : "bg-jarvis-surface border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <Toggle
          checked={settings.auto_profile_detection}
          onChange={(v) => updateSetting("auto_profile_detection", v)}
          label="Auto-detect profile from app"
          description="Switches to Email when Spark/Mail is frontmost, etc."
        />
        <div className="border-t border-jarvis-border my-1" />
        <Toggle
          checked={settings.show_active_profile}
          onChange={(v) => updateSetting("show_active_profile", v)}
          label="Show active profile in HUD"
        />
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
