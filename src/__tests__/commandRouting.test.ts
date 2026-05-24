/**
 * commandRouting.test.ts
 *
 * Regression tests for classifyTranscribeResult.
 *
 * These tests protect against a class of bug where fixes to error/HUD handling
 * accidentally break command routing.  The core invariant:
 *
 *   A result with a non-empty `action` field is ALWAYS a command —
 *   regardless of what `text`, `ok`, or `error` say.
 *
 * Run:  npm test
 *       npx vitest run src/__tests__/commandRouting.test.ts
 */
import { describe, it, expect } from "vitest";
import { classifyTranscribeResult } from "../hooks/commandRouting";
import type { SidecarResult } from "../hooks/commandRouting";

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Minimal valid command result shape from the sidecar. */
const cmd = (action: string, extra: Partial<SidecarResult> = {}): SidecarResult => ({
  ok: true,
  text: null,
  action,
  timing: { whisper: 50, ollama: 0, total: 50 },
  ...extra,
});

const text = (t: string, extra: Partial<SidecarResult> = {}): SidecarResult => ({
  ok: true,
  text: t,
  action: null,
  timing: { whisper: 80, ollama: 0, total: 80 },
  ...extra,
});

const fail = (error: string): SidecarResult => ({
  ok: false,
  text: null,
  action: null,
  error,
  timing: { whisper: 0, ollama: 0, total: 0 },
});

// ── Command responses ──────────────────────────────────────────────────────────

describe("command responses", () => {
  it("keypress with null text → command (not error, not tap_ignored)", () => {
    const r = classifyTranscribeResult(cmd("keypress", { key: "return", repeat: 1 }));
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("keypress");
  });

  it("scratch with backspace_count, null text → command", () => {
    const r = classifyTranscribeResult(cmd("scratch", { backspace_count: 12 }));
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("scratch");
  });

  it("paste_text with non-empty text → command (not plain text paste)", () => {
    // paste_text IS a command — the text is pasted via command dispatch,
    // not via the normal dictation paste path.
    const r = classifyTranscribeResult(cmd("paste_text", { text: "." }));
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("paste_text");
  });

  it("open_url with url, null text → command", () => {
    const r = classifyTranscribeResult(
      cmd("open_url", { url: "https://example.com" }),
    );
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("open_url");
  });

  it("open_app with app_name, null text → command", () => {
    const r = classifyTranscribeResult(cmd("open_app", { app_name: "Safari" }));
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("open_app");
  });

  it("set_volume with direction, null text → command", () => {
    const r = classifyTranscribeResult(cmd("set_volume", { direction: "up" }));
    expect(r.type).toBe("command");
  });

  it("key_combo with modifier+key, null text → command", () => {
    const r = classifyTranscribeResult(cmd("key_combo", { modifier: "cmd", key: "a" }));
    expect(r.type).toBe("command");
  });

  it("navigate with nav_target, null text → command", () => {
    const r = classifyTranscribeResult(cmd("navigate", { nav_target: "history" }));
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("navigate");
  });

  it("copy_text with text → command (not text paste)", () => {
    const r = classifyTranscribeResult(cmd("copy_text", { text: "hello world" }));
    expect(r.type).toBe("command");
  });

  it("copy_all, null text → command", () => {
    expect(classifyTranscribeResult(cmd("copy_all")).type).toBe("command");
  });

  it("noop with hud, null text → command (shown in HUD, nothing pasted)", () => {
    const r = classifyTranscribeResult(
      cmd("noop", { hud: "Nothing to redo", hud_color: "#ff9f0a" }),
    );
    expect(r.type).toBe("command");
    if (r.type === "command") expect(r.action).toBe("noop");
  });

  it("take_screenshot, null text → command", () => {
    const r = classifyTranscribeResult(
      cmd("take_screenshot", { screenshot_type: "area" }),
    );
    expect(r.type).toBe("command");
  });

  it("close_app with app_name → command", () => {
    const r = classifyTranscribeResult(cmd("close_app", { app_name: "Safari" }));
    expect(r.type).toBe("command");
  });

  it("snippet_waiting_trigger → command", () => {
    expect(classifyTranscribeResult(cmd("snippet_waiting_trigger")).type).toBe("command");
  });

  it("snippet_saved → command", () => {
    expect(classifyTranscribeResult(cmd("snippet_saved")).type).toBe("command");
  });

  it("format_paste with text + backspace_count → command (not plain text)", () => {
    const r = classifyTranscribeResult(
      cmd("format_paste", { text: "**hello**", backspace_count: 5 }),
    );
    expect(r.type).toBe("command");
  });
});

// ── Plain text responses ───────────────────────────────────────────────────────

describe("plain text responses", () => {
  it("ok + non-empty text + no action → text", () => {
    const r = classifyTranscribeResult(text("hello world"));
    expect(r.type).toBe("text");
    if (r.type === "text") expect(r.trimmed).toBe("hello world");
  });

  it("text is trimmed before being returned", () => {
    const r = classifyTranscribeResult(text("  hello world  "));
    expect(r.type).toBe("text");
    if (r.type === "text") expect(r.trimmed).toBe("hello world");
  });

  it("ok + text with leading/trailing whitespace, no action → text", () => {
    const r = classifyTranscribeResult(text("\t  hello\n"));
    expect(r.type).toBe("text");
    if (r.type === "text") expect(r.trimmed).toBe("hello");
  });
});

// ── Tap-ignored responses ──────────────────────────────────────────────────────

describe("tap_ignored responses (should never show red error)", () => {
  it('ok=false + error="no audio recorded" → tap_ignored', () => {
    expect(classifyTranscribeResult(fail("no audio recorded")).type).toBe("tap_ignored");
  });

  it("ok=true + text='' + no action → tap_ignored (silence / short hold)", () => {
    expect(classifyTranscribeResult(text("")).type).toBe("tap_ignored");
  });

  it("ok=true + text='   ' (whitespace only) → tap_ignored", () => {
    expect(classifyTranscribeResult(text("   ")).type).toBe("tap_ignored");
  });

  it("ok=true + text='\\t\\n' (newlines only) → tap_ignored", () => {
    expect(classifyTranscribeResult(text("\t\n")).type).toBe("tap_ignored");
  });
});

// ── Error responses ────────────────────────────────────────────────────────────

describe("real error responses", () => {
  it("ok=false + unknown error → error with message", () => {
    const r = classifyTranscribeResult(fail("Whisper model not loaded"));
    expect(r.type).toBe("error");
    if (r.type === "error") expect(r.message).toBe("Whisper model not loaded");
  });

  it("ok=false + no error field → error with default message", () => {
    const r = classifyTranscribeResult({ ok: false, text: null, action: null });
    expect(r.type).toBe("error");
    if (r.type === "error") expect(r.message).toBe("Transcription failed");
  });

  it("ok=true + text=null + action=null → error (unknown state)", () => {
    const r = classifyTranscribeResult({ ok: true, text: null, action: null });
    expect(r.type).toBe("error");
  });
});

// ── Critical invariant: command is never misrouted ────────────────────────────

describe("routing invariants", () => {
  it("command with non-empty text is COMMAND not TEXT (no double-paste)", () => {
    // Regression: paste_text commands carry the text to paste. They must go
    // through command dispatch, not through the normal text paste path.
    const r = classifyTranscribeResult(cmd("paste_text", { text: "." }));
    expect(r.type).toBe("command");
    expect(r.type).not.toBe("text");
  });

  it("command with empty text is still COMMAND not tap_ignored", () => {
    // Some command actions may have text: "" — they are still commands.
    const r = classifyTranscribeResult(cmd("noop", { text: "" }));
    expect(r.type).toBe("command");
    expect(r.type).not.toBe("tap_ignored");
  });

  it("no audio error is TAP_IGNORED not ERROR", () => {
    // "no audio recorded" is benign — short press or silence.
    // Must not show a red error HUD.
    const r = classifyTranscribeResult(fail("no audio recorded"));
    expect(r.type).toBe("tap_ignored");
    expect(r.type).not.toBe("error");
  });

  it("real error is ERROR not tap_ignored", () => {
    const r = classifyTranscribeResult(fail("CUDA out of memory"));
    expect(r.type).toBe("error");
    expect(r.type).not.toBe("tap_ignored");
  });

  it("empty text is TAP_IGNORED not ERROR", () => {
    // Whisper returned nothing. This is not a failure — just silence.
    // Must not show "Transcription failed" red error.
    const r = classifyTranscribeResult(text(""));
    expect(r.type).toBe("tap_ignored");
    expect(r.type).not.toBe("error");
  });
});
