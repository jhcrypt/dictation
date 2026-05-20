import React, { useState, useEffect, useRef, useCallback } from "react";
import { Mic, Check, Zap, AlertCircle, Loader2, Sparkles, AlertTriangle } from "lucide-react";

// ── HUD state type — mirrors Python DictationApp states + Tauri extras ────────
export type HudState =
  | "idle"           // Hold ⌥ to dictate
  | "tap_ignored"    // Tap ignored — hold a little longer
  | "recording"      // Recording… press/release to stop
  | "wake_recording" // Keep speaking · press ⌥ to stop
  | "transcribing"   // Transcribing…
  | "cleanup"        // Cleaning up… (Ollama running)
  | "skipped"        // Short phrase / already well-formed / unsafe rewrite
  | "inserted"       // Final: <text>  Status: …  Profile: …
  | "command"        // Jarvis command executed
  | "error";         // Error: <message>

export interface HudPayload {
  state: HudState;
  subtext?: string;     // detail / skip reason / error message / text preview
  profile?: string;     // writing profile on inserted state
  status?: string;      // ollama status label on inserted state
  toggleMode?: boolean; // true = "press ⌥ again to stop", false = "release ⌥ to stop"
}

// ── Waveform — 22 bars × 2px + 21 gaps × 1px = 65px, matching Python spec ───

const WAVE_BARS = 22;
function WaveformBars({ color = "#ff453a" }: { color?: string }) {
  return (
    <div
      className="flex items-center flex-shrink-0"
      style={{ gap: 1, height: 24, width: 65 }}
    >
      {Array.from({ length: WAVE_BARS }, (_, i) => (
        <div
          key={i}
          style={{
            width: 2,
            height: 24,
            background: color,
            borderRadius: 1,
            transformOrigin: "center center",
            animation: "hud-wave 0.75s ease-in-out infinite",
            // stagger across full cycle so bars feel like a live waveform
            animationDelay: `-${((i * 0.034) % 0.75).toFixed(3)}s`,
          }}
        />
      ))}
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

// ── State config ───────────────────────────────────────────────────────────────

interface StateConfig {
  icon: React.ReactNode;
  label: string;
  labelColor: string;
  subColor: string;
}

function getConfig(state: HudState, payload: HudPayload): StateConfig {
  const DIM    = "#6a6a6a";
  const FG     = "#f0f0f0";
  const BLUE   = "#0a84ff";
  const RED    = "#ff453a";
  const GREEN  = "#30d158";
  const ORANGE = "#ff9f0a";
  const HINT   = "#8ab4f8";

  switch (state) {
    case "idle":
      return {
        icon:       <Mic size={15} strokeWidth={1.75} style={{ color: DIM }} className="flex-shrink-0" />,
        label:      "Hold ⌥ to dictate",
        labelColor: DIM,
        subColor:   DIM,
      };
    case "tap_ignored":
      return {
        icon:       <AlertTriangle size={15} strokeWidth={1.75} style={{ color: ORANGE }} className="flex-shrink-0" />,
        label:      "Tap ignored — hold a little longer",
        labelColor: ORANGE,
        subColor:   DIM,
      };
    case "recording":
      return {
        icon:       <WaveformBars color={RED} />,
        label:      "Recording…",
        labelColor: FG,
        subColor:   DIM,
      };
    case "wake_recording":
      return {
        icon:       <WaveformBars color={RED} />,
        label:      "Keep speaking",
        labelColor: FG,
        subColor:   DIM,
      };
    case "transcribing":
      return {
        icon:       <Spinner />,
        label:      "Transcribing…",
        labelColor: BLUE,
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
        icon:       <Check size={15} strokeWidth={2} style={{ color: BLUE }} className="flex-shrink-0" />,
        label:      payload.subtext ? _skippedLabel(payload.subtext) : "Skipped cleanup",
        labelColor: BLUE,
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

/** Map Python skip_reason to a human-readable HUD label matching Python messages. */
function _skippedLabel(reason: string): string {
  if (reason === "short phrase")        return "Short phrase — skipped AI cleanup";
  if (reason === "already well-formed") return "Already well-formed — skipped";
  if (reason === "unsafe rewrite")      return "AI cleanup rejected — used original";
  return `Skipped: ${reason}`;
}

// ── Subtexts ───────────────────────────────────────────────────────────────────

function getSubtext(state: HudState, payload: HudPayload): string {
  switch (state) {
    case "idle":          return "";          // Python shows nothing below idle text
    case "tap_ignored":   return "";
    case "recording":
      // Match Python: "press to stop" (toggle) or "release to stop" (hold)
      if (payload.subtext) return payload.subtext;
      return payload.toggleMode ? "Press ⌥ again to stop" : "Release ⌥ to stop";
    case "wake_recording": return "Press ⌥ to stop";
    case "transcribing":   return "";
    case "cleanup":        return "Ollama AI cleanup running…";
    case "skipped":        return "";  // label already contains the message
    case "inserted": {
      const parts: string[] = [];
      if (payload.status)  parts.push(`Status: ${payload.status}`);
      if (payload.profile) parts.push(`Profile: ${payload.profile}`);
      return parts.join("  ·  ");
    }
    case "command":  return "";
    case "error":    return payload.subtext ?? "";
  }
}

// ── App icon ───────────────────────────────────────────────────────────────────

async function fetchAppIcon(): Promise<string | null> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const b64 = await invoke<string | null>("get_target_app_icon");
    if (!b64) return null;
    return `data:image/png;base64,${b64}`;
  } catch {
    return null;
  }
}

// ── Main HUD component ─────────────────────────────────────────────────────────

export default function HudApp() {
  const [state,   setState]   = useState<HudState>("idle");
  const [payload, setPayload] = useState<HudPayload>({ state: "idle" });
  const [appIcon, setAppIcon] = useState<string | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const iconTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const savePosition = useCallback((x: number, y: number) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("save_hud_position", { x: Math.round(x), y: Math.round(y) });
      } catch { /* no-op */ }
    }, 500);
  }, []);

  const refreshIcon = useCallback(async () => {
    const src = await fetchAppIcon();
    setAppIcon(src);
  }, []);

  useEffect(() => {
    let unlistenHud:   (() => void) | null = null;
    let unlistenMoved: (() => void) | null = null;

    import("@tauri-apps/api/event").then(({ listen }) => {
      listen<HudPayload>("hud-state", (event) => {
        setState(event.payload.state);
        setPayload(event.payload);
        refreshIcon();
      }).then((fn) => { unlistenHud = fn; });
    }).catch(() => {});

    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      getCurrentWindow().onMoved((pos) => {
        savePosition(pos.payload.x, pos.payload.y);
      }).then((fn) => { unlistenMoved = fn; });
    }).catch(() => {});

    refreshIcon();
    iconTimer.current = setInterval(refreshIcon, 3000);

    return () => {
      unlistenHud?.();
      unlistenMoved?.();
      if (saveTimer.current) clearTimeout(saveTimer.current);
      if (iconTimer.current) clearInterval(iconTimer.current);
    };
  }, [savePosition, refreshIcon]);

  const handleMouseDown = async (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().startDragging();
    } catch { /* browser preview */ }
  };

  const cfg     = getConfig(state, payload);
  const subtext = getSubtext(state, payload);
  const label   = cfg.label.length > 58 ? cfg.label.slice(0, 58) + "…" : cfg.label;

  return (
    <div
      className="w-full h-full flex items-center"
      style={{
        padding:      "0 14px",
        gap:          10,
        background:   "rgba(38, 40, 43, 0.94)",
        border:       "1px solid rgba(255,255,255,0.10)",
        borderRadius: "10px",
        cursor:       "grab",
        overflow:     "hidden",
        backdropFilter:       "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      } as React.CSSProperties}
      onMouseDown={handleMouseDown}
    >
      {/* Left: state icon — natural width (waveform=65px, others=15–16px) */}
      {cfg.icon}

      {/* Middle: label + optional subtext */}
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

      {/* Right: target app icon */}
      {appIcon && (
        <div
          style={{
            width:          40,
            height:         40,
            borderRadius:   10,
            flexShrink:     0,
            overflow:       "hidden",
            display:        "flex",
            alignItems:     "center",
            justifyContent: "center",
          }}
        >
          <img
            src={appIcon}
            alt=""
            draggable={false}
            style={{ width: 34, height: 34, objectFit: "contain", display: "block" }}
          />
        </div>
      )}
    </div>
  );
}
