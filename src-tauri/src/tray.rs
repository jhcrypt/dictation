use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, Runtime,
};

// ── Model / hotkey / strength / profile option lists (matching Python) ────────

const WHISPER_MODELS: &[&str] = &[
    "tiny.en", "base.en", "small.en", "medium.en",
    "large-v2", "large-v3", "distil-medium.en", "distil-large-v3",
];
const RECORD_KEYS: &[&str] = &["Right Option", "F13", "F14", "F15"];
const STRENGTHS:   &[&str] = &["Light", "Standard", "Strong", "Off"];
const PROFILES:    &[&str] = &[
    "General", "Professional", "Email", "Developer",
    "Medical", "Legal", "Sales", "Notes", "Creative", "Verbatim",
];

pub fn setup_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let icon = load_tray_icon(app);
    let s    = crate::settings::load();

    // ── Status line (disabled, updates via set_title) ─────────────────────────
    let status = MenuItem::with_id(app, "status", "Status: Ready", false, None::<&str>)?;

    // ── Primary actions ───────────────────────────────────────────────────────
    let start  = MenuItem::with_id(app, "start",  "Start Dictation",  true,  None::<&str>)?;
    let cancel = MenuItem::with_id(app, "cancel", "Cancel Recording",  false, None::<&str>)?;
    let sep1   = PredefinedMenuItem::separator(app)?;

    // ── Toggle items (with checkmarks) ────────────────────────────────────────
    // "Toggle HUD" uses a stable label with a checkmark so the label never goes
    // stale (Tauri v2 does not support changing MenuItem text at runtime).
    let hide_hud  = CheckMenuItem::with_id(app, "hide_hud", "Toggle HUD", true, s.show_hud, None::<&str>)?;
    let safe_mode = CheckMenuItem::with_id(app, "safe_mode", "Safe Mode",       true, s.safe_mode,      None::<&str>)?;
    let wake      = CheckMenuItem::with_id(app, "wake",      "Wake Word",        true, s.wake_enabled,   None::<&str>)?;
    let jarvis    = CheckMenuItem::with_id(app, "jarvis",    "Jarvis Commands",  true, s.jarvis_enabled, None::<&str>)?;
    let sep2      = PredefinedMenuItem::separator(app)?;

    // ── Whisper Model submenu ─────────────────────────────────────────────────
    let model_items: Vec<CheckMenuItem<R>> = WHISPER_MODELS.iter().map(|m| {
        CheckMenuItem::with_id(app, format!("model::{}", m), *m, true, s.model == *m, None::<&str>)
            .expect("model menu item")
    }).collect();
    let model_refs: Vec<&dyn tauri::menu::IsMenuItem<R>> = model_items.iter()
        .map(|i| i as &dyn tauri::menu::IsMenuItem<R>).collect();
    let model_sub = Submenu::with_items(app, "Whisper Model", true, &model_refs)?;

    // ── Record Key submenu ────────────────────────────────────────────────────
    let key_items: Vec<CheckMenuItem<R>> = RECORD_KEYS.iter().map(|k| {
        CheckMenuItem::with_id(app, format!("key::{}", k), *k, true, s.hotkey_label == *k, None::<&str>)
            .expect("key menu item")
    }).collect();
    let key_refs: Vec<&dyn tauri::menu::IsMenuItem<R>> = key_items.iter()
        .map(|i| i as &dyn tauri::menu::IsMenuItem<R>).collect();
    let key_sub = Submenu::with_items(app, "Record Key", true, &key_refs)?;

    // ── Correction Strength submenu ───────────────────────────────────────────
    let strength_items: Vec<CheckMenuItem<R>> = STRENGTHS.iter().map(|st| {
        CheckMenuItem::with_id(app, format!("strength::{}", st), *st, true, s.correction_strength == *st, None::<&str>)
            .expect("strength menu item")
    }).collect();
    let strength_refs: Vec<&dyn tauri::menu::IsMenuItem<R>> = strength_items.iter()
        .map(|i| i as &dyn tauri::menu::IsMenuItem<R>).collect();
    let strength_sub = Submenu::with_items(app, "Correction Strength", true, &strength_refs)?;

    // ── Writing Profile submenu ───────────────────────────────────────────────
    let profile_items: Vec<CheckMenuItem<R>> = PROFILES.iter().map(|p| {
        CheckMenuItem::with_id(app, format!("profile::{}", p), *p, true, s.writing_profile == *p, None::<&str>)
            .expect("profile menu item")
    }).collect();
    let profile_refs: Vec<&dyn tauri::menu::IsMenuItem<R>> = profile_items.iter()
        .map(|i| i as &dyn tauri::menu::IsMenuItem<R>).collect();
    let profile_sub = Submenu::with_items(app, "Writing Profile", true, &profile_refs)?;

    let sep3 = PredefinedMenuItem::separator(app)?;

    // ── Navigation / utility items ────────────────────────────────────────────
    let open_settings  = MenuItem::with_id(app, "open_settings",  "Open Settings…",                    true,  None::<&str>)?;
    let add_correction = MenuItem::with_id(app, "add_correction", "Add Correction from Last Dictation", true,  None::<&str>)?;
    let open_snippets  = MenuItem::with_id(app, "open_snippets",  "Manage Snippets…",                   true,  None::<&str>)?;
    let open_history   = MenuItem::with_id(app, "open_history",   "Show History…",                      true,  None::<&str>)?;
    let open_perms     = MenuItem::with_id(app, "open_perms",     "Open macOS Permissions…",            true,  None::<&str>)?;
    let sep4           = PredefinedMenuItem::separator(app)?;

    // ── System items ──────────────────────────────────────────────────────────
    // Launch at Login: not yet implemented in Tauri build — disabled with TODO.
    let launch_login = MenuItem::with_id(app, "launch_login", "Launch at Login  (coming soon)", false, None::<&str>)?;
    let sep5  = PredefinedMenuItem::separator(app)?;
    let about = MenuItem::with_id(app, "about", "About Quill Tauri Preview", true, None::<&str>)?;
    let quit  = MenuItem::with_id(app, "quit",  "Quit Quill Tauri Preview",  true, None::<&str>)?;

    let menu = Menu::with_items(app, &[
        &status,
        &start,
        &cancel,
        &sep1,
        &hide_hud,
        &safe_mode,
        &wake,
        &jarvis,
        &sep2,
        &model_sub,
        &key_sub,
        &strength_sub,
        &profile_sub,
        &sep3,
        &open_settings,
        &add_correction,
        &open_snippets,
        &open_history,
        &open_perms,
        &sep4,
        &launch_login,
        &sep5,
        &about,
        &quit,
    ])?;

    let _tray = TrayIconBuilder::with_id("main")
        .icon(icon)
        .icon_as_template(true)
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(move |app, event| {
            let id = event.id.as_ref();

            // ── Navigation ────────────────────────────────────────────────────
            if id == "open_settings"  { return show_and_emit(app, "nav-setup");       }
            if id == "add_correction" { return show_and_emit(app, "nav-vocabulary");  }
            if id == "open_snippets"  { return show_and_emit(app, "nav-snippets");    }
            if id == "open_history"   { return show_and_emit(app, "nav-history");     }
            if id == "open_perms"     {
                let _ = std::process::Command::new("open")
                    .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
                    .spawn();
                return;
            }

            // ── Dictation actions ─────────────────────────────────────────────
            if id == "start"  { let _ = app.emit("tray-start-dictation", ()); return; }
            if id == "cancel" { let _ = app.emit("tray-stop-dictation",  ()); return; }

            // ── Toggles ───────────────────────────────────────────────────────
            if id == "hide_hud" {
                let mut s = crate::settings::load();
                s.show_hud = !s.show_hud;
                let _ = crate::settings::save(&s);
                if let Some(hud) = app.get_webview_window("hud") {
                    if s.show_hud { let _ = hud.show(); } else { let _ = hud.hide(); }
                }
                // Update menu item label (rebuild isn't possible at runtime so emit instead)
                let _ = app.emit("settings-changed", ());
                return;
            }
            if id == "safe_mode" {
                let mut s = crate::settings::load();
                s.safe_mode = !s.safe_mode;
                let _ = crate::settings::save(&s);
                return;
            }
            if id == "wake" {
                let mut s = crate::settings::load();
                s.wake_enabled = !s.wake_enabled;
                let _ = crate::settings::save(&s);
                return;
            }
            if id == "jarvis" {
                let mut s = crate::settings::load();
                s.jarvis_enabled = !s.jarvis_enabled;
                let _ = crate::settings::save(&s);
                return;
            }

            // ── Submenus — model / key / strength / profile ───────────────────
            if let Some(m) = id.strip_prefix("model::") {
                let mut s = crate::settings::load();
                s.model = m.to_string();
                let _ = crate::settings::save(&s);
                let _ = app.emit("settings-changed", ());
                return;
            }
            if let Some(k) = id.strip_prefix("key::") {
                let mut s = crate::settings::load();
                s.hotkey_label = k.to_string();
                let _ = crate::settings::save(&s);
                let _ = app.emit("settings-changed", ());
                return;
            }
            if let Some(st) = id.strip_prefix("strength::") {
                let mut s = crate::settings::load();
                s.correction_strength = st.to_string();
                let _ = crate::settings::save(&s);
                let _ = app.emit("settings-changed", ());
                return;
            }
            if let Some(p) = id.strip_prefix("profile::") {
                let mut s = crate::settings::load();
                s.writing_profile = p.to_string();
                let _ = crate::settings::save(&s);
                let _ = app.emit("settings-changed", ());
                return;
            }

            // ── System ────────────────────────────────────────────────────────
            if id == "about" {
                show_and_emit(app, "nav-help");
                return;
            }
            if id == "quit" {
                let state = app.state::<crate::sidecar::SidecarState>();
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(proc) = guard.as_mut() { proc.kill(); }
                    *guard = None;
                }
                app.exit(0);
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up, ..
            } = event {
                let app = tray.app_handle();
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
        })
        .build(app)?;

    Ok(())
}

fn show_and_emit<R: Runtime>(app: &AppHandle<R>, event: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    let _ = app.emit(event, ());
}

fn load_tray_icon<R: Runtime>(_app: &AppHandle<R>) -> Image<'static> {
    // Embed at compile time — works in both `tauri dev` and production bundles.
    // The binary is built from src-tauri/ so the path is relative to Cargo.toml.
    const ICON_BYTES: &[u8] = include_bytes!("../icons/quill_menubar_template_black_44.png");
    Image::from_bytes(ICON_BYTES).expect("valid tray icon PNG")
}
