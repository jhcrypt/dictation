/**
 * useGlobalHotkey
 *
 * Listens for Tauri events emitted by the Rust hotkey listener (rdev):
 *   hotkey-ropt-down  → start recording
 *   hotkey-ropt-up    → stop + transcribe + paste
 *   hotkey-esc        → cancel recording
 *   tray-start-dictation / tray-stop-dictation → tray menu actions
 *
 * This hook must be called at the App level (always mounted) so listeners
 * survive page navigation.
 */
import { useEffect, useRef } from "react";
import { useSettings } from "../context/SettingsContext";

type RecState = "idle" | "recording" | "transcribing";

type HudPayload = {
  state: string;
  subtext?: string;
  profile?: string;
  status?: string;
};

export function useGlobalHotkey() {
  const { settings } = useSettings();
  const stateRef    = useRef<RecState>("idle");
  const settingsRef = useRef(settings);

  useEffect(() => { settingsRef.current = settings; }, [settings]);

  useEffect(() => {
    // ── Helpers ──────────────────────────────────────────────────────────────

    const hudEmit = async (payload: HudPayload) => {
      try {
        const { emit } = await import("@tauri-apps/api/event");
        emit("hud-state", payload);
      } catch { /* browser preview */ }
    };

    const invoke = async <T>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
      const { invoke: inv } = await import("@tauri-apps/api/core");
      return inv<T>(cmd, args);
    };

    // ── Recording flow ───────────────────────────────────────────────────────

    const startRecording = async () => {
      if (stateRef.current !== "idle") return;
      stateRef.current = "recording";
      hudEmit({ state: "recording" });
      try {
        await invoke("sidecar_start_recording");
      } catch (e) {
        stateRef.current = "idle";
        hudEmit({ state: "error", subtext: String(e) });
        setTimeout(() => hudEmit({ state: "idle" }), 4000);
      }
    };

    const stopAndTranscribe = async () => {
      if (stateRef.current !== "recording") return;
      stateRef.current = "transcribing";
      hudEmit({ state: "transcribing" });

      try {
        await invoke("sidecar_stop_recording");
        const result = await invoke<{
          ok: boolean; text: string;
          timing: { whisper: number; ollama: number; total: number };
          error?: string;
          profile?: string;
          status?: string;
          skipped_cleanup?: boolean;
          skip_reason?: string;
        }>("sidecar_transcribe_last");

        if (result.ok && result.text) {
          const s = settingsRef.current;

          // Cleanup state (brief)
          if (!result.skipped_cleanup && s.use_ollama && s.ai_cleanup_mode !== "off") {
            hudEmit({ state: "cleanup" });
            await new Promise((r) => setTimeout(r, 600));
          }

          // Skipped state
          if (result.skipped_cleanup && result.skip_reason) {
            hudEmit({ state: "skipped", subtext: result.skip_reason });
            await new Promise((r) => setTimeout(r, 1200));
          }

          let pasteStatus = "transcribed";
          if (!s.safe_mode) {
            try {
              await invoke("paste_text", { text: result.text });
              pasteStatus = "pasted";
            } catch {
              pasteStatus = "paste_failed";
            }
          }

          const profile = result.profile ?? s.writing_profile ?? "General";
          hudEmit({
            state:   "inserted",
            subtext: result.text.slice(0, 55),
            status:  pasteStatus,
            profile: s.show_active_profile ? profile : undefined,
          });

          try {
            await invoke("save_history_entry", {
              entry: {
                timestamp: new Date().toISOString(),
                final_text: result.text,
                status: pasteStatus,
                profile,
                source: "tauri",
                timing: result.timing ?? null,
              },
            });
          } catch { /* ignore */ }

          setTimeout(() => hudEmit({ state: "idle" }), 3500);
        } else {
          hudEmit({ state: "error", subtext: result.error ?? "Transcription failed" });
          setTimeout(() => hudEmit({ state: "idle" }), 4000);
        }
      } catch (e) {
        hudEmit({ state: "error", subtext: String(e) });
        setTimeout(() => hudEmit({ state: "idle" }), 4000);
      }

      stateRef.current = "idle";
    };

    const cancelRecording = async () => {
      if (stateRef.current !== "recording") return;
      stateRef.current = "idle";
      try {
        await invoke("sidecar_cancel_recording");
      } catch { /* ignore */ }
      hudEmit({ state: "idle" });
    };

    // ── Event listeners ──────────────────────────────────────────────────────

    const unlisteners: Array<() => void> = [];

    import("@tauri-apps/api/event").then(({ listen }) => {
      listen("hotkey-ropt-down",     () => startRecording())   .then(f => unlisteners.push(f));
      listen("hotkey-ropt-up",       () => stopAndTranscribe()).then(f => unlisteners.push(f));
      listen("hotkey-esc",           () => cancelRecording())  .then(f => unlisteners.push(f));
      listen("tray-start-dictation", () => startRecording())   .then(f => unlisteners.push(f));
      listen("tray-stop-dictation",  () => {
        if (stateRef.current === "recording") stopAndTranscribe();
        else cancelRecording();
      }).then(f => unlisteners.push(f));
    }).catch(() => {});

    return () => { unlisteners.forEach(u => u()); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
