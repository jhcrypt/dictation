/**
 * useGlobalHotkey
 *
 * Listens for Tauri events from the Rust CGEventTap:
 *   hotkey-ropt-down  → Right Option pressed
 *   hotkey-ropt-up    → Right Option released
 *   hotkey-esc        → Escape pressed
 *
 * Hold mode  (toggle_mode = false):
 *   key-down = start recording
 *   key-up   = stop + transcribe  (or tap_ignored if < hotkey_debounce_seconds)
 *
 * Toggle mode (toggle_mode = true):
 *   key-down when idle      = start recording
 *   key-down when recording = stop + transcribe
 *   key-up is IGNORED
 *
 * State machine
 * ─────────────
 *   idle  ──start──►  starting  ──sidecar OK──►  recording  ──stop──►  stopping  ──►  transcribing  ──►  idle
 *                         │                          │
 *                    cancel/tap                cancel/esc/tap
 *                         │                          │
 *                        idle ◄──────────────────── idle
 *
 * Rules:
 *   • startRecording   only from "idle"
 *   • stopAndTranscribe only from "recording"
 *   • cancel / handleShortTap from "starting" OR "recording"
 *   • all other states → ignore the incoming event
 *   • pendingStop flag: set when key is released while still "starting";
 *     startRecording checks it after sidecar_start_recording resolves and
 *     immediately cancels (the user released before start finished).
 *
 * ── ONE RECORDING CONTROLLER ─────────────────────────────────────────────────
 * All recording triggers MUST go through this hook. No UI page, tray handler,
 * or future feature may call sidecar_start/stop/cancel/transcribe_last directly.
 *
 * Trigger → event → handler in this file:
 *   Hotkey key-down/up  → hotkey-ropt-down / hotkey-ropt-up  (Rust CGEventTap)
 *   Dictation button    → ui-start-recording / ui-stop-recording  (DictationPage)
 *   Tray menu           → tray-start-dictation / tray-stop-dictation  (tray.rs)
 *   Jarvis wake-word    → emit "ui-start-recording" from wake handler (future)
 *
 * Adding a new trigger: emit one of the four events above. Do not invoke
 * sidecar_start_recording / sidecar_stop_recording / sidecar_transcribe_last
 * from anywhere other than this file.
 *
 * ── CRITICAL PERFORMANCE ORDER (fast path) ──────────────────────────────────
 * After transcribe_last returns, the fast path MUST be:
 *   1. paste text
 *   2. everything else (HUD, history, timing) — fire-and-forget, never awaited
 *
 * This matches the Python app which pastes FIRST, then saves history and
 * updates UI asynchronously.  Any HUD animation (skipped/cleanup/inserted)
 * that runs before paste will ADD visible lag.
 */
import { useEffect, useRef } from "react";
import { useSettings } from "../context/SettingsContext";
import type { HudPayload } from "../HudApp";

type RecState =
  | "idle"         // nothing happening
  | "starting"     // sidecar_start_recording in-flight
  | "recording"    // mic is live
  | "stopping"     // sidecar_stop_recording in-flight
  | "transcribing" // sidecar_transcribe_last in-flight
  | "error";       // transient — resets to idle after timeout

/**
 * Default minimum hold time (ms). Matches Python HOTKEY_DEBOUNCE_SECONDS default.
 * The live value is always read from settingsRef.current.hotkey_debounce_seconds.
 */
const DEFAULT_DEBOUNCE_MS = 180; // 0.18 s — same as Python default

/**
 * Timing breakdown emitted after each dictation cycle.
 * Broadcast via "dictation-timing" Tauri event → DictationPage card.
 */
export interface DictationTiming {
  model?: string;
  /** Key-down to key-up (hold duration) */
  recordingMs?: number;
  /** key-up to stop_recording returned (WAV save + sidecar overhead) */
  stopMs?: number;
  /** Whisper inference time (from sidecar) */
  transcriptionMs?: number;
  /** Ollama cleanup time ms (from sidecar); undefined if skipped */
  cleanupMs?: number;
  /** "done" | "skipped" | "off" */
  cleanupStatus?: string;
  /** paste_text total call duration */
  pasteMs?: number;
  /** Paste substeps — from PasteTiming returned by paste_text command */
  paste_save_ms?: number;
  paste_activate_ms?: number;
  paste_write_ms?: number;
  paste_cmd_v_ms?: number;
  paste_post_wait_ms?: number;
  paste_restore_ms?: number;
  paste_skipped_activate?: boolean;
  /** key-up to paste completed */
  totalAfterReleaseMs?: number;
  /** key-down to paste completed */
  totalCycleMs?: number;
  profile?: string;
  status?: string;
  updatedAt?: number;
}

type CustomCommandAction = "open_url" | "open_app" | "type_text";
interface RuntimeCustomCommand {
  trigger: string;
  action: CustomCommandAction;
  target: string;
}

export function useGlobalHotkey() {
  const { settings } = useSettings();
  const stateRef      = useRef<RecState>("idle");
  const settingsRef   = useRef(settings);
  const timeoutRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recordStartRef = useRef<number>(0);
  /**
   * pendingStop: set in hold mode when the key is released while state is
   * still "starting" (sidecar_start_recording hasn't returned yet).
   * startRecording checks this flag after the call resolves and immediately
   * cancels instead of advancing to "recording".
   */
  const pendingStopRef = useRef<boolean>(false);

  /**
   * cycleIdRef: monotonically incremented each time startRecording begins.
   * stopAndTranscribe captures the cycle ID at entry and silently drops
   * any HUD updates or state mutations if the ID has changed (stale cycle).
   */
  const cycleIdRef = useRef<number>(0);

  /**
   * isWakeRecordingRef: set when recording was triggered by the wake word.
   * Causes ropt-up to always stop+transcribe (no short-tap cancel) so the
   * user can press ⌥ once to stop, regardless of hold/toggle setting.
   * Cleared when recording ends (stop, cancel, or error).
   */
  const isWakeRecordingRef = useRef<boolean>(false);

  /**
   * wakeMonitorRef: holds the setInterval ID for the wake auto-stop monitor.
   * Started after wake recording begins; cleared by clearWakeMonitor() in
   * every stop/cancel path and by the monitor itself on any state mismatch.
   */
  const wakeMonitorRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Timing checkpoints (wall-clock ms) ──────────────────────────────────────
  const t_keyDown    = useRef<number>(0); // hotkey pressed
  const t_stopCalled = useRef<number>(0); // key-up / stop requested
  const t_stopDone   = useRef<number>(0); // sidecar_stop_recording returned

  useEffect(() => { settingsRef.current = settings; }, [settings]);

  useEffect(() => {
    // ── Helpers ──────────────────────────────────────────────────────────────

    /** Play a recording sound if the user has play_sounds enabled. Fire-and-forget. */
    const playSound = (kind: "start" | "stop" | "cancel") => {
      if (settingsRef.current.play_sounds !== true) return;
      import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("play_recording_sound", { kind }).catch(() => {}))
        .catch(() => {});
    };

    /** Match Python parity: suppress media while recording. Fire-and-forget. */
    const pauseMedia = () => {
      import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("pause_media").catch((e) => console.warn("[media] pause_media failed:", e)))
        .catch(() => {});
    };

    /** Restore media after stop/cancel/start failure. Fire-and-forget. */
    const resumeMedia = () => {
      import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("resume_media").catch((e) => console.warn("[media] resume_media failed:", e)))
        .catch(() => {});
    };

    const hudEmit = async (payload: HudPayload) => {
      try {
        const { emit } = await import("@tauri-apps/api/event");
        emit("hud-state", payload);
      } catch { /* browser preview */ }
    };

    const invokeWithTimeout = async <T>(
      cmd: string,
      args?: Record<string, unknown>,
      timeoutMs = 20_000,
    ): Promise<T> => {
      const { invoke: inv } = await import("@tauri-apps/api/core");
      const timeoutP = new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error(`${cmd} timed out after ${timeoutMs}ms`)), timeoutMs),
      );
      return Promise.race([inv<T>(cmd, args), timeoutP]);
    };

    const clearRecordingTimeout = () => {
      if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
    };

    /** Clear the wake auto-stop monitor interval (safe to call when null). */
    const clearWakeMonitor = () => {
      if (wakeMonitorRef.current) { clearInterval(wakeMonitorRef.current); wakeMonitorRef.current = null; }
    };

    const normalizeTrigger = (text: string) =>
      text.trim().toLowerCase().replace(/[.,!?]+$/g, "");

    const runCustomCommand = async (spokenText: string): Promise<{
      matched: boolean;
      pasteText?: string;
      status?: string;
      subtext?: string;
    }> => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const cmds = await invoke<RuntimeCustomCommand[]>("load_custom_commands");
        if (!Array.isArray(cmds) || cmds.length === 0) return { matched: false };

        const lower = normalizeTrigger(spokenText);
        const match = cmds.find((cmd) => {
          const trig = normalizeTrigger(String(cmd?.trigger ?? ""));
          return trig.length > 0 && trig.split(/\s+/).length >= 2 && trig === lower;
        });
        if (!match) return { matched: false };

        if (match.action === "open_url") {
          await invoke("open_url", { url: match.target });
          return { matched: true, status: "custom_command", subtext: `Opened ${match.target}` };
        }
        if (match.action === "open_app") {
          await invoke("open_app", { appName: match.target });
          return { matched: true, status: "custom_command", subtext: `Opened ${match.target}` };
        }
        if (match.action === "type_text") {
          return { matched: true, pasteText: match.target, status: "custom_command", subtext: match.target.slice(0, 55) };
        }

        return { matched: false };
      } catch (e) {
        console.warn("[custom-command] runtime dispatch failed:", e);
        return { matched: false };
      }
    };

    // ── State helpers ─────────────────────────────────────────────────────────

    const isActive = () =>
      stateRef.current === "starting" || stateRef.current === "recording";

    const setError = (msg: string) => {
      stateRef.current = "error";
      hudEmit({ state: "error", subtext: msg });
      setTimeout(() => {
        if (stateRef.current === "error") stateRef.current = "idle";
        hudEmit({ state: "idle" });
      }, 4000);
    };

    // ── Recording flow ────────────────────────────────────────────────────────

    const startRecording = async (source: "hotkey" | "button" | "tray" | "wake" = "hotkey") => {
      if (stateRef.current !== "idle") {
        console.log("[recording] startRecording ignored — state =", stateRef.current, "source =", source);
        return;
      }

      console.log("[recording] → starting  source =", source);
      stateRef.current  = "starting";
      pendingStopRef.current = false;
      recordStartRef.current = Date.now();
      t_keyDown.current = recordStartRef.current;
      cycleIdRef.current += 1; // invalidate any previous in-flight stopAndTranscribe

      // Wake-triggered recordings use the wake_recording HUD state and
      // always stop on a single ⌥ press (no short-tap cancel).
      isWakeRecordingRef.current = source === "wake";

      if (source === "wake") {
        hudEmit({ state: "wake_recording" });
      } else {
        const toggleMode = settingsRef.current.toggle_mode;
        hudEmit({ state: "recording", toggleMode });
      }

      // Python parity: suppress browser/music audio before opening the mic.
      pauseMedia();

      // Safety auto-stop: if still recording after 90 s, force a stop
      timeoutRef.current = setTimeout(() => {
        console.warn("[recording] 90 s safety timeout — forcing stop");
        if (stateRef.current === "recording") stopAndTranscribe();
      }, 90_000);

      try {
        console.log("[sidecar] start_recording →");
        await invokeWithTimeout("sidecar_start_recording", undefined, 10_000);
        console.log("[sidecar] start_recording ✓");
      } catch (e) {
        console.error("[sidecar] start_recording FAILED:", e);
        clearRecordingTimeout();
        pendingStopRef.current = false;
        isWakeRecordingRef.current = false;
        stateRef.current = "idle";
        resumeMedia();
        setError(String(e));
        return;
      }

      // Check if a stop/cancel was requested while the start was in-flight
      if (pendingStopRef.current) {
        console.log("[recording] pendingStop set — cancelling immediately after start");
        pendingStopRef.current = false;
        isWakeRecordingRef.current = false;
        clearRecordingTimeout();
        stateRef.current = "idle";
        hudEmit({ state: "tap_ignored" });
        setTimeout(() => hudEmit({ state: "idle" }), 2500);
        try {
          await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        } catch (e) {
          console.warn("[sidecar] cancel_recording error (ignored):", e);
        }
        resumeMedia();
        return;
      }

      // Play start sound on successful recording start
      playSound("start");

      // Advance to live-recording state
      console.log("[recording] → recording");
      stateRef.current = "recording";

      // ── Wake auto-stop monitor ─────────────────────────────────────────────
      // Only for wake-triggered recordings. Matches stable Python _silence_stop_monitor:
      //   1. grace period — never auto-stop before wake_dictation_grace_seconds
      //   2. voice_active poll — sidecar VAD distinguishes speech from fan/AC noise
      //   3. silence window — auto-stop after wake_dictation_silence_seconds with
      //                       no voice_active=true frames
      //   4. hard cap — force stop at wake_dictation_max_seconds regardless
      //
      // Uses voice_active (not raw RMS) so steady background noise cannot prevent
      // auto-stop after the user finishes speaking.
      // Normal Option-key recordings are unaffected (monitor only starts for "wake").
      if (source === "wake") {
        const wakeStartMs = Date.now();
        let silenceSinceMs: number | null = null;
        const graceMs   = (settingsRef.current.wake_dictation_grace_seconds   ?? 3.5) * 1000;
        const silenceMs = (settingsRef.current.wake_dictation_silence_seconds ?? 2.5) * 1000;
        const maxMs     = (settingsRef.current.wake_dictation_max_seconds     ?? 45.0) * 1000;

        clearWakeMonitor(); // defensive: clear any stale monitor
        wakeMonitorRef.current = setInterval(async () => {
          // Self-cancel if no longer a wake recording (manual ⌥ stop, cancel, error)
          if (!isWakeRecordingRef.current || stateRef.current !== "recording") {
            clearWakeMonitor();
            return;
          }

          const elapsed = Date.now() - wakeStartMs;

          // Hard max cap — matches Python wake_dictation_max_seconds
          if (elapsed >= maxMs) {
            console.log("[wake-monitor] max duration reached — auto-stopping");
            clearWakeMonitor();
            stopAndTranscribe();
            return;
          }

          // Grace period: silence detection is completely disabled for the first
          // graceMs so the opening words are never cut off.
          if (elapsed < graceMs) {
            silenceSinceMs = null;
            return;
          }

          // Poll voice activity from sidecar VAD
          try {
            const statusStr = await invokeWithTimeout<string>("sidecar_get_status", undefined, 2_000);
            const status = JSON.parse(statusStr) as {
              ok: boolean;
              recording: boolean;
              voice_active?: boolean;
            };

            if (!status.ok || !status.recording) {
              // Sidecar recording stopped unexpectedly — bail out silently
              clearWakeMonitor();
              return;
            }

            const voiceActive = status.voice_active ?? false;

            if (voiceActive) {
              // Voice detected — reset the silence window
              silenceSinceMs = null;
            } else {
              // Silent. The grace period above already guarantees we won't fire
              // before the user has had time to begin speaking, so there is no
              // need for a separate "has-ever-heard-voice" gate.  That gate made
              // wake_dictation_silence_seconds completely ineffective whenever
              // the VAD threshold wasn't crossed (quiet mic, noisy floor, etc.)
              // causing recordings to always run to the 45-second max cap.
              if (silenceSinceMs === null) silenceSinceMs = Date.now();
              else if (Date.now() - silenceSinceMs >= silenceMs) {
                console.log(
                  `[wake-monitor] silence for ${((Date.now() - silenceSinceMs) / 1000).toFixed(1)}s — auto-stopping`,
                );
                clearWakeMonitor();
                stopAndTranscribe();
              }
            }
          } catch (e) {
            console.warn("[wake-monitor] get_status error (ignored):", e);
          }
        }, 200);
      }
    };

    const stopAndTranscribe = async () => {
      if (stateRef.current !== "recording") {
        console.log("[recording] stopAndTranscribe ignored — state =", stateRef.current);
        return;
      }

      // Capture cycle ID before first await — any change means this result is stale.
      const myCycle = cycleIdRef.current;

      console.log("[recording] → stopping  cycle=", myCycle);
      clearRecordingTimeout();
      clearWakeMonitor();
      isWakeRecordingRef.current = false;
      playSound("stop");
      stateRef.current = "stopping";
      t_stopCalled.current = Date.now();
      hudEmit({ state: "transcribing" });

      try {
        console.log("[sidecar] stop_recording →");
        await invokeWithTimeout("sidecar_stop_recording", undefined, 8_000);
        console.log("[sidecar] stop_recording ✓");
        resumeMedia();
      } catch (e) {
        // Guard: a new cycle may have started while we awaited stop_recording
        if (cycleIdRef.current !== myCycle) {
          console.log("[recording] stop_recording error discarded — stale cycle", myCycle);
          return;
        }
        console.error("[sidecar] stop_recording FAILED:", e);
        stateRef.current = "idle";
        resumeMedia();
        setError(String(e));
        return;
      }

      // Guard: bail if a new recording cycle started while stop_recording was in-flight
      if (cycleIdRef.current !== myCycle) {
        console.log("[recording] stop_recording done — stale cycle", myCycle, "discarding");
        return;
      }

      t_stopDone.current = Date.now();
      stateRef.current = "transcribing";

      try {
        console.log("[sidecar] transcribe_last →");
        const result = await invokeWithTimeout<{
          ok: boolean; text: string | null;
          action?: string | null;
          backspace_count?: number;
          key?: string;
          with_shift?: boolean;
          repeat?: number;
          modifier?: string;
          nav_target?: string;
          // Jarvis system-command fields
          app_name?: string;
          url?: string;
          direction?: string;
          level?: number | null;
          screenshot_type?: string;
          force?: boolean;
          hud?: string | null;
          hud_color?: string;
          timing: { whisper: number; ollama: number; total: number };
          error?: string;
          profile?: string;
          status?: string;
          skipped_cleanup?: boolean;
          skip_reason?: string;
          // History enrichment
          whisper_text?: string | null;
          ollama_text?: string | null;
          active_app?: string | null;
        }>("sidecar_transcribe_last", undefined, 120_000);
        console.log("[sidecar] transcribe_last ✓  ok=", result.ok,
                    "action=", result.action, "chars=", result.text?.length);

        // Guard: bail if a new recording cycle started while transcribe_last was in-flight
        if (cycleIdRef.current !== myCycle) {
          console.log("[recording] transcribe_last result discarded — stale cycle", myCycle);
          return;
        }

        // ── Voice command dispatch ──────────────────────────────────────────
        // The sidecar detects command phrases (scratch, punct, format, nav…)
        // before the correction pipeline and returns action != null.
        if (result.ok && result.action) {
          const { invoke: inv } = await import("@tauri-apps/api/core");
          const { emit: ev }   = await import("@tauri-apps/api/event");
          const act = result.action;
          console.log("[cmd] dispatching action=", act);

          try {
            if (act === "scratch" || act === "format_paste") {
              const bc = result.backspace_count ?? 0;
              if (bc > 0) await inv("send_backspaces", { count: bc });
            }
            if ((act === "paste_text" || act === "format_paste") && result.text) {
              await invokeWithTimeout<{
                save_ms: number; activate_ms: number; write_ms: number;
                cmd_v_ms: number; post_wait_ms: number; restore_ms: number;
                total_ms: number; skipped_activate: boolean;
              }>("paste_text", { text: result.text }, 8_000);
            }
            if (act === "keypress") {
              await inv("send_keypress", {
                keyName:     result.key ?? "return",
                withShift:   result.with_shift ?? false,
                repeatCount: result.repeat ?? 1,
              });
            }
            if (act === "key_combo") {
              await inv("send_key_combo", {
                modifier: result.modifier ?? "cmd",
                key:      result.key ?? "a",
              });
            }
            if (act === "copy_text" && result.text) {
              await inv("copy_to_clipboard_str", { text: result.text });
            }
            if (act === "copy_all") {
              // Cmd+A then Cmd+C
              await inv("send_key_combo", { modifier: "cmd", key: "a" });
              await new Promise(r => setTimeout(r, 60));
              await inv("send_key_combo", { modifier: "cmd", key: "c" });
            }
            if (act === "navigate" && result.nav_target) {
              const evName = result.nav_target === "history"    ? "nav-history"
                           : result.nav_target === "vocabulary" ? "nav-vocabulary"
                           : null;
              if (evName) { ev(evName, {}); }
            }
            // ── Jarvis system commands ──────────────────────────────────────
            if (act === "open_app" && result.app_name) {
              await inv("open_app", { appName: result.app_name });
            }
            if (act === "open_url" && result.url) {
              await inv("open_url", { url: result.url });
            }
            if (act === "set_volume") {
              await inv("set_system_volume", {
                direction: result.direction ?? "up",
                level: result.level ?? null,
              });
            }
            if (act === "create_reminder" && result.text) {
              await inv("create_reminder", { text: result.text });
            }
            if (act === "take_screenshot") {
              await inv("trigger_shottr", { screenshotType: result.screenshot_type ?? "screen" });
            }
            if (act === "close_app" && result.app_name) {
              await inv("close_app", { appName: result.app_name, force: result.force ?? false });
            }
            // Snippet state notifications — HUD only, no keyboard action
            // act === "snippet_waiting_trigger" | "snippet_trigger_received" | "snippet_saved"
            // noop: just show HUD
          } catch (ce) {
            console.error("[cmd] dispatch error:", ce);
            // Surface actionable errors (e.g. Shottr not installed) in the HUD.
            const errMsg = String(ce);
            stateRef.current = "idle";
            hudEmit({ state: "error", subtext: errMsg });
            setTimeout(() => hudEmit({ state: "idle" }), 4500);
            return;
          }

          // HUD notification for command (fire-and-forget)
          if (result.hud) {
            hudEmit({ state: "command", subtext: result.hud })
              .then(() => setTimeout(() => hudEmit({ state: "idle" }), 1800))
              .catch(() => {});
          } else {
            hudEmit({ state: "idle" }).catch(() => {});
          }

          stateRef.current = "idle";
          return;
        }

        if (result.ok && result.text) {
          // ── SAFETY GUARD: never paste empty or whitespace-only text ────────
          // This prevents pasting stale clipboard contents when transcription
          // returns an empty result (e.g. audio too quiet, sidecar error).
          const trimmed = result.text.trim();
          if (trimmed.length === 0) {
            console.log("[dictation] empty transcript — skipping paste");
            stateRef.current = "idle";
            hudEmit({ state: "error", subtext: "Empty transcription" });
            setTimeout(() => hudEmit({ state: "idle" }), 3000);
            return;
          }

          const s = settingsRef.current;

          let custom: { matched: boolean; pasteText?: string; status?: string; subtext?: string } = { matched: false };
          if (settingsRef.current.jarvis_enabled === true) {
            custom = await runCustomCommand(trimmed);
            if (custom.matched && !custom.pasteText) {
              stateRef.current = "idle";
              hudEmit({ state: "inserted", subtext: custom.subtext ?? trimmed.slice(0, 55), status: custom.status ?? "custom_command" })
                .then(() => setTimeout(() => hudEmit({ state: "idle" }), 1200))
                .catch(() => {});
              return;
            }
          }

          const textToPaste = custom.pasteText ?? trimmed;

          // ── FAST PATH: paste FIRST, before any HUD/history/timing work ─────
          // Matches Python app: paste_text() happens before save_history() and
          // show_message().  No HUD animation or setTimeout blocks paste.

          type PasteTiming = {
            save_ms: number; activate_ms: number; write_ms: number;
            cmd_v_ms: number; post_wait_ms: number; restore_ms: number;
            total_ms: number; skipped_activate: boolean;
          };
          let pasteStatus = "transcribed";
          let pasteTiming: PasteTiming | null = null;
          const t_pasteStart = Date.now();
          let   t_pasteEnd   = t_pasteStart;
          if (!s.safe_mode) {
            try {
              console.log("[perf] paste_text sent");
              pasteTiming = await invokeWithTimeout<PasteTiming>("paste_text", { text: textToPaste }, 8_000);
              t_pasteEnd = Date.now();
              pasteStatus = "pasted";
              console.log(
                "[paste] save=%dms activate=%dms write=%dms cmd_v=%dms post_wait=%dms restore=%dms total=%dms skip_activate=%s",
                pasteTiming.save_ms, pasteTiming.activate_ms, pasteTiming.write_ms,
                pasteTiming.cmd_v_ms, pasteTiming.post_wait_ms, pasteTiming.restore_ms,
                pasteTiming.total_ms, pasteTiming.skipped_activate,
              );
            } catch (pe) {
              t_pasteEnd = Date.now();
              pasteStatus = "paste_failed";
              console.error("[paste] failed:", pe);
            }
          } else {
            t_pasteEnd = t_pasteStart; // safe mode: no paste
          }

          // ── AFTER PASTE: everything is fire-and-forget, never awaited ──────
          // HUD update, history save, timing emission all happen after paste
          // and do not block the user from continuing.

          const profile = result.profile ?? s.writing_profile ?? "General";

          // HUD "inserted" state — fire-and-forget
          hudEmit({
            state:   "inserted",
            subtext: textToPaste.slice(0, 55),
            status:  custom.status ?? pasteStatus,
            profile: s.show_active_profile ? profile : undefined,
          }).then(() => {
            setTimeout(() => hudEmit({ state: "idle" }), 1500);
          }).catch(() => {});

          // HUD skipped/cleanup state — fire-and-forget AFTER insert
          // This replaces the blocking 1.5s setTimeout that was blocking paste.
          if (result.skipped_cleanup && result.skip_reason) {
            setTimeout(() => {
              hudEmit({ state: "skipped", subtext: result.skip_reason }).catch(() => {});
            }, 300);
          }

          // ── Store last dictated text for "Add Correction" tray item ─────────
          try {
            const { emit } = await import("@tauri-apps/api/event");
            emit("last-dictation-text", result.text);
          } catch { /* non-critical */ }

          // ── Emit full timing breakdown (fire-and-forget) ────────────────────
          const cleanupStatus =
            s.ai_cleanup_mode === "off" ? "off" :
            result.skipped_cleanup      ? "skipped" :
            result.timing.ollama > 0   ? "done" : "skipped";

          const timingPayload: DictationTiming = {
            model:               s.model,
            recordingMs:         t_stopCalled.current - t_keyDown.current,
            stopMs:              t_stopDone.current   - t_stopCalled.current,
            transcriptionMs:     result.timing.whisper,
            cleanupMs:           result.timing.ollama > 0 ? result.timing.ollama : undefined,
            cleanupStatus,
            pasteMs:             s.safe_mode ? undefined : (t_pasteEnd - t_pasteStart),
            // Paste substeps (from Rust PasteTiming)
            paste_save_ms:          pasteTiming?.save_ms,
            paste_activate_ms:      pasteTiming?.activate_ms,
            paste_write_ms:         pasteTiming?.write_ms,
            paste_cmd_v_ms:         pasteTiming?.cmd_v_ms,
            paste_post_wait_ms:     pasteTiming?.post_wait_ms,
            paste_restore_ms:       pasteTiming?.restore_ms,
            paste_skipped_activate: pasteTiming?.skipped_activate,
            totalAfterReleaseMs: t_pasteEnd - t_stopCalled.current,
            totalCycleMs:        t_pasteEnd - t_keyDown.current,
            profile,
            status:              pasteStatus,
            updatedAt:           Date.now(),
          };

          try {
            const { emit } = await import("@tauri-apps/api/event");
            console.log("[perf] timing event emitted  totalAfterReleaseMs=", timingPayload.totalAfterReleaseMs);
            emit("dictation-timing", timingPayload);
          } catch { /* non-critical */ }

          // Resolve target app name for history (fire-and-forget, non-blocking)
          // get_last_target_app returns "AppName (bundle.id)" — strip bundle suffix
          const resolveApp = async (): Promise<string> => {
            try {
              const { invoke: inv2 } = await import("@tauri-apps/api/core");
              const info = await inv2<string | null>("get_last_target_app");
              if (info) return info.replace(/\s*\([^)]+\)\s*$/, "").trim();
            } catch { /* ignore */ }
            return result.active_app ?? "";
          };

          // History save — fire-and-forget (not awaited)
          resolveApp().then((appName) => {
            invokeWithTimeout("save_history_entry", {
              entry: {
                timestamp:    new Date().toISOString(),
                app:          appName,
                final_text:   textToPaste,
                status:       custom.status ?? pasteStatus,
                profile,
                source:       "tauri",
                timing:       result.timing ?? null,
                whisper_text: result.whisper_text ?? null,
                ollama_text:  result.ollama_text  ?? null,
              },
            }, 5_000).catch(() => {});
          }).catch(() => {});

        } else {
          // Guard before showing error: don't clobber a new cycle's HUD
          if (cycleIdRef.current !== myCycle) {
            console.log("[recording] transcription failed result discarded — stale cycle", myCycle);
            return;
          }
          const errMsg = result.error ?? "Transcription failed";
          console.error("[sidecar] transcription failed:", errMsg);
          hudEmit({ state: "error", subtext: errMsg });
          setTimeout(() => hudEmit({ state: "idle" }), 4000);
        }
      } catch (e) {
        // Guard before showing error: don't clobber a new cycle's HUD
        if (cycleIdRef.current !== myCycle) {
          console.log("[recording] transcribe_last exception discarded — stale cycle", myCycle);
          return;
        }
        console.error("[sidecar] transcribe error:", e);
        hudEmit({ state: "error", subtext: String(e) });
        setTimeout(() => hudEmit({ state: "idle" }), 4000);
      }

      stateRef.current = "idle";
    };

    /**
     * handleShortTap — hold mode only.
     * Called when key is released within hotkey_debounce_seconds.
     *
     * If state is "starting": the sidecar call is still in-flight.
     *   Set pendingStop so startRecording cancels after the call returns.
     *
     * If state is "recording": sidecar is live.
     *   Cancel immediately.
     */
    const handleShortTap = async () => {
      const st = stateRef.current;
      if (st !== "starting" && st !== "recording") return;

      console.log("[recording] short tap — state was", st);
      clearRecordingTimeout();
      clearWakeMonitor();

      if (st === "starting") {
        // Can't cancel mid-start safely — mark pending, startRecording will cancel
        pendingStopRef.current = true;
        hudEmit({ state: "tap_ignored" });
        setTimeout(() => hudEmit({ state: "idle" }), 2500);
        return;
      }

      // state === "recording" — cancel now
      playSound("cancel");
      stateRef.current = "idle";
      hudEmit({ state: "tap_ignored" });
      setTimeout(() => hudEmit({ state: "idle" }), 2500);
      try {
        await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        console.log("[sidecar] cancel_recording ✓");
      } catch (e) {
        console.warn("[sidecar] cancel_recording error (ignored):", e);
      }
      resumeMedia();
    };

    const cancelRecording = async () => {
      if (!isActive()) {
        console.log("[recording] cancelRecording ignored — state =", stateRef.current);
        return;
      }

      const st = stateRef.current;
      console.log("[recording] cancel — state was", st);
      clearRecordingTimeout();
      clearWakeMonitor();
      isWakeRecordingRef.current = false;

      if (st === "starting") {
        pendingStopRef.current = true; // let startRecording clean up
        hudEmit({ state: "idle" });
        return;
      }

      playSound("cancel");
      stateRef.current = "idle";
      hudEmit({ state: "idle" });
      try {
        await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        console.log("[sidecar] cancel_recording ✓");
      } catch (e) {
        console.warn("[sidecar] cancel_recording error (ignored):", e);
      }
      resumeMedia();
    };

    // ── Event listeners ───────────────────────────────────────────────────────

    const unlisteners: Array<() => void> = [];

    import("@tauri-apps/api/event").then(({ listen }) => {

      // Right Option DOWN
      listen("hotkey-ropt-down", () => {
        const tm  = settingsRef.current.toggle_mode;
        const st  = stateRef.current;
        console.log("[hotkey] ropt-down  toggle_mode=", tm, " state=", st);

        if (tm) {
          // Toggle mode: down toggles idle↔recording, all other states ignored
          if (st === "idle")      startRecording();
          else if (st === "recording") stopAndTranscribe();
        } else {
          // Hold mode: down always means "start" — guard inside startRecording
          startRecording();
        }
      }).then(f => unlisteners.push(f));

      // Right Option UP
      listen("hotkey-ropt-up", () => {
        const tm  = settingsRef.current.toggle_mode;
        const st  = stateRef.current;
        console.log("[hotkey] ropt-up  toggle_mode=", tm, " state=", st,
                    " isWake=", isWakeRecordingRef.current);

        if (tm) return; // toggle mode: release is always ignored

        // Wake-triggered recordings: a single ⌥ press always stops.
        // Skip short-tap logic so the user doesn't accidentally cancel.
        if (isWakeRecordingRef.current && st === "recording") {
          stopAndTranscribe();
          return;
        }

        // Hold mode: up = stop (unless it was a short tap)
        const elapsed = Date.now() - recordStartRef.current;
        // Read threshold live from settings (matches Python _setting_float("hotkey_debounce_seconds"))
        const debounceMs = (settingsRef.current.hotkey_debounce_seconds ?? DEFAULT_DEBOUNCE_MS / 1000) * 1000;
        console.log("[hotkey] hold duration =", elapsed, "ms  threshold =", debounceMs, "ms");

        if (st === "starting") {
          // Start not yet complete — set pendingStop regardless of elapsed
          // (the user lifted before the sidecar even started; always treat as short tap)
          handleShortTap();
        } else if (st === "recording") {
          if (elapsed < debounceMs) {
            handleShortTap();
          } else {
            stopAndTranscribe();
          }
        }
        // stopping/transcribing/error/idle → ignore
      }).then(f => unlisteners.push(f));

      // Escape — cancel
      listen("hotkey-esc", () => {
        console.log("[hotkey] esc  state=", stateRef.current);
        cancelRecording();
      }).then(f => unlisteners.push(f));

      // Tray — start dictation
      listen("tray-start-dictation", () => {
        console.log("[tray] start-dictation  state=", stateRef.current);
        startRecording();
      }).then(f => unlisteners.push(f));

      // Tray — stop/cancel dictation
      listen("tray-stop-dictation", () => {
        const st = stateRef.current;
        console.log("[tray] stop-dictation  state=", st);
        if (st === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));

      // UI start (button) → same guarded path as hotkey
      listen("ui-start-recording", () => {
        console.log("[ui] ui-start-recording  state=", stateRef.current);
        startRecording("button");
      }).then(f => unlisteners.push(f));

      // UI stop (button) → same guarded path as hotkey
      listen("ui-stop-recording", () => {
        const st = stateRef.current;
        console.log("[ui] ui-stop-recording  state=", st);
        if (st === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));

      // Jarvis wake-word detected → same guarded startRecording path
      // Uses wake_recording HUD state + single-press stop behavior
      listen("wake-detected", () => {
        console.log("[wake] wake-detected  state=", stateRef.current);
        startRecording("wake");
      }).then(f => unlisteners.push(f));

    }).catch(() => {});

    return () => {
      clearRecordingTimeout();
      unlisteners.forEach(u => u());
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}