use crate::data::{self, Contact, HistoryEntry};
use arboard;
use crate::focus::{LastTargetApp, activate_app};
use crate::hotkey::HotkeyConfig;
use crate::settings::{self, Settings};
use crate::sidecar::{SidecarState, TranscribeResult, spawn_sidecar};
use tauri::State;
use serde_json::json;
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventTapLocation, CGKeyCode,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use std::time::Instant;
use std::sync::{Mutex, OnceLock};

// ── Settings commands ─────────────────────────────────────────────────────────

#[tauri::command]
pub fn load_settings() -> Settings {
    settings::load()
}

#[tauri::command]
pub fn save_settings(
    settings: Settings,
    hk: State<'_, HotkeyConfig>,
) -> Result<(), String> {
    // Update live hotkey atomics so listener switches immediately (no restart).
    hk.set_key(&settings.hotkey_label);
    hk.set_toggle(settings.toggle_mode);
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

/// Run `pbcopy` with the given text. Returns Ok(()) on success.
fn pbcopy(text: &str) -> Result<(), String> {
    pbcopy_raw(text.as_bytes())
}

/// Run `pbcopy` with raw bytes (preserves non-UTF-8 clipboard contents).
fn pbcopy_raw(data: &[u8]) -> Result<(), String> {
    let mut child = std::process::Command::new("pbcopy")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("pbcopy spawn failed: {}", e))?;

    use std::io::Write;
    child.stdin.take()
        .ok_or_else(|| "pbcopy stdin not available".to_string())?
        .write_all(data)
        .map_err(|e| format!("pbcopy write failed: {}", e))?;

    let status = child.wait().map_err(|e| format!("pbcopy wait failed: {}", e))?;
    if !status.success() {
        return Err("pbcopy failed".to_string());
    }
    Ok(())
}

/// Activate the last-known non-Jarvis app, paste dictated text via Cmd+V,
/// then restore the user's original clipboard contents.
///
/// Uses macOS pbcopy/pbpaste CLI tools (not arboard), matching the Python
/// app's approach.  pbcopy writes directly to NSPasteboard so there is no
/// cache-vs-reality mismatch like arboard has.

fn send_cmd_v_quartz() -> Result<(), String> {
    const KEY_V: CGKeyCode = 9;

    let source = CGEventSource::new(CGEventSourceStateID::HIDSystemState)
        .map_err(|e| format!("failed to create CGEventSource: {:?}", e))?;

    let key_down = CGEvent::new_keyboard_event(source.clone(), KEY_V, true)
        .map_err(|e| format!("failed to create key down event: {:?}", e))?;
    key_down.set_flags(CGEventFlags::CGEventFlagCommand);
    key_down.post(CGEventTapLocation::HID);

    let key_up = CGEvent::new_keyboard_event(source, KEY_V, false)
        .map_err(|e| format!("failed to create key up event: {:?}", e))?;
    key_up.set_flags(CGEventFlags::CGEventFlagCommand);
    key_up.post(CGEventTapLocation::HID);

    Ok(())
}

fn send_cmd_v_osascript() -> Result<(), String> {
    std::process::Command::new("osascript")
        .arg("-e")
        .arg(r#"tell application "System Events" to keystroke "v" using command down"#)
        .output()
        .map_err(|e| e.to_string())?;

    Ok(())
}

fn send_cmd_v() -> Result<(), String> {
    match send_cmd_v_quartz() {
        Ok(()) => {
            eprintln!("[paste] cmd_v method=quartz");
            Ok(())
        }
        Err(e) => {
            eprintln!(
                "[paste] Quartz Cmd+V failed, falling back to osascript: {}",
                e
            );
            send_cmd_v_osascript()
        }
    }
}

#[tauri::command]
pub fn paste_text(text: String, target: State<LastTargetApp>) -> Result<(), String> {
    eprintln!("[paste] requested text len={} preview={}", text.len(), &text[..text.len().min(40)]);

    // ── 1. Save original clipboard BEFORE we touch it ───────────────────────
    // pbpaste with no args returns the current plain-text clipboard content.
    // We read raw bytes so non-UTF-8 content (e.g. RTF, binary) round-trips
    // correctly through pbcopy_raw() below.
    let prev_clipboard: Option<Vec<u8>> = std::process::Command::new("pbpaste")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .output()
        .ok()
        .map(|o| o.stdout)
        .filter(|b| !b.is_empty());

    eprintln!(
        "[paste] saved original clipboard ({} bytes)",
        prev_clipboard.as_ref().map_or(0, |b| b.len())
    );

    // ── 2. Resolve target app ───────────────────────────────────────────────
    let app_info = {
        let guard = target.0.lock().map_err(|e| e.to_string())?;
        guard.clone()
    };

    let app_info = app_info.ok_or_else(|| {
        "No target app found. Click into the app where you want text inserted, then dictate.".to_string()
    })?;

    eprintln!("[paste] target: {} ({})", app_info.name, app_info.bundle_id);

    // ── 3. Restore focus to target app ──────────────────────────────────────
    activate_app(&app_info).map_err(|e| format!("Could not activate target app: {}", e))?;
    // Wait for the window to come to front before writing to clipboard.
    std::thread::sleep(std::time::Duration::from_millis(250));

    // ── 4. Write dictated text via pbcopy ──────────────────────────────────
    // Append a trailing space to match Python behavior (ensures paste ends
    // the word being typed rather than extending it).
    // Python source: paste_text() at line 2484: paste_content = text + " "
    let paste_content = format!("{} ", text);
    pbcopy(&paste_content)?;
    eprintln!("[paste] clipboard set via pbcopy");

    // ── 5. Cmd+V ───────────────────────────────────────────────────────────
    // pbcopy is synchronous — the process exits only after NSPasteboard ownership
    // is registered.  No settle needed (unlike arboard which had internal cache).
    let cmd_v_start = Instant::now();
    send_cmd_v()?;
    eprintln!(
        "[paste] cmd_v returned elapsed={}ms",
        cmd_v_start.elapsed().as_millis()
    );
    eprintln!("[paste] Cmd+V sent successfully into '{}'", app_info.name);

    // ── 6. Wait for target app to process the paste, then restore clipboard ─
    // 350 ms is enough for the app to read NSPasteboard before we overwrite it.
    std::thread::sleep(std::time::Duration::from_millis(350));

    if let Some(prev_bytes) = prev_clipboard {
        match pbcopy_raw(&prev_bytes) {
            Ok(()) => eprintln!("[paste] original clipboard restored ({} bytes)", prev_bytes.len()),
            Err(e) => eprintln!("[paste] clipboard restore failed (non-fatal): {}", e),
        }
    } else {
        eprintln!("[paste] no original clipboard to restore (was empty before dictation)");
    }

    Ok(())
}

/// Return the name of the currently tracked paste target (for diagnostics/UI).
#[tauri::command]
pub fn get_last_target_app(target: State<LastTargetApp>) -> Option<String> {
    let guard = target.0.lock().ok()?;
    guard.as_ref().map(|i| format!("{} ({})", i.name, i.bundle_id))
}

/// Return the target app's icon as a base64-encoded PNG (24×24) for the HUD.
/// Returns None if the icon cannot be resolved.
#[tauri::command]
pub fn get_target_app_icon(target: State<LastTargetApp>) -> Option<String> {
    let bundle_id = {
        let guard = target.0.lock().ok()?;
        guard.as_ref()?.bundle_id.clone()
    };

    // Find the .app bundle path from the bundle identifier.
    let mdfind_out = std::process::Command::new("mdfind")
        .arg(format!("kMDItemCFBundleIdentifier == '{}'", bundle_id))
        .output().ok()?;
    let app_path = String::from_utf8_lossy(&mdfind_out.stdout)
        .trim().lines().next()?.trim().to_string();
    if app_path.is_empty() { return None; }

    // Read CFBundleIconFile from Info.plist.
    let plist_path = format!("{}/Contents/Info.plist", app_path);
    let defaults_out = std::process::Command::new("defaults")
        .args(["read", &plist_path, "CFBundleIconFile"])
        .output().ok()?;
    let mut icon_name = String::from_utf8_lossy(&defaults_out.stdout).trim().to_string();
    if icon_name.is_empty() { return None; }
    if !icon_name.ends_with(".icns") { icon_name.push_str(".icns"); }

    let icon_src = format!("{}/Contents/Resources/{}", app_path, icon_name);
    let tmp_path = format!("/tmp/jarvis_hud_icon_{}.png", std::process::id());

    // Convert .icns → 80×80 PNG via sips (2× of 40px display → crisp on Retina).
    let ok = std::process::Command::new("sips")
        .args(["-s", "format", "png", "-z", "80", "80",
               &icon_src, "--out", &tmp_path])
        .output().ok()?.status.success();
    if !ok { return None; }

    // Read bytes and base64-encode via the system `base64` tool.
    let b64_out = std::process::Command::new("base64")
        .args(["-i", &tmp_path])
        .output().ok()?;
    if !b64_out.status.success() { return None; }

    let encoded = String::from_utf8_lossy(&b64_out.stdout)
        .split_whitespace()   // strip newlines inserted by base64
        .collect::<String>();
    Some(encoded)
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

// ── Wake-word commands ────────────────────────────────────────────────────────

/// Start the Python wake listener (opens 16 kHz mic stream + openwakeword thread).
/// Returns the raw sidecar JSON as a string so the frontend can inspect ok/error.
#[tauri::command]
pub fn sidecar_start_wake_listen(state: State<SidecarState>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let resp = proc.send("start_wake_listen").map_err(|e| e.to_string())?;
    Ok(resp.to_string())
}

/// Stop the Python wake listener (closes stream, stops detection thread).
#[tauri::command]
pub fn sidecar_stop_wake_listen(state: State<SidecarState>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    let resp = proc.send("stop_wake_listen").map_err(|e| e.to_string())?;
    Ok(resp.to_string())
}

/// Poll wake status — called by the Rust wake-poll thread every 300 ms.
/// Returns {"ok":true,"listening":bool,"detected":bool}.
/// "detected" is a one-shot flag: reading it clears it in the sidecar.
#[tauri::command]
pub fn sidecar_get_wake_status(state: State<SidecarState>) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let proc = guard.as_mut().ok_or("Sidecar not running")?;
    proc.send("get_wake_status").map_err(|e| e.to_string())
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

// ── Ollama status + model install ─────────────────────────────────────────────

/// The single model recommended by Quill for local AI cleanup — must match
/// Python's OLLAMA_MODEL constant and the sidecar's OLLAMA_MODEL value.
pub const OLLAMA_RECOMMENDED_MODEL: &str = "qwen2.5:3b";

/// Find the ollama CLI binary. Mirrors Python's _check_ollama_status probe order.
fn find_ollama_cli() -> Option<String> {
    // Try PATH via `which`
    if let Ok(out) = std::process::Command::new("which").arg("ollama").output() {
        if out.status.success() {
            let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !p.is_empty() { return Some(p); }
        }
    }
    // Common install locations (Homebrew + official pkg installer)
    for p in &["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"] {
        if std::path::Path::new(p).exists() { return Some(p.to_string()); }
    }
    None
}

/// Probe Ollama and return one of:
///   "ready"         — server running, recommended model present
///   "not_installed" — ollama CLI not found
///   "not_running"   — CLI found, but `ollama list` failed / server not responding
///   "model_missing" — server running, model not yet downloaded
///
/// Matches Python _check_ollama_status exactly. Safe to call from any thread.
#[tauri::command]
pub fn check_ollama_status() -> String {
    let Some(cli) = find_ollama_cli() else {
        eprintln!("[ollama] status: not_installed");
        return "not_installed".into();
    };

    // Is the server responding?
    let list = std::process::Command::new(&cli)
        .arg("list")
        .output();

    match list {
        Err(_) => {
            eprintln!("[ollama] status: not_running (spawn failed)");
            return "not_running".into();
        }
        Ok(out) if !out.status.success() => {
            eprintln!("[ollama] status: not_running (exit {})", out.status);
            return "not_running".into();
        }
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            if stdout.contains(OLLAMA_RECOMMENDED_MODEL) {
                eprintln!("[ollama] status: ready");
                "ready".into()
            } else {
                eprintln!("[ollama] status: model_missing");
                "model_missing".into()
            }
        }
    }
}

/// Pull the recommended model (`ollama pull qwen2.5:3b`).
/// Runs in a blocking thread so Tauri's async runtime stays free.
/// Returns Ok("installed") on success, Err(message) on failure.
/// Matches Python's _do_install_model — only runs when the user explicitly clicks.
#[tauri::command]
pub async fn install_ollama_model() -> Result<String, String> {
    tokio::task::spawn_blocking(|| {
        eprintln!("[ollama] pulling {} …", OLLAMA_RECOMMENDED_MODEL);
        let result = std::process::Command::new("ollama")
            .args(["pull", OLLAMA_RECOMMENDED_MODEL])
            .output()
            .map_err(|e| format!("Failed to run ollama: {}", e))?;

        if result.status.success() {
            eprintln!("[ollama] pull complete");
            Ok("installed".to_string())
        } else {
            let err = String::from_utf8_lossy(&result.stderr).to_string();
            eprintln!("[ollama] pull failed: {}", err);
            Err(format!("ollama pull failed: {}", err.lines().next().unwrap_or("unknown error")))
        }
    })
    .await
    .map_err(|e| e.to_string())?
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


// ── Media pause / resume ─────────────────────────────────────────────────────

#[derive(Default, Debug)]
struct MediaPauseState {
    active: bool,
    pre_recording_muted: bool,
    paused_apps: Vec<String>,
}

static MEDIA_PAUSE_STATE: OnceLock<Mutex<MediaPauseState>> = OnceLock::new();

fn media_pause_state() -> &'static Mutex<MediaPauseState> {
    MEDIA_PAUSE_STATE.get_or_init(|| Mutex::new(MediaPauseState::default()))
}

fn osa_output(script: &str) -> Option<String> {
    let out = std::process::Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .ok()?;

    if !out.status.success() {
        return None;
    }

    Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn osa_spawn(script: &str) {
    let _ = std::process::Command::new("osascript")
        .arg("-e")
        .arg(script)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
}

fn app_is_running(process_name: &str) -> bool {
    std::process::Command::new("pgrep")
        .args(["-ix", process_name])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn pause_player_if_playing(app_name: &str) -> bool {
    if !app_is_running(app_name) {
        return false;
    }

    let script = format!(
        r#"try
  tell application "{}" to player state as string
on error
  return "stopped"
end try"#,
        app_name
    );

    let state = osa_output(&script).unwrap_or_default().to_lowercase();
    if state.contains("playing") {
        osa_spawn(&format!(r#"tell application "{}" to pause"#, app_name));
        eprintln!("[media] paused {}", app_name);
        true
    } else {
        false
    }
}

#[tauri::command]
pub fn pause_media() -> Result<(), String> {
    let mut guard = media_pause_state().lock().map_err(|e| e.to_string())?;

    if guard.active {
        eprintln!("[media] pause_media ignored — already active");
        return Ok(());
    }

    let was_muted = osa_output(r#"output muted of (get volume settings)"#)
        .map(|v| v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    guard.active = true;
    guard.pre_recording_muted = was_muted;
    guard.paused_apps.clear();

    // Match Python behavior: instantly mute first so browser/audio cannot bleed into recording.
    if !was_muted {
        osa_spawn(r#"set volume with output muted"#);
        eprintln!("[media] system muted");
    }

    // Pause app players in the background when they were actually playing.
    for app_name in ["Spotify", "Music", "Podcasts"] {
        if pause_player_if_playing(app_name) {
            guard.paused_apps.push(app_name.to_string());
        }
    }

    Ok(())
}

#[tauri::command]
pub fn resume_media() -> Result<(), String> {
    let mut guard = media_pause_state().lock().map_err(|e| e.to_string())?;

    if !guard.active {
        return Ok(());
    }

    let pre_recording_muted = guard.pre_recording_muted;
    let paused_apps = guard.paused_apps.clone();

    guard.active = false;
    guard.paused_apps.clear();

    if !pre_recording_muted {
        osa_spawn(r#"set volume without output muted"#);
        eprintln!("[media] system unmuted");
    }

    for app_name in paused_apps {
        osa_spawn(&format!(r#"tell application "{}" to play"#, app_name));
        eprintln!("[media] resumed {}", app_name);
    }

    Ok(())
}


// ── Recording sounds ──────────────────────────────────────────────────────────

/// Play a system sound via `afplay` to indicate recording state transitions.
/// Fire-and-forget: the command is spawned, and any failure is silently ignored
/// so that sound playback never interferes with dictation.
///
/// kind must be one of:
///   "start"  → /System/Library/Sounds/Tink.aiff
///   "stop"   → /System/Library/Sounds/Pop.aiff
///   "cancel" → /System/Library/Sounds/Funk.aiff
#[tauri::command]
pub fn play_recording_sound(kind: String) -> Result<(), String> {
    let sound = match kind.as_str() {
        "start"  => "/System/Library/Sounds/Tink.aiff",
        "stop"   => "/System/Library/Sounds/Pop.aiff",
        "cancel" => "/System/Library/Sounds/Funk.aiff",
        _ => return Err(format!("Unknown recording sound kind: {}", kind)),
    };

    // Fire-and-forget: spawn afplay, ignore any failure
    match std::process::Command::new("afplay").arg(sound).spawn() {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!("[sound] failed to play {}: {}", kind, e);
            Err(format!("Failed to play sound: {}", e))
        }
    }
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