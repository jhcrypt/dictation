/// wake.rs — background wake-word poll loop.
///
/// Polls the Python sidecar's `get_wake_status` command every ~300 ms.
/// When the sidecar reports `detected: true` (one-shot flag), emits the
/// Tauri event `wake-detected` to all windows so the React controller
/// (`useGlobalHotkey`) can call `startRecording()`.
///
/// Mic contention is fully handled by the sidecar:
///   • start_recording  closes the wake stream
///   • stop/cancel_recording re-opens it when wake_listening is still true
///
/// This thread runs for the process lifetime. It is harmless when wake
/// listening is disabled (sidecar returns detected:false every poll).

use std::sync::{Arc, Mutex};
use std::time::Duration;
use crate::sidecar::SidecarProcess;

pub fn start_wake_poll_thread(
    emit_fn: Box<dyn Fn() + Send + 'static>,
    state:   Arc<Mutex<Option<SidecarProcess>>>,
) {
    std::thread::Builder::new()
        .name("wake-poll".into())
        .spawn(move || {
            eprintln!("[wake-poll] thread started");
            let mut error_backoff = false;

            loop {
                // Normal interval 300 ms; back off to 1 s after errors.
                std::thread::sleep(Duration::from_millis(if error_backoff { 1000 } else { 300 }));
                error_backoff = false;

                let detected = {
                    let mut guard = match state.lock() {
                        Ok(g)  => g,
                        Err(_) => { error_backoff = true; continue; }
                    };
                    match guard.as_mut() {
                        None => false, // sidecar not yet running
                        Some(proc) => match proc.send("get_wake_status") {
                            Ok(v) => v.get("detected")
                                       .and_then(|d| d.as_bool())
                                       .unwrap_or(false),
                            Err(e) => {
                                eprintln!("[wake-poll] get_wake_status error: {}", e);
                                error_backoff = true;
                                false
                            }
                        },
                    }
                    // guard (and mutex lock) dropped here, before emit
                };

                if detected {
                    eprintln!("[wake-poll] wake-detected → emitting to frontend");
                    emit_fn();
                }
            }
        })
        .expect("wake-poll thread spawn failed");
}
