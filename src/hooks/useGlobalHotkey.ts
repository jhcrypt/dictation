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
 *   key-up   = stop + transcribe  (or tap_ignored if < MIN_TAP_MS)
 *
 * Toggle mode (toggle_mode = true):
 *   key-down when idle      = start recording
 *   key-down when recording = stop + transcribe
 *   key-up is IGNORED
 *
 * Tap detection (hold mode only):
 *   If Right Option is released within MIN_TAP_MS (300 ms) of being pressed,
 *   the recording is cancelled and HUD shows "Tap ignored — hold a little longer"
 *   for 2.5 s, matching the Python app's MIN_RECORD_SECONDS = 0.30 guard.
 *
 * Also listens for:
 *   tray-start-dictation / tray-stop-dictation → tray menu actions
 *   ui-stop-recording → DictationPage stop button when hotkey started session
 */
import { useEffect, useRef } from "react";
import { useSettings } from "../context/SettingsContext";
import type { HudPayload } from "../HudApp";

type RecState = "idle" | "recording" | "transcribing";

/** Minimum hold time before a release is treated as a real recording (ms). */
const MIN_TAP_MS = 300;

export function useGlobalHotkey() {
  const { settings } = useSettings();
  const stateRef       = useRef<RecState>("idle");
  const settingsRef    = useRef(settings);
  const timeoutRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recordStartRef = useRef<number>(0);  // timestamp when recording began

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

    // ── Recording flow ────────────────────────────────────────────────────────

    const startRecording = async () => {
      if (stateRef.current !== "idle") {
        console.log("[recording] startRecording called but state =", stateRef.current, "— ignored");
        return;
      }
      console.log("[recording] start requested");
      stateRef.current = "recording";
      recordStartRef.current = Date.now();

      const toggleMode = settingsRef.current.toggle_mode;
      hudEmit({
        state:      "recording",
        toggleMode,
        // subtext is derived in HudApp from toggleMode flag
      });

      // Safety auto-stop after 90 s
      timeoutRef.current = setTimeout(() => {
        console.warn("[recording] 90-second safety timeout — forcing stop");
        stopAndTranscribe();
      }, 90_000);

      try {
        console.log("[sidecar] start_recording →");
        await invokeWithTimeout("sidecar_start_recording", undefined, 10_000);
        console.log("[sidecar] start_recording ✓");
      } catch (e) {
        console.error("[sidecar] start_recording FAILED:", e);
        clearRecordingTimeout();
        stateRef.current = "idle";
        hudEmit({ state: "error", subtext: String(e) });
        setTimeout(() => hudEmit({ state: "idle" }), 4000);
      }
    };

    const stopAndTranscribe = async () => {
      if (stateRef.current !== "recording") {
        console.log("[recording] stopAndTranscribe called but state =", stateRef.current, "— ignored");
        return;
      }
      console.log("[recording] stop requested");
      clearRecordingTimeout();
      stateRef.current = "transcribing";
      hudEmit({ state: "transcribing" });

      try {
        console.log("[sidecar] stop_recording →");
        await invokeWithTimeout("sidecar_stop_recording", undefined, 8_000);
        console.log("[sidecar] stop_recording ✓");

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

        if (result.ok && result.text) {
          const s = settingsRef.current;

          // Cleanup state: show briefly only when Ollama actually ran
          if (!result.skipped_cleanup && s.use_ollama && s.ai_cleanup_mode !== "off") {
            hudEmit({ state: "cleanup" });
            await new Promise((r) => setTimeout(r, 600));
          }

          // Skipped cleanup: match Python messages by skip_reason
          if (result.skipped_cleanup && result.skip_reason) {
            hudEmit({ state: "skipped", subtext: result.skip_reason });
            await new Promise((r) => setTimeout(r, 1500));
          }

          let pasteStatus = "transcribed";
          if (!s.safe_mode) {
            try {
              await invokeWithTimeout("paste_text", { text: result.text }, 8_000);
              pasteStatus = "pasted";
              console.log("[paste] pasted", result.text.length, "chars");
            } catch (pe) {
              pasteStatus = "paste_failed";
              console.error("[paste] failed:", pe);
            }
          }

          const profile = result.profile ?? s.writing_profile ?? "General";
          console.log("[hud] → inserted  status=", pasteStatus, "profile=", profile);

          // "inserted" = Python's set_transcript — green check, text preview
          hudEmit({
            state:   "inserted",
            subtext: result.text.slice(0, 55),
            status:  pasteStatus,
            profile: s.show_active_profile ? profile : undefined,
          });

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

          // Return to idle after 1.5 s, matching Python's `time.sleep(1.5); app.set_state("idle")`
          setTimeout(() => hudEmit({ state: "idle" }), 1500);
        } else {
          const errMsg = result.error ?? "Transcription failed";
          console.error("[sidecar] transcription failed:", errMsg);
          hudEmit({ state: "error", subtext: errMsg });
          setTimeout(() => hudEmit({ state: "idle" }), 4000);
        }
      } catch (e) {
        console.error("[sidecar] stop/transcribe error:", e);
        hudEmit({ state: "error", subtext: String(e) });
        setTimeout(() => hudEmit({ state: "idle" }), 4000);
      }

      stateRef.current = "idle";
    };

    /**
     * Short-tap handler (hold mode only):
     * If the key was released within MIN_TAP_MS of being pressed, cancel the
     * recording and show "Tap ignored — hold a little longer" for 2.5 s.
     * Matches Python's MIN_RECORD_SECONDS = 0.30 guard in _finish_short_recording().
     */
    const handleShortTap = async () => {
      if (stateRef.current !== "recording") return;
      console.log("[recording] short tap — cancelling, showing tap_ignored");
      clearRecordingTimeout();
      stateRef.current = "idle";
      hudEmit({ state: "tap_ignored" });
      setTimeout(() => hudEmit({ state: "idle" }), 2500);
      try {
        await invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000);
      } catch (e) {
        console.warn("[sidecar] cancel_recording error (ignored):", e);
      }
    };

    const cancelRecording = async () => {
      if (stateRef.current !== "recording") {
        console.log("[recording] cancelRecording called but state =", stateRef.current);
        return;
      }
      console.log("[recording] cancel");
      clearRecordingTimeout();
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
        const tm = settingsRef.current.toggle_mode;
        console.log("[hotkey] right option down  toggle_mode=", tm, " state=", stateRef.current);
        if (tm) {
          if (stateRef.current === "idle")           startRecording();
          else if (stateRef.current === "recording") stopAndTranscribe();
          // transcribing → ignore
        } else {
          startRecording();
        }
      }).then(f => unlisteners.push(f));

      // Right Option UP
      listen("hotkey-ropt-up", () => {
        const tm = settingsRef.current.toggle_mode;
        console.log("[hotkey] right option up  toggle_mode=", tm, " state=", stateRef.current);
        if (!tm) {
          // Hold mode: check for short tap before committing to transcribe
          const elapsed = Date.now() - recordStartRef.current;
          console.log("[hotkey] hold duration =", elapsed, "ms  threshold =", MIN_TAP_MS, "ms");
          if (elapsed < MIN_TAP_MS) {
            handleShortTap();
          } else {
            stopAndTranscribe();
          }
        }
        // Toggle mode: release is intentionally ignored
      }).then(f => unlisteners.push(f));

      // Escape — cancel recording
      listen("hotkey-esc", () => {
        console.log("[hotkey] esc  state=", stateRef.current);
        cancelRecording();
      }).then(f => unlisteners.push(f));

      // Tray — start dictation
      listen("tray-start-dictation", () => {
        console.log("[tray] start-dictation");
        startRecording();
      }).then(f => unlisteners.push(f));

      // Tray/menu — stop or cancel
      listen("tray-stop-dictation", () => {
        console.log("[tray] stop-dictation  state=", stateRef.current);
        if (stateRef.current === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));

      // DictationPage stop button (when hotkey started the session)
      listen("ui-stop-recording", () => {
        console.log("[ui] ui-stop-recording  state=", stateRef.current);
        if (stateRef.current === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));

    }).catch(() => {});

    return () => {
      clearRecordingTimeout();
      unlisteners.forEach(u => u());
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
