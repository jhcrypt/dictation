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

// ── Diagnostics (additive; failures here must never affect the app) ─────────
/// Folder for diagnostic logs: ~/Library/Logs/JarvisDictation/
fn diag_dir() -> Option<std::path::PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let dir = std::path::PathBuf::from(home).join("Library").join("Logs").join("JarvisDictation");
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

/// Append one timestamped line to app.log. Silently ignores any error.
pub fn diag_log(msg: &str) {
    use std::io::Write as _;
    if let Some(dir) = diag_dir() {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("app.log")) {
            let secs = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            let _ = writeln!(f, "[{}] {}", secs, msg);
        }
    }
}

/// stderr target for the sidecar: sidecar_stderr.log if it can be opened, else null (old behavior).
fn sidecar_stderr() -> Stdio {
    if let Some(dir) = diag_dir() {
        if let Ok(f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("sidecar_stderr.log")) {
            return Stdio::from(f);
        }
    }
    Stdio::null()
}

/// Start the sidecar process.
///
/// Resolution order:
///   1. Frozen PyInstaller binary — `Contents/Helpers/jarvis-sidecar/jarvis-sidecar`
///      Stored in Contents/Helpers/ (not MacOS/) so codesign --deep does not
///      traverse _internal/*.dist-info and can sign the bundle cleanly.
///   2. Dev fallback — `~/jarvis-tauri/sidecar/jarvis_sidecar.py` run with the
///      conda Python.  Only works on the developer machine; never ships.
pub fn start_sidecar_process() -> Result<SidecarProcess, String> {
    // ── 1. Frozen binary (packaged .app) ──────────────────────────────────────
    //
    // Layout inside the .app bundle:
    //   Contents/MacOS/jarvis-dictation           ← Tauri main binary (current_exe)
    //   Contents/Resources/jarvis-sidecar/
    //     jarvis-sidecar                          ← frozen sidecar executable
    //     _internal/                              ← Python + all dylibs
    //
    // Stored in Resources/ (not MacOS/ or Helpers/) so that codesign seals the
    // sidecar's files as data resources rather than recursing into _internal/ as
    // nested code — which would choke on .dist-info and python3.11/ directories.
    //
    // Path: current_exe parent = Contents/MacOS  →  ../Resources/jarvis-sidecar/jarvis-sidecar
    let frozen_bin = std::env::current_exe()
        .ok()
        .and_then(|p| {
            p.parent()                  // Contents/MacOS
             .and_then(|d| d.parent()) // Contents
             .map(|d| d.join("Resources").join("jarvis-sidecar").join("jarvis-sidecar"))
        });

    if let Some(bin) = frozen_bin.filter(|p| p.exists()) {
        eprintln!("[sidecar] launching frozen binary: {}", bin.display());
        diag_log(&format!("launching frozen sidecar: {}", bin.display()));
        let r = spawn_sidecar_bin(&bin).map_err(|e| e.to_string());
        match &r {
            Ok(_)  => diag_log("sidecar process spawned OK"),
            Err(e) => diag_log(&format!("sidecar spawn FAILED: {}", e)),
        }
        return r;
    }

    // ── 2. Dev fallback: repo checkout + conda environment ────────────────────
    eprintln!("[sidecar] frozen binary not found — falling back to dev Python");
    diag_log(&format!("frozen sidecar NOT found (current_exe={:?}) — trying dev Python", std::env::current_exe().ok()));
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
        .ok_or_else(|| {
            "Sidecar not available: frozen binary not found and no Python discovered. \
             Build the frozen sidecar with PyInstaller or run from the developer repo."
                .to_string()
        })?;

    if !std::path::Path::new(&sidecar_script).exists() {
        return Err(format!(
            "Sidecar script not found at {}. \
             Build the frozen sidecar with PyInstaller for a packaged build.",
            sidecar_script
        ));
    }

    spawn_sidecar(python_path, &sidecar_script).map_err(|e| e.to_string())
}

/// Launch a pre-built frozen sidecar binary (no Python interpreter argument).
pub fn spawn_sidecar_bin(bin_path: &std::path::Path) -> anyhow::Result<SidecarProcess> {
    let mut child = Command::new(bin_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(sidecar_stderr())
        .spawn()?;

    let stdin  = child.stdin.take().ok_or_else(|| anyhow::anyhow!("no stdin"))?;
    let stdout = BufReader::new(child.stdout.take().ok_or_else(|| anyhow::anyhow!("no stdout"))?);

    Ok(SidecarProcess {
        child,
        python_path: bin_path.to_string_lossy().into_owned(),
        stdin,
        stdout,
    })
}

/// Launch the sidecar via a Python interpreter + script path (dev mode only).
pub fn spawn_sidecar(python_path: &str, script_path: &str) -> anyhow::Result<SidecarProcess> {
    let mut child = Command::new(python_path)
        .arg(script_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(sidecar_stderr())
        .spawn()?;

    let stdin  = child.stdin.take().ok_or_else(|| anyhow::anyhow!("no stdin"))?;
    let stdout = BufReader::new(child.stdout.take().ok_or_else(|| anyhow::anyhow!("no stdout"))?);

    Ok(SidecarProcess { child, python_path: python_path.to_string(), stdin, stdout })
}
