/// hotkey.rs — CGEventTap-based global hotkey (no rdev, no HIToolbox calls).
///
/// rdev crashed because its callback called Keyboard::string_from_code →
/// TSMGetInputSourceProperty, which asserts dispatch_assert_queue(main).
/// This implementation reads ONLY raw integers from the event — no HIToolbox,
/// no TSM, no string conversion — so it is safe on any thread.
///
/// Supported record keys (live-switchable without restart):
///   Right Option  — modifier key, keycode 61,  via CG_EVENT_FLAGS_CHANGED
///   F13           — regular key,  keycode 105, via CG_EVENT_KEY_DOWN / KEY_UP
///   F14           — regular key,  keycode 107
///   F15           — regular key,  keycode 113
///
/// Toggle mode (settings.toggle_mode):
///   false (push-to-talk) — hold key → start recording, release → transcribe
///   true  (toggle)       — first press → start, second press → stop (F-key keyUp ignored)
///
/// Tauri events emitted:
///   "hotkey-ropt-down"  →  start recording
///   "hotkey-ropt-up"    →  stop + transcribe + paste
///   "hotkey-esc"        →  cancel recording

use std::io::Write as _;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use tauri::{AppHandle, Emitter, Runtime};

// ── CGEventType constants ─────────────────────────────────────────────────────
const CG_EVENT_KEY_DOWN:      u32 = 10;
const CG_EVENT_KEY_UP:        u32 = 11;
const CG_EVENT_FLAGS_CHANGED: u32 = 12;

// ── CGEventField: keyboard key code ──────────────────────────────────────────
const CG_KEYBOARD_EVENT_KEYCODE: u32 = 9;

// ── CGEventFlags: Option/Alt key bit ─────────────────────────────────────────
const CG_FLAG_ALTERNATE: u64 = 0x0008_0000;

// ── CGEventTap configuration ──────────────────────────────────────────────────
const CG_SESSION_EVENT_TAP:            u32 = 1;
const CG_HEAD_INSERT_EVENT_TAP:        u32 = 0;
const CG_EVENT_TAP_OPTION_LISTEN_ONLY: u32 = 1;

// ── macOS virtual key codes ───────────────────────────────────────────────────
const KEY_RIGHT_OPTION: i64 = 61;  // kVK_RightOption
const KEY_ESCAPE:        i64 = 53;  // kVK_Escape
const KEY_F13:           i64 = 105; // kVK_F13
const KEY_F14:           i64 = 107; // kVK_F14
const KEY_F15:           i64 = 113; // kVK_F15

/// Convert a `hotkey_label` string (from settings) to a macOS virtual keycode.
pub fn label_to_keycode(label: &str) -> i64 {
    match label {
        "F13" => KEY_F13,
        "F14" => KEY_F14,
        "F15" => KEY_F15,
        _     => KEY_RIGHT_OPTION, // "Right Option" or any unknown value
    }
}

// ── Shared live-switchable config ─────────────────────────────────────────────

/// Managed Tauri state: allows live-switching of hotkey and toggle mode
/// without restarting the CGEventTap.
#[derive(Clone)]
pub struct HotkeyConfig {
    /// Current active keycode (one of 61, 105, 107, 113).
    pub keycode: Arc<AtomicI64>,
    /// Toggle mode: false = push-to-talk, true = press-once-to-start/stop.
    pub toggle_mode: Arc<AtomicBool>,
}

impl HotkeyConfig {
    pub fn new(hotkey_label: &str, toggle_mode: bool) -> Self {
        Self {
            keycode:     Arc::new(AtomicI64::new(label_to_keycode(hotkey_label))),
            toggle_mode: Arc::new(AtomicBool::new(toggle_mode)),
        }
    }

    pub fn set_key(&self, label: &str) {
        self.keycode.store(label_to_keycode(label), Ordering::SeqCst);
    }

    pub fn set_toggle(&self, on: bool) {
        self.toggle_mode.store(on, Ordering::SeqCst);
    }
}

// ── FFI: CoreGraphics framework ───────────────────────────────────────────────
type TapCb = unsafe extern "C" fn(
    proxy:  *mut std::ffi::c_void,
    etype:  u32,
    event:  *mut std::ffi::c_void,
    refcon: *mut std::ffi::c_void,
) -> *mut std::ffi::c_void;

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventTapCreate(
        tap:      u32,
        place:    u32,
        options:  u32,
        events:   u64,
        callback: TapCb,
        refcon:   *mut std::ffi::c_void,
    ) -> *mut std::ffi::c_void;

    fn CGEventGetIntegerValueField(event: *mut std::ffi::c_void, field: u32) -> i64;
    fn CGEventGetFlags(event: *mut std::ffi::c_void) -> u64;
    fn CGEventTapEnable(tap: *mut std::ffi::c_void, enable: bool);
}

// ── FFI: CoreFoundation framework ─────────────────────────────────────────────
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFMachPortCreateRunLoopSource(
        alloc:  *const std::ffi::c_void,
        port:   *mut std::ffi::c_void,
        order:  i64,
    ) -> *mut std::ffi::c_void;

    fn CFRunLoopAddSource(
        rl:     *mut std::ffi::c_void,
        source: *mut std::ffi::c_void,
        mode:   *const std::ffi::c_void,
    );

    fn CFRunLoopGetCurrent() -> *mut std::ffi::c_void;
    fn CFRunLoopRun();

    static kCFRunLoopDefaultMode: *const std::ffi::c_void;
}

// ── Context passed through the CGEventTap refcon void* ───────────────────────
struct TapCtx {
    emit_down: Box<dyn Fn() + Send + Sync>,
    emit_up:   Box<dyn Fn() + Send + Sync>,
    emit_esc:  Box<dyn Fn() + Send + Sync>,
    /// Physical hold-state for push-to-talk (Right Option and F-keys).
    held: AtomicBool,
    /// Shared live-switchable config (keycode + toggle_mode).
    config: HotkeyConfig,
}

// ── CGEventTap callback — reads key code + flags only, no HIToolbox ───────────
//
// SAFETY NOTE: This is an extern "C" fn — Rust panics CANNOT unwind through
// the FFI boundary.  If a panic reaches here the runtime calls abort() and
// the whole process dies (EXC_CRASH / SIGABRT).
//
// Two defences:
//   1. Replace every `eprintln!` with `let _ = writeln!(stderr, ...)`.
//      `eprintln!` panics when the stderr pipe is broken (e.g. after the dev
//      server restarts and the binary is re-parented to launchd).
//      `writeln!` returns a Result; discarding it with `let _ =` is safe.
//   2. Wrap the entire body in `catch_unwind(AssertUnwindSafe(...))`.
//      If anything inside still panics the error is silently swallowed rather
//      than aborting the process.
unsafe extern "C" fn tap_callback(
    _proxy: *mut std::ffi::c_void,
    etype:  u32,
    event:  *mut std::ffi::c_void,
    refcon: *mut std::ffi::c_void,
) -> *mut std::ffi::c_void {
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let ctx    = &*(refcon as *const TapCtx);
        let kc     = CGEventGetIntegerValueField(event, CG_KEYBOARD_EVENT_KEYCODE);
        let cur_kc = ctx.config.keycode.load(Ordering::SeqCst);
        let toggle = ctx.config.toggle_mode.load(Ordering::SeqCst);

        match etype {
            // ── Right Option (modifier key — generates FlagsChanged) ──────────
            CG_EVENT_FLAGS_CHANGED if cur_kc == KEY_RIGHT_OPTION && kc == KEY_RIGHT_OPTION => {
                let alt_down = CGEventGetFlags(event) & CG_FLAG_ALTERNATE != 0;
                if toggle {
                    // Toggle mode: only act on key-press (alt_down), ignore release.
                    if alt_down {
                        if ctx.held.swap(true, Ordering::SeqCst) {
                            // Was held → this is "second press" → stop
                            ctx.held.store(false, Ordering::SeqCst);
                            let _ = writeln!(std::io::stderr(), "[hotkey] right option TOGGLE-OFF");
                            (ctx.emit_up)();
                        } else {
                            // Was not held → start
                            let _ = writeln!(std::io::stderr(), "[hotkey] right option TOGGLE-ON");
                            (ctx.emit_down)();
                        }
                    }
                    // Release events ignored in toggle mode.
                } else {
                    // Push-to-talk: alt_down → start, !alt_down → stop.
                    if alt_down && !ctx.held.swap(true, Ordering::SeqCst) {
                        let _ = writeln!(std::io::stderr(), "[hotkey] right option DOWN");
                        (ctx.emit_down)();
                    } else if !alt_down && ctx.held.swap(false, Ordering::SeqCst) {
                        let _ = writeln!(std::io::stderr(), "[hotkey] right option UP");
                        (ctx.emit_up)();
                    }
                }
            }

            // ── F13 / F14 / F15 (regular keys — generate KeyDown / KeyUp) ────
            CG_EVENT_KEY_DOWN if kc == cur_kc
                && (cur_kc == KEY_F13 || cur_kc == KEY_F14 || cur_kc == KEY_F15) =>
            {
                if toggle {
                    // Toggle: first KeyDown → start, second KeyDown → stop.
                    if ctx.held.swap(true, Ordering::SeqCst) {
                        ctx.held.store(false, Ordering::SeqCst);
                        let _ = writeln!(std::io::stderr(), "[hotkey] F-key TOGGLE-OFF");
                        (ctx.emit_up)();
                    } else {
                        let _ = writeln!(std::io::stderr(), "[hotkey] F-key TOGGLE-ON");
                        (ctx.emit_down)();
                    }
                } else {
                    // Push-to-talk: start on KeyDown (if not already held).
                    if !ctx.held.swap(true, Ordering::SeqCst) {
                        let _ = writeln!(std::io::stderr(), "[hotkey] F-key DOWN");
                        (ctx.emit_down)();
                    }
                }
            }

            CG_EVENT_KEY_UP if kc == cur_kc
                && (cur_kc == KEY_F13 || cur_kc == KEY_F14 || cur_kc == KEY_F15) =>
            {
                if !toggle {
                    // Push-to-talk: stop on KeyUp.
                    if ctx.held.swap(false, Ordering::SeqCst) {
                        let _ = writeln!(std::io::stderr(), "[hotkey] F-key UP");
                        (ctx.emit_up)();
                    }
                }
                // Toggle mode: KeyUp ignored.
            }

            // ── Escape — always active regardless of selected key ─────────────
            CG_EVENT_KEY_DOWN if kc == KEY_ESCAPE => {
                let _ = writeln!(std::io::stderr(), "[hotkey] ESC");
                (ctx.emit_esc)();
            }

            _ => {}
        }
    }));

    event // listen-only: return event unmodified
}

// ── Public API ────────────────────────────────────────────────────────────────
pub fn start_hotkey_listener<R: Runtime>(app: AppHandle<R>, config: HotkeyConfig) {
    std::thread::spawn(move || {
        let ctx = Box::new(TapCtx {
            emit_down: Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-ropt-down", ()); } }),
            emit_up:   Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-ropt-up",   ()); } }),
            emit_esc:  Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-esc",        ()); } }),
            held:      AtomicBool::new(false),
            config,
        });
        let ctx_ptr = Box::into_raw(ctx) as *mut std::ffi::c_void;

        // Bitmask: FlagsChanged (Right Option) + KeyDown + KeyUp (F-keys)
        let mask: u64 = (1 << CG_EVENT_FLAGS_CHANGED)
                      | (1 << CG_EVENT_KEY_DOWN)
                      | (1 << CG_EVENT_KEY_UP);

        unsafe {
            let tap = CGEventTapCreate(
                CG_SESSION_EVENT_TAP,
                CG_HEAD_INSERT_EVENT_TAP,
                CG_EVENT_TAP_OPTION_LISTEN_ONLY,
                mask,
                tap_callback,
                ctx_ptr,
            );

            if tap.is_null() {
                eprintln!("[hotkey] CGEventTapCreate failed — grant Accessibility permission and restart");
                drop(Box::from_raw(ctx_ptr as *mut TapCtx));
                return;
            }

            let source = CFMachPortCreateRunLoopSource(std::ptr::null(), tap, 0);
            if source.is_null() {
                eprintln!("[hotkey] CFMachPortCreateRunLoopSource failed");
                drop(Box::from_raw(ctx_ptr as *mut TapCtx));
                return;
            }

            let rl = CFRunLoopGetCurrent();
            CFRunLoopAddSource(rl, source, kCFRunLoopDefaultMode);
            CGEventTapEnable(tap, true);
            eprintln!("[hotkey] CGEventTap active — Right Option / F13 / F14 / F15 + Esc monitored globally");
            CFRunLoopRun(); // blocks this thread; tap stays live until process exits
        }
    });
}
