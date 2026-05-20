/**
 * HUD notification helpers — mirrors Python's app.show_message() calls.
 *
 * Uses the same "hud-state" Tauri event path that already works for
 * menu-bar model-change notifications. Auto-clears to "idle" after
 * clearAfter ms so dictation is never blocked.
 */

async function _emit(state: string, subtext: string) {
  try {
    const { emit } = await import("@tauri-apps/api/event");
    await emit("hud-state", { state, subtext });
  } catch { /* browser preview / no Tauri */ }
}

/**
 * Green "saved" notification — Python: show_message("Saved.", GREEN)
 * Shows a green check with the given text, auto-clears after clearAfter ms.
 */
export async function hudSaved(subtext = "Saved.", clearAfter = 2500) {
  await _emit("saved", subtext);
  setTimeout(() => _emit("idle", ""), clearAfter);
}

/**
 * Blue "command" notification — Python: show_message("...", BLUE)
 * Used for mode changes, loading states, etc. Auto-clears after clearAfter ms.
 */
export async function hudCommand(subtext: string, clearAfter = 2500) {
  await _emit("command", subtext);
  setTimeout(() => _emit("idle", ""), clearAfter);
}
