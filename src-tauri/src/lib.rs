mod commands;
mod data;
mod focus;
mod hotkey;
mod settings;
mod sidecar;
mod tray;

use commands::*;
use focus::LastTargetApp;
use sidecar::SidecarState;
use tauri::{Manager, WebviewWindowBuilder, WebviewUrl};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState::new())
        .manage(LastTargetApp::new())
        .setup(|app| {
            tray::setup_tray(app.handle())?;

            // Create main window programmatically for full macOS chrome control.
            // transparent(true)      — lets native window corners clip the content
            // TitleBarStyle::Overlay — traffic lights stay, content fills to top
            // title("")              — hide native title; shown in our custom header
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("")
                .transparent(true)
                .title_bar_style(tauri::TitleBarStyle::Overlay)
                .inner_size(900.0, 680.0)
                .min_inner_size(700.0, 500.0)
                .resizable(true)
                .center()
                .visible(true)
                .build()?;

            // Global hotkey listener (CGEventTap, no HIToolbox calls).
            hotkey::start_hotkey_listener(app.handle().clone());

            // Start focus tracker — polls frontmost app every 800 ms.
            focus::start_focus_tracker(app.handle().clone());

            // Auto-start the Python sidecar.
            let state = app.handle().state::<SidecarState>();
            let mut guard = state.0.lock().unwrap();
            match crate::sidecar::start_sidecar_process() {
                Ok(proc) => { *guard = Some(proc); }
                Err(e) => { eprintln!("[jarvis] sidecar auto-start failed: {}", e); }
            }
            drop(guard);

            // Create floating HUD window — always on top, no decorations.
            let hud = WebviewWindowBuilder::new(app, "hud", WebviewUrl::App("index.html".into()))
                .title("Quill Tauri Preview HUD")
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .visible_on_all_workspaces(true)
                .focused(false)
                .resizable(false)
                .shadow(false)
                .inner_size(420.0, 52.0)
                .visible(true)
                .build()?;

            // Restore saved HUD position, with off-screen guard.
            if let Ok(Some(monitor)) = hud.primary_monitor() {
                let sf = monitor.scale_factor();
                let screen_w = (monitor.size().width as f64 / sf) as i32;
                let screen_h = (monitor.size().height as f64 / sf) as i32;
                let saved = crate::settings::load();
                let mut hud_x = saved.hud_x;
                let mut hud_y = saved.hud_y;
                // Reset off-screen positions to default top-center.
                if hud_x < 0 || hud_x + 420 > screen_w || hud_y < 0 || hud_y + 52 > screen_h {
                    hud_x = (screen_w - 420) / 2;
                    hud_y = 28;
                }
                let _ = hud.set_position(tauri::Position::Logical(
                    tauri::LogicalPosition::new(hud_x as f64, hud_y as f64),
                ));
            }

            Ok(())
        })
        // ── Intercept close on "main" — hide instead of destroy ──────────────
        // Tauri's default is to destroy the window on close (red X / Cmd+W).
        // Once destroyed, get_webview_window("main") returns None and the tray
        // "Open Settings…" handler can never show it again.
        // Fix: prevent the close event and hide the window instead; the tray
        // handler's existing w.show() + set_focus() then works correctly.
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    window.hide().ok();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            // Settings
            load_settings,
            save_settings,
            reset_settings,
            // Contacts
            load_contacts,
            save_contacts,
            // History
            load_history,
            clear_history,
            // Vocabulary
            load_vocab,
            save_vocab,
            // Snippets
            load_snippets,
            save_snippets,
            // Custom commands
            load_custom_commands,
            save_custom_commands,
            // Storage
            clear_vocabulary,
            clear_log,
            // Sidecar
            sidecar_start,
            sidecar_ping,
            sidecar_start_recording,
            sidecar_stop_recording,
            sidecar_transcribe_last,
            sidecar_get_status,
            sidecar_stop,
            // Mic diagnostics
            sidecar_list_microphones,
            sidecar_test_microphone,
            sidecar_cancel_recording,
            // HUD
            save_hud_position,
            get_target_app_icon,
            // Paste & clipboard & accessibility
            paste_text,
            copy_to_clipboard,
            get_accessibility_status,
            open_accessibility_settings,
            // History
            save_history_entry,
            // Native
            open_url,
            open_app,
            restart_engine,
            get_diagnostics,
            get_last_target_app,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Quill Tauri Preview");
}
