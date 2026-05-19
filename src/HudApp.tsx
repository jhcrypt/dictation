import React, { useState, useEffect, useRef, useCallback } from "react";
import { Mic, Check, Zap, AlertCircle, Loader2, Sparkles } from "lucide-react";

// All HUD states mirroring the Python app
export type HudState =
  | "idle"           // Quill Ready — Hold ⌥ to dictate
  | "recording"      // Recording… — Release to stop (hotkey mode)
  | "wake_recording" // Keep speaking · press ⌥ to stop (wake-word mode)
  | "transcribing"   // Transcribing…
  | "cleanup"        // Cleaning up…
  | "skipped"        // Status: skipped: <reason>
  | "inserted"       // Final: <text preview> / Status: pasted / Profile: <name>
  | "command"        // Jarvis command executed
  | "error";         // Error: <message>

interface HudPayload {
  state: HudState;
  subtext?: string;     // extra detail line (preview text, error msg, skip reason)
  profile?: string;     // writing profile shown on final state
  status?: string;      // status label on final state
}

// ── Indicator components ──────────────────────────────────────────────────────

function PulsingDot({ color = "#ff453a" }: { color?: string }) {
  return (
    <div className="relative w-4 h-4 flex items-center justify-center flex-shrink-0">
      <div
        className="absolute inset-0 rounded-full animate-ping opacity-30"
        style={{ background: color }}
      />
      <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
    </div>
  );
}

function Spinner() {
  return (
    <Loader2
      size={16}
      strokeWidth={2}
      className="animate-spin flex-shrink-0"
      style={{ color: "#0a84ff" }}
    />
  );
}

// ── State config ──────────────────────────────────────────────────────────────

interface StateConfig {
  icon: React.ReactNode;
  label: string;
  labelColor: string;
  subColor: string;
}

function getConfig(state: HudState, payload: HudPayload): StateConfig {
  const DIM      = "#6a6a6a";
  const FG       = "#f0f0f0";
  const BLUE     = "#0a84ff";
  const RED      = "#ff453a";
  const GREEN    = "#30d158";
  const ORANGE   = "#ff9f0a";
  const HINT     = "#8ab4f8";

  switch (state) {
    case "idle":
      return {
        icon:       <Mic size={15} strokeWidth={1.75} style={{ color: DIM }} className="flex-shrink-0" />,
        label:      "Quill Ready",
        labelColor: DIM,
        subColor:   DIM,
      };
    case "recording":
      return {
        icon:       <PulsingDot color={RED} />,
        label:      "Recording…",
        labelColor: FG,
        subColor:   DIM,
      };
    case "wake_recording":
      return {
        icon:       <PulsingDot color={RED} />,
        label:      "Jarvis wake-word recording",
        labelColor: FG,
        subColor:   DIM,
      };
    case "transcribing":
      return {
        icon:       <Spinner />,
        label:      "Transcribing…",
        labelColor: FG,
        subColor:   DIM,
      };
    case "cleanup":
      return {
        icon:       <Sparkles size={15} strokeWidth={1.75} style={{ color: BLUE }} className="flex-shrink-0" />,
        label:      "Cleaning up…",
        labelColor: FG,
        subColor:   DIM,
      };
    case "skipped":
      return {
        icon:       <Check size={15} strokeWidth={2} style={{ color: ORANGE }} className="flex-shrink-0" />,
        label:      "Skipped cleanup",
        labelColor: ORANGE,
        subColor:   DIM,
      };
    case "inserted":
      return {
        icon:       <Check size={15} strokeWidth={2} style={{ color: GREEN }} className="flex-shrink-0" />,
        label:      payload.subtext ? `Final: ${payload.subtext}` : "Inserted",
        labelColor: FG,
        subColor:   HINT,
      };
    case "command":
      return {
        icon:       <Zap size={15} strokeWidth={1.75} style={{ color: BLUE }} className="flex-shrink-0" />,
        label:      payload.subtext || "Command done",
        labelColor: FG,
        subColor:   DIM,
      };
    case "error":
      return {
        icon:       <AlertCircle size={15} strokeWidth={1.75} style={{ color: RED }} className="flex-shrink-0" />,
        label:      "Error",
        labelColor: RED,
        subColor:   DIM,
      };
  }
}

// ── Default subtexts per state ────────────────────────────────────────────────

function getSubtext(state: HudState, payload: HudPayload): string {
  if (state === "inserted") {
    // Build "Status: pasted  ·  Profile: Email" line
    const parts: string[] = [];
    if (payload.status) parts.push(`Status: ${payload.status}`);
    if (payload.profile) parts.push(`Profile: ${payload.profile}`);
    return parts.join("  ·  ");
  }
  if (state === "skipped" && payload.subtext) return `Reason: ${payload.subtext}`;
  if (state === "error"   && payload.subtext) return payload.subtext;
  if (state === "command" && payload.subtext) return "";

  const defaults: Partial<Record<HudState, string>> = {
    idle:          "Hold ⌥ to dictate",
    recording:     "Hotkey recording · release to stop",
    wake_recording:"Keep speaking · press ⌥ to stop",
    transcribing:  "Processing speech…",
    cleanup:       "Ollama AI cleanup running…",
    skipped:       "",
  };
  return defaults[state] ?? "";
}

// ── Main HUD component ────────────────────────────────────────────────────────

export default function HudApp() {
  const [state,   setState]   = useState<HudState>("idle");
  const [payload, setPayload] = useState<HudPayload>({ state: "idle" });
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const savePosition = useCallback((x: number, y: number) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("save_hud_position", { x: Math.round(x), y: Math.round(y) });
      } catch { /* no-op */ }
    }, 500);
  }, []);

  useEffect(() => {
    let unlistenHud:   (() => void) | null = null;
    let unlistenMoved: (() => void) | null = null;

    import("@tauri-apps/api/event").then(({ listen }) => {
      listen<HudPayload>("hud-state", (event) => {
        setState(event.payload.state);
        setPayload(event.payload);
      }).then((fn) => { unlistenHud = fn; });
    }).catch(() => {});

    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      getCurrentWindow().onMoved((pos) => {
        savePosition(pos.payload.x, pos.payload.y);
      }).then((fn) => { unlistenMoved = fn; });
    }).catch(() => {});

    return () => {
      unlistenHud?.();
      unlistenMoved?.();
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [savePosition]);

  const handleMouseDown = async (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().startDragging();
    } catch { /* browser preview */ }
  };

  const cfg     = getConfig(state, payload);
  const subtext = getSubtext(state, payload);

  // Truncate long labels (final text preview)
  const label = cfg.label.length > 70 ? cfg.label.slice(0, 70) + "…" : cfg.label;

  return (
    <div
      className="w-full h-full flex items-center gap-3"
      style={{
        padding:      "0 18px",
        background:   "rgba(28, 28, 30, 0.96)",
        border:       "1px solid rgba(255,255,255,0.10)",
        borderRadius: "18px",
        cursor:       "grab",
        overflow:     "hidden",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      } as React.CSSProperties}
      onMouseDown={handleMouseDown}
    >
      {/* State icon */}
      {cfg.icon}

      {/* Text area */}
      <div className="flex-1 min-w-0">
        <div
          className="text-[13px] font-semibold leading-tight truncate"
          style={{ color: cfg.labelColor }}
        >
          {label}
        </div>
        {subtext && (
          <div
            className="text-[11.5px] mt-0.5 leading-tight truncate"
            style={{ color: cfg.subColor }}
          >
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
}
