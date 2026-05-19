/// hotkey.rs — CGEventTap-based global hotkey (no rdev, no HIToolbox calls).
///
/// rdev crashed because its callback called Keyboard::string_from_code →
/// TSMGetInputSourceProperty, which asserts dispatch_assert_queue(main).
/// This implementation reads ONLY raw integers from the event — no HIToolbox,
/// no TSM, no string conversion — so it is safe on any thread.
///
/// Events:
///   kCGEventFlagsChanged + keycode 61  → Right Option press / release
///   kCGEventKeyDown      + keycode 53  → Escape
///
/// Tauri events emitted:
///   "hotkey-ropt-down"  →  start recording
///   "hotkey-ropt-up"    →  stop + transcribe + paste
///   "hotkey-esc"        →  cancel recording

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Emitter, Runtime};

// ── CGEventType constants ─────────────────────────────────────────────────────
const CG_EVENT_KEY_DOWN:       u32 = 10;
const CG_EVENT_FLAGS_CHANGED:  u32 = 12;

// ── CGEventField: keyboard key code ──────────────────────────────────────────
const CG_KEYBOARD_EVENT_KEYCODE: u32 = 9;

// ── CGEventFlags: Option/Alt key bit ─────────────────────────────────────────
const CG_FLAG_ALTERNATE: u64 = 0x0008_0000;

// ── CGEventTap configuration ──────────────────────────────────────────────────
const CG_SESSION_EVENT_TAP:            u32 = 1;
const CG_HEAD_INSERT_EVENT_TAP:        u32 = 0;
const CG_EVENT_TAP_OPTION_LISTEN_ONLY: u32 = 1;

// ── macOS virtual key codes ───────────────────────────────────────────────────
const KEY_RIGHT_OPTION: i64 = 61; // kVK_RightOption
const KEY_ESCAPE:        i64 = 53; // kVK_Escape

// ── FFI: CoreGraphics framework ───────────────────────────────────────────────
type TapCb = unsafe extern "C" fn(
    proxy:   *mut std::ffi::c_void,
    etype:   u32,
    event:   *mut std::ffi::c_void,
    refcon:  *mut std::ffi::c_void,
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
    held:      AtomicBool,
}

// ── CGEventTap callback — reads key code + flags only, no HIToolbox ───────────
unsafe extern "C" fn tap_callback(
    _proxy:  *mut std::ffi::c_void,
    etype:   u32,
    event:   *mut std::ffi::c_void,
    refcon:  *mut std::ffi::c_void,
) -> *mut std::ffi::c_void {
    let ctx = &*(refcon as *const TapCtx);
    let kc  = CGEventGetIntegerValueField(event, CG_KEYBOARD_EVENT_KEYCODE);

    match etype {
        // Right Option is a modifier key: generates FlagsChanged events.
        // Distinguish press (Alternate flag set) from release (flag cleared).
        CG_EVENT_FLAGS_CHANGED if kc == KEY_RIGHT_OPTION => {
            let is_down = CGEventGetFlags(event) & CG_FLAG_ALTERNATE != 0;
            if is_down && !ctx.held.swap(true, Ordering::SeqCst) {
                (ctx.emit_down)();
            } else if !is_down && ctx.held.swap(false, Ordering::SeqCst) {
                (ctx.emit_up)();
            }
        }
        CG_EVENT_KEY_DOWN if kc == KEY_ESCAPE => {
            (ctx.emit_esc)();
        }
        _ => {}
    }

    event // listen-only: return event unmodified
}

// ── Public API ────────────────────────────────────────────────────────────────
pub fn start_hotkey_listener<R: Runtime>(app: AppHandle<R>) {
    std::thread::spawn(move || {
        let ctx = Box::new(TapCtx {
            emit_down: Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-ropt-down", ()); } }),
            emit_up:   Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-ropt-up",   ()); } }),
            emit_esc:  Box::new({ let a = app.clone(); move || { let _ = a.emit("hotkey-esc",        ()); } }),
            held:      AtomicBool::new(false),
        });
        let ctx_ptr = Box::into_raw(ctx) as *mut std::ffi::c_void;

        // Bitmask of event types to intercept
        let mask: u64 = (1 << CG_EVENT_FLAGS_CHANGED) | (1 << CG_EVENT_KEY_DOWN);

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
            eprintln!("[hotkey] CGEventTap active — Right Option + Esc monitored globally");
            CFRunLoopRun(); // blocks this thread; tap stays live until process exits
        }
    });
}
