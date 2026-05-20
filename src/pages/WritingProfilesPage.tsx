import React from "react";
import Card from "../components/ui/Card";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";
import type { WritingProfile } from "../types/settings";

const PROFILES: WritingProfile[] = [
  "General", "Professional", "Email", "Developer",
  "Medical", "Legal", "Sales", "Notes", "Creative", "Verbatim",
];

const PROFILE_DESC: Record<WritingProfile, string> = {
  General:      "Everyday dictation — balanced and natural",
  Professional: "Formal tone, polished grammar",
  Email:        "Email-ready — greeting, body, sign-off structure",
  Developer:    "Code-friendly — preserves identifiers and technical terms",
  Medical:      "Clinical language, anatomical terms",
  Legal:        "Precise legal phrasing and citations",
  Sales:        "Persuasive, client-focused tone",
  Notes:        "Short-form, minimal punctuation, quick capture",
  Creative:     "Expressive — preserves voice, minimal correction",
  Verbatim:     "Exact transcription — no cleanup at all",
};

export default function WritingProfilesPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Writing Profiles</h2>
        <p className="text-sm text-jarvis-hint mt-1">Profile adjusts how Ollama formats and phrases the output.</p>
      </div>

      <Card title="Active Profile">
        <div className="flex flex-col gap-2">
          {PROFILES.map((p) => (
            <button
              key={p}
              onClick={() => updateSetting("writing_profile", p)}
              className={`flex items-center justify-between px-4 py-2.5 rounded-lg border text-left transition-colors ${
                settings.writing_profile === p
                  ? "bg-jarvis-accent/10 border-jarvis-accent"
                  : "bg-jarvis-surface border-jarvis-border hover:border-jarvis-muted"
              }`}
            >
              <span className={`text-sm font-medium ${settings.writing_profile === p ? "text-jarvis-text" : "text-jarvis-muted"}`}>
                {p}
              </span>
              <span className="text-xs text-jarvis-muted">{PROFILE_DESC[p]}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card title="Profile Detection">
        <div className="flex flex-col gap-3">
          <Toggle
            checked={settings.auto_profile_detection}
            onChange={(v) => updateSetting("auto_profile_detection", v)}
            label="Auto-detect profile from app"
            description="Switches to Email when Spark/Mail is frontmost, etc."
          />
          <div className="border-t border-jarvis-border" />
          <Toggle
            checked={settings.show_active_profile}
            onChange={(v) => updateSetting("show_active_profile", v)}
            label="Show active profile in HUD"
          />
        </div>
      </Card>

      <div className="flex justify-end">
        <SaveButton onClick={saveSettings} saved={saved} />
      </div>
    </div>
  );
}
