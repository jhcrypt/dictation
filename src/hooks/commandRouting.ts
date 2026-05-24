/**
 * commandRouting.ts
 *
 * Pure classification of sidecar transcribe_last responses.
 * Extracted from useGlobalHotkey so it can be unit-tested without
 * any React or Tauri dependencies.
 *
 * Used by useGlobalHotkey to decide what to do with each result:
 *   "command"     → execute the action, show HUD, go idle — do NOT paste command text
 *   "text"        → paste trimmed text, show inserted HUD
 *   "tap_ignored" → short press / silence / no audio — show orange tap message, go idle
 *   "error"       → real transcription failure — show red error HUD
 *
 * The ONLY valid instructions come from the sidecar via the result shape.
 * TypeScript callers must not interpret an empty text as an error, and must
 * not interpret a command result (action present) as text to paste.
 */

export interface SidecarResult {
  ok: boolean;
  text?: string | null;
  action?: string | null;
  error?: string | null;
  // Command fields (present on command results, absent on text results)
  backspace_count?: number | null;
  key?: string | null;
  with_shift?: boolean | null;
  repeat?: number | null;
  modifier?: string | null;
  nav_target?: string | null;
  app_name?: string | null;
  url?: string | null;
  direction?: string | null;
  level?: number | null;
  screenshot_type?: string | null;
  force?: boolean | null;
  hud?: string | null;
  hud_color?: string | null;
  // Text result fields
  whisper_text?: string | null;
  ollama_text?: string | null;
  skipped_cleanup?: boolean | null;
  skip_reason?: string | null;
  timing?: { whisper: number; ollama: number; total: number };
  profile?: string | null;
  active_app?: string | null;
  ollama_accepted?: boolean | null;
  ollama_reject_reason?: string | null;
  ollama_request_ms?: number | null;
  ollama_model?: string | null;
  word_count?: number | null;
}

/**
 * Outcome types returned by classifyTranscribeResult.
 * Each type maps to a distinct HUD state and action in useGlobalHotkey.
 */
export type TranscribeOutcome =
  | { type: "command"; action: string }
  | { type: "text"; trimmed: string }
  | { type: "tap_ignored" }
  | { type: "error"; message: string };

/**
 * Normalize a spoken phrase or stored trigger for exact-match comparison.
 *
 * Rules (order matters):
 *  1. trim() — remove surrounding whitespace
 *  2. toLowerCase()
 *  3. Strip LEADING punctuation — Whisper sometimes hallucinates ", " or ". "
 *     at the start of the transcript.  Without this strip, a trigger "open movies"
 *     would never match a Whisper result ", open movies."
 *  4. Strip TRAILING punctuation — Whisper/smart_punctuate commonly adds "."
 *  5. Remove apostrophes — "let's" → "lets" so stored triggers without apostrophes
 *     match natural speech (e.g. stored "lets play chess" matches "let's play chess").
 */
export function normalizeTrigger(text: string): string {
  return text.trim()
    .toLowerCase()
    .replace(/^[.,!?\s]+/g, "") // leading punctuation + space (Whisper hallucinations: ", open movies")
    .replace(/[.,!?]+$/g, "")   // trailing punctuation
    .replace(/['']/g, "");      // apostrophes: "let's" → "lets"
}

/**
 * Classify a sidecar transcribe_last result into one of four outcomes.
 *
 * Routing rules (in priority order):
 * 1. ok=false AND error="no audio recorded"  → tap_ignored
 * 2. ok=false (any other error)               → error
 * 3. ok=true  AND action is a non-empty string → command
 * 4. ok=true  AND text != null AND trimmed non-empty → text (paste)
 * 5. ok=true  AND text == "" or whitespace-only → tap_ignored (silence / short hold)
 * 6. ok=true  AND text == null, no action      → error ("Transcription failed")
 *
 * Critical invariant: a command result (rule 3) NEVER reaches the text branch.
 * This means command text (e.g. "." for period) is pasted via the command
 * dispatch, not via the normal paste path — preventing double-paste bugs.
 */
export function classifyTranscribeResult(result: SidecarResult): TranscribeOutcome {
  // ── Rule 1 & 2: ok=false ──────────────────────────────────────────────────
  if (!result.ok) {
    if (result.error === "no audio recorded") {
      return { type: "tap_ignored" };
    }
    return { type: "error", message: result.error ?? "Transcription failed" };
  }

  // ── Rule 3: command (action present and non-empty) ────────────────────────
  // Must check BEFORE text so command responses with text (e.g. paste_text
  // action which carries the text to insert) are handled as commands, not
  // as raw dictation.
  if (result.action) {
    return { type: "command", action: result.action };
  }

  // ── Rules 4 & 5: plain transcription ─────────────────────────────────────
  if (result.text != null) {
    const trimmed = result.text.trim();
    if (trimmed.length === 0) {
      // Whisper returned nothing — user said nothing or held just barely
      // over the debounce threshold.  Not an error; treat same as short tap.
      return { type: "tap_ignored" };
    }
    return { type: "text", trimmed };
  }

  // ── Rule 6: ok=true but no action and no text ─────────────────────────────
  // Should not happen in normal operation; treat as unknown error.
  return { type: "error", message: result.error ?? "Transcription failed" };
}
