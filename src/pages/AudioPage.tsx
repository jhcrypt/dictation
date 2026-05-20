import React from "react";
import Card from "../components/ui/Card";
import Select from "../components/ui/Select";
import Toggle from "../components/ui/Toggle";
import SaveButton from "../components/ui/SaveButton";
import { useSettings } from "../context/SettingsContext";
import type { DictationQuality, TranslateTarget } from "../types/settings";

const SPEAKING_LANGUAGES = ["Auto Detect", "English", "French", "Spanish", "German", "Italian", "Portuguese"] as const;
const TRANSLATE_OPTIONS: TranslateTarget[] = ["Off", "English", "French", "Spanish", "German", "Italian", "Portuguese"];
const QUALITY_OPTIONS: DictationQuality[] = ["Fast", "Balanced", "Accurate"];

const LANGUAGE_TO_CODE: Record<string, string> = {
  "Auto Detect": "",
  "English": "en",
  "French": "fr",
  "Spanish": "es",
  "German": "de",
  "Italian": "it",
  "Portuguese": "pt",
};

const CODE_TO_LANGUAGE: Record<string, string> = {
  "": "Auto Detect",
  "en": "English",
  "fr": "French",
  "es": "Spanish",
  "de": "German",
  "it": "Italian",
  "pt": "Portuguese",
};

const QUALITY_DESCRIPTION: Record<DictationQuality, string> = {
  Fast: "tiny model — fastest, lower accuracy",
  Balanced: "small model — good balance (recommended)",
  Accurate: "medium model — slowest, best accuracy",
};

function isEnOnlyModel(model: string): boolean {
  return model.endsWith(".en");
}

export default function AudioPage() {
  const { settings, updateSetting, saveSettings, saved } = useSettings();

  const currentLangLabel = CODE_TO_LANGUAGE[settings.language] ?? "English";
  const isAutoDetect = settings.auto_detect;

  const handleSpeakingLanguage = (label: string) => {
    if (label === "Auto Detect") {
      updateSetting("auto_detect", true);
      updateSetting("language", "");
    } else {
      updateSetting("auto_detect", false);
      updateSetting("language", LANGUAGE_TO_CODE[label] ?? "en");
    }
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Audio &amp; Language</h2>
        <p className="text-sm text-jarvis-hint mt-1">Configure microphone, speech model, and translation.</p>
      </div>

      {/* 1. Microphone */}
      <Card title="Microphone">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-jarvis-text">Device index: <span className="font-medium">{settings.mic_device}</span></p>
            <p className="text-xs text-jarvis-muted mt-0.5">Sample rate: {settings.sample_rate} Hz</p>
          </div>
          <span className="text-xs text-jarvis-muted bg-jarvis-surface px-2 py-1 rounded-lg">Picker coming soon</span>
        </div>
      </Card>

      {/* 2. I'm Speaking (input language) */}
      <Card title="I'm Speaking">
        <p className="text-xs text-jarvis-hint mb-3">
          The language you speak into the microphone. Auto Detect works well for most users.
        </p>
        <div className="flex flex-wrap gap-2">
          {SPEAKING_LANGUAGES.map((lang) => {
            const active = lang === "Auto Detect" ? isAutoDetect : (!isAutoDetect && currentLangLabel === lang);
            return (
              <button
                key={lang}
                onClick={() => handleSpeakingLanguage(lang)}
                className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                  active
                    ? "bg-jarvis-accent border-jarvis-accent text-white"
                    : "bg-jarvis-sidebar border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted"
                }`}
              >
                {lang}
              </button>
            );
          })}
        </div>
      </Card>

      {/* 3. Dictation Quality */}
      <Card title="Dictation Quality">
        <div className="flex flex-col gap-2">
          {QUALITY_OPTIONS.map((q) => (
            <button
              key={q}
              onClick={() => updateSetting("dictation_quality", q)}
              className={`flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors ${
                settings.dictation_quality === q
                  ? "bg-jarvis-accent/15 border-jarvis-accent"
                  : "bg-jarvis-sidebar border-jarvis-border hover:border-jarvis-muted"
              }`}
            >
              <span className={`text-sm font-medium ${settings.dictation_quality === q ? "text-jarvis-text" : "text-jarvis-muted"}`}>
                {q}
              </span>
              <span className="text-xs text-jarvis-muted">{QUALITY_DESCRIPTION[q]}</span>
            </button>
          ))}
        </div>
      </Card>

      {/* 4. Advanced Speech Model */}
      <Card title="Advanced Speech Model">
        <p className="text-xs text-jarvis-hint mb-2">
          Optional override. Leave blank to use the model set by Dictation Quality above.
        </p>
        <input
          type="text"
          value={settings.model}
          onChange={(e) => updateSetting("model", e.target.value)}
          placeholder="e.g. large-v3, distil-large-v3"
          className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
        />
        {isEnOnlyModel(settings.model) && !isAutoDetect && settings.language !== "en" && (
          <p className="text-xs text-jarvis-recording mt-2">
            Warning: .en models only support English. Switch to a multilingual model.
          </p>
        )}
      </Card>

      {/* 5. Translate My Dictation To */}
      <Card title="Translate My Dictation To">
        <p className="text-xs text-jarvis-hint mb-3">
          Translate the output of every dictation to another language. Set to Off to disable.
        </p>
        <Select<TranslateTarget>
          value={settings.translate_my_dictation}
          options={TRANSLATE_OPTIONS}
          onChange={(v) => updateSetting("translate_my_dictation", v)}
        />
      </Card>

      {/* 6. Translate Selected Text To */}
      <Card title="Translate Selected Text To">
        <p className="text-xs text-jarvis-hint mb-3">
          Target language when you say "translate that" or "translate selected text".
          This is separate from Translate My Dictation.
        </p>
        <Select<TranslateTarget>
          value={settings.translate_target_language}
          options={TRANSLATE_OPTIONS.filter((v) => v !== "Off")}
          onChange={(v) => updateSetting("translate_target_language", v)}
        />
      </Card>

      {/* 7. How language settings work */}
      <Card title="How Language Settings Work">
        <div className="text-xs text-jarvis-hint leading-relaxed space-y-2">
          <p><span className="text-jarvis-text font-medium">I'm Speaking</span> — the language you speak. Controls which Whisper model is used and how auto-detect works.</p>
          <p><span className="text-jarvis-text font-medium">Translate My Dictation</span> — every dictation output is translated to this language before pasting. Use when you speak one language but write in another.</p>
          <p><span className="text-jarvis-text font-medium">Translate Selected Text</span> — triggered by voice command only. Translates whatever is in the clipboard.</p>
          <p><span className="text-jarvis-text font-medium">Dictation Quality</span> — selects the Whisper model size. Advanced Speech Model overrides this.</p>
        </div>
      </Card>

      {/* 8. Restart card */}
      <Card title="Apply Changes">
        <p className="text-xs text-jarvis-hint mb-3">
          Audio and model changes take effect after saving and restarting the dictation engine.
        </p>
        <div className="flex gap-2">
          <SaveButton onClick={saveSettings} saved={saved} />
          <button
            onClick={async () => {
              await saveSettings();
              try {
                const { invoke } = await import("@tauri-apps/api/core");
                await invoke("restart_engine");
              } catch { /* not in Tauri */ }
            }}
            className="px-5 py-2 rounded-lg text-sm font-semibold bg-jarvis-sidebar border border-jarvis-border text-jarvis-muted hover:text-jarvis-text hover:border-jarvis-muted transition-colors"
          >
            Save &amp; Restart Engine
          </button>
        </div>
      </Card>
    </div>
  );
}
