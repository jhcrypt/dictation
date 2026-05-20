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
 * Also listens for:
 *   tray-start-dictation / tray-stop-dictation → tray menu actions
 *   ui-stop-recording → DictationPage stop button when hotkey started session
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
  /** paste_text call duration */
  pasteMs?: number;
  /** key-up to paste completed */
  totalAfterReleaseMs?: number;
  /** key-down to paste completed */
  totalCycleMs?: number;
  profile?: string;
  status?: string;
  updatedAt?: number;
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

  // ── Timing checkpoints (wall-clock ms) ──────────────────────────────────────
  const t_keyDown    = useRef<number>(0); // hotkey pressed
  const t_stopCalled = useRef<number>(0); // key-up / stop requested
  const t_stopDone   = useRef<number>(0); // sidecar_stop_recording returned

  useEffect(() => { settingsRef.current = settings; }, [settings]);

  useEffect(() => {
    // ── Helpers ──────────────────────────────────────────────────────────────

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

    const startRecording = async () => {
      if (stateRef.current !== "idle") {
        console.log("[recording] startRecording ignored — state =", stateRef.current);
        return;
      }

      console.log("[recording] → starting");
      stateRef.current  = "starting";
      pendingStopRef.current = false;
      recordStartRef.current = Date.now();
      t_keyDown.current = recordStartRef.current;
      cycleIdRef.current += 1; // invalidate any previous in-flight stopAndTranscribe

      const toggleMode = settingsRef.current.toggle_mode;
      hudEmit({ state: "recording", toggleMode });

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
        stateRef.current = "idle";
        setError(String(e));
        return;
      }

      // Check if a stop/cancel was requested while the start was in-flight
      if (pendingStopRef.current) {
        console.log("[recording] pendingStop set — cancelling immediately after start");
        pendingStopRef.current = false;
        clearRecordingTimeout();
        stateRef.current = "idle";
        hudEmit({ state: "tap_ignored" });
        setTimeout(() => hudEmit({ state: "idle" }), 2500);
        try {
          await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        } catch (e) {
          console.warn("[sidecar] cancel_recording error (ignored):", e);
        }
        return;
      }

      // Advance to live-recording state
      console.log("[recording] → recording");
      stateRef.current = "recording";
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
      stateRef.current = "stopping";
      t_stopCalled.current = Date.now();
      hudEmit({ state: "transcribing" });

      try {
        console.log("[sidecar] stop_recording →");
        await invokeWithTimeout("sidecar_stop_recording", undefined, 8_000);
        console.log("[sidecar] stop_recording ✓");
      } catch (e) {
        // Guard: a new cycle may have started while we awaited stop_recording
        if (cycleIdRef.current !== myCycle) {
          console.log("[recording] stop_recording error discarded — stale cycle", myCycle);
          return;
        }
        console.error("[sidecar] stop_recording FAILED:", e);
        stateRef.current = "idle";
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
          ok: boolean; text: string;
          timing: { whisper: number; ollama: number; total: number };
          error?: string;
          profile?: string;
          status?: string;
          skipped_cleanup?: boolean;
          skip_reason?: string;
        }>("sidecar_transcribe_last", undefined, 120_000);
        console.log("[sidecar] transcribe_last ✓  ok=", result.ok, "chars=", result.text?.length);

        // Guard: bail if a new recording cycle started while transcribe_last was in-flight
        if (cycleIdRef.current !== myCycle) {
          console.log("[recording] transcribe_last result discarded — stale cycle", myCycle);
          return;
        }

        if (result.ok && result.text) {
          const s = settingsRef.current;

          if (!result.skipped_cleanup && s.use_ollama && s.ai_cleanup_mode !== "off") {
            hudEmit({ state: "cleanup" });
            await new Promise((r) => setTimeout(r, 600));
          }

          if (result.skipped_cleanup && result.skip_reason) {
            hudEmit({ state: "skipped", subtext: result.skip_reason });
            await new Promise((r) => setTimeout(r, 1500));
          }

          let pasteStatus = "transcribed";
          const t_pasteStart = Date.now();
          let   t_pasteEnd   = t_pasteStart;
          if (!s.safe_mode) {
            try {
              await invokeWithTimeout("paste_text", { text: result.text }, 8_000);
              t_pasteEnd = Date.now();
              pasteStatus = "pasted";
              console.log("[paste] pasted", result.text.length, "chars");
            } catch (pe) {
              t_pasteEnd = Date.now();
              pasteStatus = "paste_failed";
              console.error("[paste] failed:", pe);
            }
          } else {
            t_pasteEnd = t_pasteStart; // safe mode: no paste
          }

          // Guard after paste: another cycle may have started during paste_text
          if (cycleIdRef.current !== myCycle) {
            console.log("[recording] paste done — stale cycle", myCycle, "discarding HUD update");
            return;
          }

          const profile = result.profile ?? s.writing_profile ?? "General";
          hudEmit({
            state:   "inserted",
            subtext: result.text.slice(0, 55),
            status:  pasteStatus,
            profile: s.show_active_profile ? profile : undefined,
          });

          // ── Store last dictated text for "Add Correction" tray item ─────────
          try {
            const { emit } = await import("@tauri-apps/api/event");
            emit("last-dictation-text", result.text);
          } catch { /* non-critical */ }

          // ── Emit full timing breakdown (non-blocking, after paste) ───────────
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
            totalAfterReleaseMs: t_pasteEnd - t_stopCalled.current,
            totalCycleMs:        t_pasteEnd - t_keyDown.current,
            profile,
            status:              pasteStatus,
            updatedAt:           Date.now(),
          };

          try {
            const { emit } = await import("@tauri-apps/api/event");
            emit("dictation-timing", timingPayload);
          } catch { /* non-critical */ }

          try {
            await invokeWithTimeout("save_history_entry", {
              entry: {
                timestamp:  new Date().toISOString(),
                final_text: result.text,
                status:     pasteStatus,
                profile,
                source:     "tauri",
                timing:     result.timing ?? null,
              },
            }, 5_000);
          } catch { /* non-critical */ }

          setTimeout(() => hudEmit({ state: "idle" }), 1500);
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

      if (st === "starting") {
        // Can't cancel mid-start safely — mark pending, startRecording will cancel
        pendingStopRef.current = true;
        hudEmit({ state: "tap_ignored" });
        setTimeout(() => hudEmit({ state: "idle" }), 2500);
        return;
      }

      // state === "recording" — cancel now
      stateRef.current = "idle";
      hudEmit({ state: "tap_ignored" });
      setTimeout(() => hudEmit({ state: "idle" }), 2500);
      try {
        await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        console.log("[sidecar] cancel_recording ✓");
      } catch (e) {
        console.warn("[sidecar] cancel_recording error (ignored):", e);
      }
    };

    const cancelRecording = async () => {
      if (!isActive()) {
        console.log("[recording] cancelRecording ignored — state =", stateRef.current);
        return;
      }

      const st = stateRef.current;
      console.log("[recording] cancel — state was", st);
      clearRecordingTimeout();

      if (st === "starting") {
        pendingStopRef.current = true; // let startRecording clean up
        hudEmit({ state: "idle" });
        return;
      }

      stateRef.current = "idle";
      hudEmit({ state: "idle" });
      try {
        await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
        console.log("[sidecar] cancel_recording ✓");
      } catch (e) {
        console.warn("[sidecar] cancel_recording error (ignored):", e);
      }
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
        console.log("[hotkey] ropt-up  toggle_mode=", tm, " state=", st);

        if (tm) return; // toggle mode: release is always ignored

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

      // DictationPage start button → same path as hotkey / tray
      listen("ui-start-recording", () => {
        console.log("[ui] ui-start-recording  state=", stateRef.current);
        startRecording();
      }).then(f => unlisteners.push(f));

      // DictationPage stop button → same path as hotkey / tray
      listen("ui-stop-recording", () => {
        const st = stateRef.current;
        console.log("[ui] ui-stop-recording  state=", st);
        if (st === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));

    }).catch(() => {});

    return () => {
      clearRecordingTimeout();
      unlisteners.forEach(u => u());
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
