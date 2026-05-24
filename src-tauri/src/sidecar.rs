use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::{Arc, Mutex};

#[derive(Debug, Serialize, Deserialize)]
pub struct SidecarCommand {
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscribeResult {
    pub ok: bool,
    // Option<String> so sidecar "text": null for action commands doesn't fail deserialization.
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub timing: TranscribeTiming,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub profile: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub skipped_cleanup: Option<bool>,
    #[serde(default)]
    pub skip_reason: Option<String>,
    // Voice command fields — absent for plain-text results, present for action commands.
    #[serde(default)]
    pub action: Option<String>,
    #[serde(default)]
    pub backspace_count: Option<u32>,
    #[serde(default)]
    pub key: Option<String>,
    #[serde(default)]
    pub with_shift: Option<bool>,
    #[serde(default)]
    pub repeat: Option<u32>,
    #[serde(default)]
    pub modifier: Option<String>,
    #[serde(default)]
    pub nav_target: Option<String>,
    #[serde(default)]
    pub app_name: Option<String>,
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default)]
    pub direction: Option<String>,
    #[serde(default)]
    pub level: Option<u32>,
    #[serde(default)]
    pub screenshot_type: Option<String>,
    #[serde(default)]
    pub force: Option<bool>,
    #[serde(default)]
    pub hud: Option<String>,
    #[serde(default)]
    pub hud_color: Option<String>,
    #[serde(default)]
    pub whisper_text: Option<String>,
    #[serde(default)]
    pub ollama_text: Option<String>,
    #[serde(default)]
    pub active_app: Option<String>,
    /// True = safety filter passed, False = rejected, None = cleanup was skipped
    #[serde(default)]
    pub ollama_accepted: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TranscribeTiming {
    pub whisper: u64,
    pub ollama: u64,
    pub total: u64,
}

pub struct SidecarProcess {
    pub child: Child,
    pub python_path: String,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl SidecarProcess {
    pub fn pid(&self) -> u32 { self.child.id() }

    pub fn send(&mut self, action: &str) -> anyhow::Result<serde_json::Value> {
        let cmd = serde_json::json!({ "action": action });
        self.send_value(cmd)
    }

    pub fn send_value(&mut self, cmd: serde_json::Value) -> anyhow::Result<serde_json::Value> {
        writeln!(self.stdin, "{}", cmd)?;
        self.stdin.flush()?;
        let mut line = String::new();
        self.stdout.read_line(&mut line)?;
        let v: serde_json::Value = serde_json::from_str(line.trim())?;
        Ok(v)
    }

    pub fn kill(&mut self) {
        let _ = self.child.kill();
    }
}

/// Shared, cloneable mutex so the wake-poll thread can hold a reference
/// without going through Tauri's state system from another thread.
pub struct SidecarState(pub Arc<Mutex<Option<SidecarProcess>>>);

impl SidecarState {
    pub fn new() -> Self {
        SidecarState(Arc::new(Mutex::new(None)))
    }
}

pub fn start_sidecar_process() -> Result<SidecarProcess, String> {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let python_candidates = [
        format!("{}/miniconda3/envs/dictation/bin/python", home),
        format!("{}/miniconda3/bin/python", home),
        "/usr/local/bin/python3".to_string(),
        "/usr/bin/python3".to_string(),
    ];
    let sidecar_script = format!("{}/jarvis-tauri/sidecar/jarvis_sidecar.py", home);

    let python_path = python_candidates
        .iter()
        .find(|p| std::path::Path::new(p).exists())
        .ok_or_else(|| "No Python found".to_string())?;

    if !std::path::Path::new(&sidecar_script).exists() {
        return Err(format!("Sidecar script not found: {}", sidecar_script));
    }

    spawn_sidecar(python_path, &sidecar_script).map_err(|e| e.to_string())
}

pub fn spawn_sidecar(python_path: &str, script_path: &str) -> anyhow::Result<SidecarProcess> {
    let mut child = Command::new(python_path)
        .arg(script_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;

    let stdin = child.stdin.take().ok_or_else(|| anyhow::anyhow!("no stdin"))?;
    let stdout = BufReader::new(child.stdout.take().ok_or_else(|| anyhow::anyhow!("no stdout"))?);

    Ok(SidecarProcess { child, python_path: python_path.to_string(), stdin, stdout })
}
