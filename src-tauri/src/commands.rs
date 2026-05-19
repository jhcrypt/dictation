use crate::data::{self, Contact, HistoryEntry};
use arboard;
use crate::focus::{LastTargetApp, activate_app};
use crate::settings::{self, Settings};
use crate::sidecar::{SidecarState, TranscribeResult, spawn_sidecar};
use tauri::State;
use serde_json::json;

// ── Settings commands ─────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_settings() -> Settings {
    settings::load()
}

#[tauri::command]
pub fn save_settings(settings: Settings) -> Result<(), String> {
    settings::save(&settings).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn reset_settings() -> Settings {
    Settings::default()
}

// ── Contacts commands ─────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_contacts() -> Vec<Contact> {
    data::load_contacts()
}

#[tauri::command]
pub fn save_contacts(contacts: Vec<Contact>) -> Result<(), String> {
    data::save_contacts(&contacts).map_err(|e| e.to_string())
}

// ── History commands ──────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_history() -> Vec<HistoryEntry> {
    data::load_history()
}

#[tauri::command]
pub fn clear_history() -> Result<(), String> {
    data::clear_history().map_err(|e| e.to_string())
}

// ── Vocabulary commands ───────────────────────────────────────────────────────

#[tauri::command]
pub fn load_vocab() -> serde_json::Value {
    data::load_vocab()
}

#[tauri::command]
pub fn save_vocab(vocab: serde_json::Value) -> Result<(), String> {
    data::save_vocab(&vocab).map_err(|e| e.to_string())
}

// ── Snippets commands ─────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_snippets() -> serde_json::Value {
    data::load_snippets()
}

#[tauri::command]
pub fn save_snippets(snippets: serde_json::Value) -> Result<(), String> {
    data::save_snippets(&snippets).map_err(|e| e.to_string())
}

// ── Custom commands ───────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_custom_commands() -> Vec<serde_json::Value> {
    data::load_custom_commands()
}

#[tauri::command]
pub fn save_custom_commands(commands: Vec<serde_json::Value>) -> Result<(), String> {
    data::save_custom_commands(&commands).map_err(|e| e.to_string())
}

// ── Storage cleanup ───────────────────────────────────────────────────────────

#[tauri::command]
pub fn clear_vocabulary() -> Result<(), String> {
    data::clear_vocabulary().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn clear_log() -> Result<(), String> {
    data::clear_log().map_err(|e| e.to_string())
}

// ── Sidecar commands ──────────────────────────────────────────────────────────

#[tauri::command]
pub fn sidecar_start(state: State<SidecarState>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;

    // Find Python and sidecar script
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

    let proc = spawn_sidecar(python_path, &sidecar_script).map_err(|e| e.to_string())?;
    *guard = Some(proc);
    Ok("started".into())
}

#[tauri::command]
pub fn sidecar_ping(state: State<SidecarState>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let resp = proc.send("ping").map_err(|e| e.to_string())?;
    Ok(resp.to_string())
}

#[tauri::command]
pub fn sidecar_start_recording(state: State<SidecarState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let resp = proc.send("start_recording").map_err(|e| e.to_string())?;
    if resp.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        let msg = resp.get("error").and_then(|v| v.as_str()).unwrap_or("recording failed");
        return Err(msg.to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn sidecar_stop_recording(state: State<SidecarState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    proc.send("stop_recording").map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn sidecar_transcribe_last(
    state:  State<SidecarState>,
    target: State<LastTargetApp>,
) -> Result<TranscribeResult, String> {
    // Pass the active app name so the sidecar can auto-detect the writing profile.
    let active_app: String = {
        let guard = target.0.lock().map_err(|e| e.to_string())?;
        guard.as_ref().map(|i| i.name.clone()).unwrap_or_default()
    };

    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let cmd = json!({ "action": "transcribe_last", "active_app": active_app });
    let resp = proc.send_value(cmd).map_err(|e| e.to_string())?;
    let result: TranscribeResult = serde_json::from_value(resp).map_err(|e| e.to_string())?;
    Ok(result)
}

#[tauri::command]
pub fn sidecar_get_status(state: State<SidecarState>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let resp = proc.send("get_status").map_err(|e| e.to_string())?;
    Ok(resp.to_string())
}

#[tauri::command]
pub fn sidecar_stop(state: State<SidecarState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(proc) = guard.as_mut() {
        proc.kill();
    }
    *guard = None;
    Ok(())
}

// ── Mic diagnostic commands ───────────────────────────────────────────────────

#[tauri::command]
pub fn sidecar_list_microphones(state: State<SidecarState>) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    proc.send("list_microphones").map_err(|e| e.to_string())
}

#[tauri::command]
pub fn sidecar_test_microphone(state: State<SidecarState>) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    proc.send("test_microphone").map_err(|e| e.to_string())
}

// ── Text insertion ────────────────────────────────────────────────────────────

/// Activate the last-known non-Jarvis app, then paste text into it via Cmd+V.
/// Restores the previous clipboard content after 600 ms.
#[tauri::command]
pub fn paste_text(text: String, target: State<LastTargetApp>) -> Result<(), String> {
    eprintln!("[paste] {} chars", text.len());

    // ── 1. Resolve target app ───────────────────────────────────────────────
    let app_info = {
        let guard = target.0.lock().map_err(|e| e.to_string())?;
        guard.clone()
    };

    let app_info = app_info.ok_or_else(|| {
        "No target app found. Click into the app where you want text inserted, then dictate.".to_string()
    })?;

    eprintln!("[paste] target: {} ({})", app_info.name, app_info.bundle_id);

    // ── 2. Restore focus to target app ──────────────────────────────────────
    activate_app(&app_info).map_err(|e| format!("Could not activate target app: {}", e))?;
    // Wait for the window to come to front before writing to clipboard.
    std::thread::sleep(std::time::Duration::from_millis(250));

    // ── 3. Write text to clipboard ──────────────────────────────────────────
    let mut cb = arboard::Clipboard::new().map_err(|e| e.to_string())?;
    let previous = cb.get_text().ok();
    cb.set_text(text).map_err(|e| e.to_string())?;
    // Brief pause so clipboard change settles before the keystroke.
    std::thread::sleep(std::time::Duration::from_millis(80));

    // ── 4. Cmd+V ────────────────────────────────────────────────────────────
    let output = std::process::Command::new("osascript")
        .arg("-e")
        .arg(r#"tell application "System Events" to keystroke "v" using command down"#)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr).to_string();
        eprintln!("[paste] failed: {}", err);
        return Err(format!("Paste failed: {}", err));
    }
    eprintln!("[paste] success into '{}'", app_info.name);

    // ── 5. Restore previous clipboard (non-blocking) ────────────────────────
    if let Some(prev) = previous {
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(600));
            if let Ok(mut cb2) = arboard::Clipboard::new() {
                let _ = cb2.set_text(prev);
            }
        });
    }
    Ok(())
}

/// Return the name of the currently tracked paste target (for diagnostics/UI).
#[tauri::command]
pub fn get_last_target_app(target: State<LastTargetApp>) -> Option<String> {
    let guard = target.0.lock().ok()?;
    guard.as_ref().map(|i| format!("{} ({})", i.name, i.bundle_id))
}

// ── Accessibility ─────────────────────────────────────────────────────────────

/// Returns true if Accessibility permission has been granted.
/// Uses AppleScript System Events as a practical proxy check.
#[tauri::command]
pub fn get_accessibility_status() -> bool {
    let ok = std::process::Command::new("osascript")
        .arg("-e")
        .arg(r#"tell application "System Events" to return name of first process where it is frontmost"#)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);
    eprintln!("[accessibility] trusted={}", ok);
    ok
}

/// Open macOS Privacy → Accessibility settings pane.
#[tauri::command]
pub fn open_accessibility_settings() -> Result<(), String> {
    std::process::Command::new("open")
        .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

// ── Clipboard (copy only, no paste) ──────────────────────────────────────────

/// Write text to the system clipboard without triggering a paste.
#[tauri::command]
pub fn copy_to_clipboard(text: String) -> Result<(), String> {
    let mut cb = arboard::Clipboard::new().map_err(|e| e.to_string())?;
    cb.set_text(text).map_err(|e| e.to_string())
}

// ── History ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub fn save_history_entry(entry: data::HistoryEntry) -> Result<(), String> {
    data::append_history(&entry).map_err(|e| e.to_string())
}

// ── Cancel recording ──────────────────────────────────────────────────────────

#[tauri::command]
pub fn sidecar_cancel_recording(state: State<SidecarState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    proc.send("cancel_recording").map_err(|e| e.to_string())?;
    eprintln!("[sidecar] recording cancelled");
    Ok(())
}

// ── HUD position ─────────────────────────────────────────────────────────────

#[tauri::command]
pub fn save_hud_position(x: i32, y: i32) -> Result<(), String> {
    let mut s = settings::load();
    s.hud_x = x;
    s.hud_y = y;
    settings::save(&s).map_err(|e| e.to_string())
}

// ── Native macOS commands ─────────────────────────────────────────────────────

#[tauri::command]
pub fn open_url(url: String) -> Result<(), String> {
    std::process::Command::new("open")
        .arg(&url)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn open_app(app_name: String) -> Result<(), String> {
    std::process::Command::new("open")
        .arg("-a")
        .arg(&app_name)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn restart_engine(state: State<SidecarState>) -> Result<(), String> {
    let _ = sidecar_stop(state.clone());
    sidecar_start(state).map(|_| ())
}

// ── Diagnostics ───────────────────────────────────────────────────────────────

#[derive(serde::Serialize)]
pub struct DiagnosticsReport {
    pub app_path: String,
    pub bundle_id: String,
    pub accessibility_trusted: bool,
    pub sidecar_running: bool,
    pub sidecar_pid: Option<u32>,
    pub python_path: Option<String>,
    pub sidecar_ping: String,
    pub mic_device: Option<serde_json::Value>,
    pub mic_list: String,
    pub mic_test: String,
    pub hotkey_listener: String,
    pub paste_target: String,
}

#[tauri::command]
pub fn get_diagnostics(state: State<SidecarState>, target: State<LastTargetApp>) -> DiagnosticsReport {
    // App path
    let app_path = std::env::current_exe()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| "unknown".into());

    // Accessibility
    let accessibility_trusted = std::process::Command::new("osascript")
        .arg("-e")
        .arg(r#"tell application "System Events" to return name of first process where it is frontmost"#)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    // Sidecar state
    let mut guard = match state.0.lock() {
        Ok(g) => g,
        Err(_) => return DiagnosticsReport {
            app_path, bundle_id: "com.jarvis.dictation.tauri".into(),
            accessibility_trusted, sidecar_running: false, sidecar_pid: None,
            python_path: None, sidecar_ping: "mutex poisoned".into(),
            mic_device: None, mic_list: "n/a".into(), mic_test: "n/a".into(),
            hotkey_listener: "CGEventTap (Right Option + Esc)".into(),
            paste_target: "n/a".into(),
        },
    };

    let (sidecar_running, sidecar_pid, python_path, sidecar_ping, mic_device, mic_list, mic_test) =
        if let Some(proc) = guard.as_mut() {
            let pid = proc.pid();
            let py = proc.python_path.clone();

            let ping = match proc.send("ping") {
                Ok(v)  => v.to_string(),
                Err(e) => format!("ERROR: {}", e),
            };

            let mic_dev = crate::settings::load().mic_device
                .map(|i| serde_json::Value::Number(i.into()));

            let mic_list = match proc.send("list_microphones") {
                Ok(v)  => v.to_string(),
                Err(e) => format!("ERROR: {}", e),
            };
            let mic_test = match proc.send("test_microphone") {
                Ok(v)  => v.to_string(),
                Err(e) => format!("ERROR: {}", e),
            };

            (true, Some(pid), Some(py), ping, mic_dev, mic_list, mic_test)
        } else {
            (false, None, None, "sidecar not running".into(), None, "n/a".into(), "n/a".into())
        };

    let paste_target = {
        let guard = target.0.lock().ok();
        guard.and_then(|g| g.as_ref().map(|i| format!("{} ({})", i.name, i.bundle_id)))
              .unwrap_or_else(|| "none yet".into())
    };

    DiagnosticsReport {
        app_path,
        bundle_id: "com.jarvis.dictation.tauri".into(),
        accessibility_trusted,
        sidecar_running,
        sidecar_pid,
        python_path,
        sidecar_ping,
        mic_device,
        mic_list,
        mic_test,
        hotkey_listener: "CGEventTap (Right Option + Esc) — see stderr log".into(),
        paste_target,
    }
}
