export type DictationQuality = "Fast" | "Balanced" | "Accurate";
export type Language = "Auto Detect" | "English" | "French" | "Spanish" | "German" | "Italian" | "Portuguese";
export type TranslateTarget = "Off" | "English" | "French" | "Spanish" | "German" | "Italian" | "Portuguese";
export type AiCleanupMode = "auto" | "on" | "off";
export type CorrectionStrength = "Light" | "Standard" | "Strong" | "Off";
export type WritingProfile = "General" | "Professional" | "Email" | "Developer" | "Medical" | "Legal" | "Sales" | "Notes" | "Creative" | "Verbatim";
export type HotkeyLabel = "Right Option" | "F13" | "F14" | "F15";

// ── Transcription engine / provider ──────────────────────────────────────────
export type TranscriptionEngine   = "local" | "cloud";
export type TranscriptionProvider = "openai";          // Phase 1 only; future: "deepgram" etc.
export type CleanupProvider = "off" | "ollama";        // future: "claude", "groq" etc.
// Local Whisper model is owned by Audio & Language (dictation_quality + model fields).
// Do not add a separate local_model field here — use dictation_quality as the source of truth.

export interface Settings {
  // ── Transcription engine ─────────────────────────────────────────────────
  transcription_engine:   TranscriptionEngine;
  transcription_provider: TranscriptionProvider;
  cleanup_provider:       CleanupProvider;
  // Local Whisper model → use dictation_quality (AudioPage) + model override (AudioPage).
  // ── Legacy (kept for migration path only — do not write new code against these) ──
  /** @deprecated use transcription_engine instead */
  cloud_mode?: boolean;
  // openai_key is intentionally absent — key is stored in macOS Keychain only.
  // Do not add openai_key here; it must never appear in the save payload.
  // ── Audio / hardware ─────────────────────────────────────────────────────
  model: string;
  mic_device: number | null;
  mic_device_name: string;
  sample_rate: number;
  hotkey_label: HotkeyLabel;
  show_hud: boolean;
  toggle_mode: boolean;
  context_format: boolean;
  auto_detect: boolean;
  jarvis_enabled: boolean;
  use_ollama: boolean;
  play_sounds: boolean;
  show_startup_tips: boolean;
  first_run_complete: boolean;
  onboarding_shown_version: string;
  min_record_seconds: number;
  hotkey_debounce_seconds: number;
  safe_mode: boolean;
  ai_cleanup_mode: AiCleanupMode;
  correction_strength: CorrectionStrength;
  writing_profile: WritingProfile;
  auto_profile_detection: boolean;
  show_active_profile: boolean;
  wake_enabled: boolean;
  wake_dictation_grace_seconds: number;
  wake_dictation_silence_seconds: number;
  wake_dictation_max_seconds: number;
  wake_dictation_silence_rms: number;
  translate_my_dictation: TranslateTarget;
  translate_target_language: TranslateTarget;
  dictation_quality: DictationQuality;
  debug_logging: boolean;
  language: string;
  manual_vocabulary: string;
  assistant_name: string;
  hud_x: number;
  hud_y: number;
}

export const DEFAULT_SETTINGS: Settings = {
  // Transcription engine
  transcription_engine:   "local",
  transcription_provider: "openai",
  cleanup_provider:       "ollama",
  // Audio / hardware
  model: "small.en",
  mic_device: null,
  mic_device_name: "",
  sample_rate: 48000,
  hotkey_label: "Right Option",
  show_hud: true,
  toggle_mode: true,
  context_format: true,
  auto_detect: true,
  jarvis_enabled: true,
  use_ollama: true,
  play_sounds: true,
  show_startup_tips: true,
  first_run_complete: false,
  onboarding_shown_version: "",
  min_record_seconds: 0.3,
  hotkey_debounce_seconds: 0.18,
  safe_mode: false,
  ai_cleanup_mode: "auto",
  correction_strength: "Standard",
  writing_profile: "General",
  auto_profile_detection: true,
  show_active_profile: true,
  wake_enabled: true,
  wake_dictation_grace_seconds: 3.5,
  wake_dictation_silence_seconds: 2.5,
  wake_dictation_max_seconds: 45.0,
  wake_dictation_silence_rms: 0.025,
  translate_my_dictation: "Off",
  translate_target_language: "English",
  dictation_quality: "Balanced",
  debug_logging: false,
  language: "en",
  manual_vocabulary: "",
  assistant_name: "Jarvis",
  hud_x: 606,
  hud_y: 0,
};

export interface Contact {
  name: string;
  email: string;
  aliases: string;
}

export interface CustomCommand {
  trigger: string;
  action: "open_url" | "open_app" | "type_text";
  target: string;
}

export interface HistoryEntry {
  timestamp: string;
  app: string;
  final_text: string;
  status: string;
  profile: string;
  whisper_text?: string;
  ollama_text?: string;
}
