use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

fn home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

fn contacts_path() -> PathBuf { home().join(".dictation_contacts.json") }
fn history_path() -> PathBuf { home().join(".dictation_history.json") }
fn vocab_path() -> PathBuf { home().join(".dictation_vocabulary.json") }
fn snippets_path() -> PathBuf { home().join(".dictation_snippets.json") }
fn custom_commands_path() -> PathBuf { home().join(".dictation_custom_commands.json") }
fn log_path() -> PathBuf { home().join("jarvis_startup_debug.log") }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contact {
    pub name: String,
    pub email: String,
    #[serde(default)]
    pub aliases: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    #[serde(default)]
    pub timestamp: String,
    #[serde(default)]
    pub app: String,
    #[serde(default)]
    pub final_text: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub profile: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub whisper_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ollama_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timing: Option<serde_json::Value>,
}

pub fn load_contacts() -> Vec<Contact> {
    let path = contacts_path();
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save_contacts(contacts: &[Contact]) -> anyhow::Result<()> {
    let json = serde_json::to_string_pretty(contacts)?;
    fs::write(contacts_path(), json)?;
    Ok(())
}

pub fn load_history() -> Vec<HistoryEntry> {
    let path = history_path();
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn append_history(entry: &HistoryEntry) -> anyhow::Result<()> {
    let path = history_path();
    let mut entries: Vec<serde_json::Value> = if path.exists() {
        let raw = fs::read_to_string(&path).unwrap_or_default();
        serde_json::from_str(&raw).unwrap_or_default()
    } else {
        Vec::new()
    };
    entries.insert(0, serde_json::to_value(entry)?); // newest first
    entries.truncate(500);
    fs::write(path, serde_json::to_string_pretty(&entries)?)?;
    eprintln!("[history] saved: {:?}", &entry.final_text[..entry.final_text.len().min(50)]);
    Ok(())
}

pub fn clear_history() -> anyhow::Result<()> {
    fs::write(history_path(), "[]")?;
    Ok(())
}

pub fn clear_vocabulary() -> anyhow::Result<()> {
    fs::write(vocab_path(), "{}")?;
    Ok(())
}

/// Vocab file format: {"corrections": {"wrong": "right", ...}, "manual_vocabulary": "word\nword\n..."}
pub fn load_vocab() -> serde_json::Value {
    let path = vocab_path();
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| serde_json::json!({"corrections": {}, "manual_vocabulary": ""}))
}

pub fn save_vocab(vocab: &serde_json::Value) -> anyhow::Result<()> {
    fs::write(vocab_path(), serde_json::to_string_pretty(vocab)?)?;
    Ok(())
}

/// Snippets file format: {"trigger": "expansion", ...}
pub fn load_snippets() -> serde_json::Value {
    let path = snippets_path();
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

pub fn save_snippets(snippets: &serde_json::Value) -> anyhow::Result<()> {
    fs::write(snippets_path(), serde_json::to_string_pretty(snippets)?)?;
    Ok(())
}

/// Custom commands file format: [{"trigger": "...", "action": "open_url|open_app|type_text", "target": "..."}, ...]
pub fn load_custom_commands() -> Vec<serde_json::Value> {
    let path = custom_commands_path();
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save_custom_commands(commands: &[serde_json::Value]) -> anyhow::Result<()> {
    fs::write(custom_commands_path(), serde_json::to_string_pretty(commands)?)?;
    Ok(())
}

pub fn clear_log() -> anyhow::Result<()> {
    let path = log_path();
    if path.exists() {
        fs::write(path, "")?;
    }
    Ok(())
}
