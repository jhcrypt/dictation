use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

fn settings_path() -> PathBuf {
    dirs_next().join(".dictation_settings.json")
}

fn dirs_next() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    // ── Transcription engine ──────────────────────────────────────────────────
    #[serde(default = "default_transcription_engine")]
    pub transcription_engine: String,
    #[serde(default = "default_transcription_provider")]
    pub transcription_provider: String,
    #[serde(default = "default_local_model")]
    pub local_model: String,
    #[serde(default = "default_cleanup_provider")]
    pub cleanup_provider: String,
    // Legacy fields — kept for migration only; openai_key no longer written back
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cloud_mode: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub openai_key: Option<String>,
    // ── Audio / hardware ──────────────────────────────────────────────────────
    #[serde(default = "default_model")]
    pub model: String,
    #[serde(default)]
    pub mic_device: Option<u32>,
    #[serde(default)]
    pub mic_device_name: String,
    #[serde(default = "default_sample_rate")]
    pub sample_rate: u32,
    #[serde(default = "default_hotkey")]
    pub hotkey_label: String,
    #[serde(default = "default_true")]
    pub show_hud: bool,
    #[serde(default = "default_true")]
    pub toggle_mode: bool,
    #[serde(default = "default_true")]
    pub context_format: bool,
    #[serde(default = "default_true")]
    pub auto_detect: bool,
    #[serde(default = "default_true")]
    pub jarvis_enabled: bool,
    #[serde(default = "default_true")]
    pub use_ollama: bool,
    #[serde(default = "default_true")]
    pub play_sounds: bool,
    #[serde(default = "default_true")]
    pub show_startup_tips: bool,
    #[serde(default)]
    pub first_run_complete: bool,
    #[serde(default)]
    pub onboarding_shown_version: String,
    #[serde(default = "default_min_record")]
    pub min_record_seconds: f64,
    #[serde(default = "default_debounce")]
    pub hotkey_debounce_seconds: f64,
    #[serde(default)]
    pub safe_mode: bool,
    #[serde(default = "default_ai_cleanup_mode")]
    pub ai_cleanup_mode: String,
    #[serde(default = "default_correction_strength")]
    pub correction_strength: String,
    #[serde(default = "default_writing_profile")]
    pub writing_profile: String,
    #[serde(default = "default_true")]
    pub auto_profile_detection: bool,
    #[serde(default = "default_true")]
    pub show_active_profile: bool,
    #[serde(default = "default_true")]
    pub wake_enabled: bool,
    #[serde(default = "default_wake_grace")]
    pub wake_dictation_grace_seconds: f64,
    #[serde(default = "default_wake_silence")]
    pub wake_dictation_silence_seconds: f64,
    #[serde(default = "default_wake_max")]
    pub wake_dictation_max_seconds: f64,
    #[serde(default = "default_wake_rms")]
    pub wake_dictation_silence_rms: f64,
    #[serde(default = "default_translate_off")]
    pub translate_my_dictation: String,
    #[serde(default = "default_quality")]
    pub dictation_quality: String,
    #[serde(default)]
    pub debug_logging: bool,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default = "default_translate_target")]
    pub translate_target_language: String,
    #[serde(default)]
    pub manual_vocabulary: String,
    #[serde(default = "default_assistant_name")]
    pub assistant_name: String,
    #[serde(default = "default_hud_x")]
    pub hud_x: i32,
    #[serde(default)]
    pub hud_y: i32,
}

fn default_transcription_engine()   -> String { "local".into() }
fn default_transcription_provider() -> String { "openai".into() }
fn default_local_model()            -> String { "small.en".into() }
fn default_cleanup_provider()       -> String { "ollama".into() }
fn default_model() -> String { "small.en".into() }
fn default_sample_rate() -> u32 { 48000 }
fn default_hotkey() -> String { "Right Option".into() }
fn default_true() -> bool { true }
fn default_min_record() -> f64 { 0.3 }
fn default_debounce() -> f64 { 0.18 }
fn default_ai_cleanup_mode() -> String { "auto".into() }
fn default_correction_strength() -> String { "Standard".into() }
fn default_writing_profile() -> String { "General".into() }
fn default_wake_grace() -> f64 { 3.5 }
fn default_wake_silence() -> f64 { 2.5 }
fn default_wake_max() -> f64 { 45.0 }
fn default_wake_rms() -> f64 { 0.025 }
fn default_translate_off() -> String { "Off".into() }
fn default_quality() -> String { "Balanced".into() }
fn default_language() -> String { "en".into() }
fn default_translate_target() -> String { "English".into() }
fn default_assistant_name() -> String { "Jarvis".into() }
fn default_hud_x() -> i32 { 606 }

impl Default for Settings {
    fn default() -> Self {
        serde_json::from_str("{}").unwrap()
    }
}

pub fn load() -> Settings {
    let path = settings_path();
    if let Ok(data) = fs::read_to_string(&path) {
        if let Ok(mut s) = serde_json::from_str::<serde_json::Value>(&data) {
            // Merge defaults for missing keys
            let defaults: serde_json::Value = serde_json::to_value(Settings::default()).unwrap();
            if let (Some(obj), Some(def_obj)) = (s.as_object_mut(), defaults.as_object()) {
                for (k, v) in def_obj {
                    obj.entry(k).or_insert_with(|| v.clone());
                }
            }
            if let Ok(settings) = serde_json::from_value(s) {
                return settings;
            }
        }
    }
    Settings::default()
}

pub fn save(settings: &Settings) -> anyhow::Result<()> {
    let path = settings_path();
    let json = serde_json::to_string_pretty(settings)?;
    fs::write(path, json)?;
    Ok(())
}
