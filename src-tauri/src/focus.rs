/// Focus tracker — keeps track of the last frontmost app that is NOT Jarvis.
///
/// A background thread polls NSRunningApplication via AppleScript every 800 ms.
/// Any app that is frontmost and is not com.jarvis.dictation.tauri gets stored
/// as the paste target.  paste_text reads this to restore focus before Cmd+V.
use std::sync::Mutex;
use tauri::{AppHandle, Manager, Runtime};

pub struct LastTargetApp(pub Mutex<Option<AppInfo>>);

#[derive(Clone, Debug)]
pub struct AppInfo {
    pub bundle_id: String,
    pub name: String,
}

impl LastTargetApp {
    pub fn new() -> Self {
        LastTargetApp(Mutex::new(None))
    }
}

const JARVIS_BUNDLE: &str = "com.jarvis.dictation.tauri";

/// Query the current frontmost app's bundle ID and name via AppleScript.
/// Returns None on any failure.
fn frontmost_app() -> Option<AppInfo> {
    // Single osascript call that returns "bundle_id|||name"
    let script = r#"
        tell application "System Events"
            set fp to first process where it is frontmost
            return (bundle identifier of fp) & "|||" & (name of fp)
        end tell
    "#;
    let output = std::process::Command::new("osascript")
        .arg("-e").arg(script)
        .output().ok()?;

    if !output.status.success() { return None; }
    let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let mut parts = s.splitn(2, "|||");
    let bundle_id = parts.next()?.trim().to_string();
    let name      = parts.next().unwrap_or("").trim().to_string();
    if bundle_id.is_empty() { return None; }
    Some(AppInfo { bundle_id, name })
}

/// Activate an app by bundle ID using System Events (requires Accessibility).
/// Falls back to `tell application id` activate if System Events fails.
pub fn activate_app(info: &AppInfo) -> Result<(), String> {
    // Primary: System Events set frontmost
    let script = format!(
        r#"tell application "System Events" to set frontmost of (first process whose bundle identifier is "{}") to true"#,
        info.bundle_id
    );
    let out = std::process::Command::new("osascript")
        .arg("-e").arg(&script)
        .output()
        .map_err(|e| e.to_string())?;

    if out.status.success() {
        return Ok(());
    }

    // Fallback: tell application id … to activate
    let script2 = format!(r#"tell application id "{}" to activate"#, info.bundle_id);
    let out2 = std::process::Command::new("osascript")
        .arg("-e").arg(&script2)
        .output()
        .map_err(|e| e.to_string())?;

    if out2.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Could not activate '{}' ({}): {}",
            info.name, info.bundle_id,
            String::from_utf8_lossy(&out2.stderr).trim()
        ))
    }
}

/// Start the background polling thread.
/// Must be called after `app.manage::<LastTargetApp>()`.
pub fn start_focus_tracker<R: Runtime>(app: AppHandle<R>) {
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(std::time::Duration::from_millis(800));
            if let Some(info) = frontmost_app() {
                if info.bundle_id != JARVIS_BUNDLE {
                    if let Ok(state) = app.try_state::<LastTargetApp>().ok_or(()) {
                        if let Ok(mut guard) = state.0.lock() {
                            *guard = Some(info);
                        }
                    }
                }
            }
        }
    });
}
