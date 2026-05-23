import React, { useState, useEffect, useRef, useCallback } from "react";
import { Mic, Check, Zap, AlertCircle, Loader2, Sparkles, AlertTriangle } from "lucide-react";
import quillAppIcon from "./assets/quill_app_icon.png";

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
  | "command"        // Jarvis command / blue info notification
  | "saved"          // Settings saved — green check notification
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
const WAVEFORM_HEIGHTS = [4, 6, 8, 11, 14, 17, 20, 22, 22, 20, 17, 14, 10, 7, 5, 4, 6, 9, 13, 10, 7, 4];

// audioLevel: 0.0–1.0 (matches stable Python scale = min(1.0, rms * 18 + 0.15)).
// Bar heights are scaled by audioLevel so bars grow taller when the mic is louder.
// The CSS hud-wave animation (scaleY 0.25→1.0) provides organic motion on top.
// Default 0.15 = minimum visible level (matches Python's +0.15 floor).
function WaveformBars({ color = "#ff453a", audioLevel = 0.15 }: { color?: string; audioLevel?: number }) {
  return (
    <div
      className="flex items-center flex-shrink-0"
      style={{ gap: 1, height: 24, width: 65 }}
    >
      {Array.from({ length: WAVE_BARS }, (_, i) => {
        const baseH = WAVEFORM_HEIGHTS[i % WAVEFORM_HEIGHTS.length];
        // Scale height by audio level; floor at 2px so bars are always visible.
        const h = Math.max(2, Math.round(baseH * audioLevel));

        return (
          <div
            key={i}
            style={{
              width: 2,
              height: h,
              background: color,
              opacity: 0.92,
              borderRadius: 1,
              transformOrigin: "center center",
              animation: "hud-wave 0.38s ease-in-out infinite",
              animationDelay: `-${((i * 0.031) % 0.38).toFixed(3)}s`,
            }}
          />
        );
      })}
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

function getConfig(state: HudState, payload: HudPayload, audioLevel: number): StateConfig {
  const DIM    = "#4a4a4a";   // Python TEXT_DIM
  const FG     = "#ffffff";   // Python TEXT_WHITE
  const BLUE   = "#0a84ff";
  const RED    = "#ff3b30";   // Python RED
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
        icon:       <WaveformBars color={RED} audioLevel={audioLevel} />,
        label:      "Recording…",
        labelColor: FG,
        subColor:   DIM,
      };
    case "wake_recording":
      return {
        icon:       <WaveformBars color={RED} audioLevel={audioLevel} />,
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
    case "saved":
      return {
        icon:       <Check size={15} strokeWidth={2} style={{ color: GREEN }} className="flex-shrink-0" />,
        label:      payload.subtext || "Saved.",
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
    case "saved":    return "";
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

// ── Dominant-colour extractor ─────────────────────────────────────────────────
// Draws the icon onto an offscreen canvas, samples a grid of pixels, discards
// near-black / near-white / near-grey, and returns the most saturated colour.
function extractDominantColor(src: string): Promise<string | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      try {
        const size = 32;
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = size;
        const ctx = canvas.getContext("2d");
        if (!ctx) { resolve(null); return; }
        ctx.drawImage(img, 0, 0, size, size);
        const { data } = ctx.getImageData(0, 0, size, size);
        let bestSat = 0, bestR = 0, bestG = 0, bestB = 0;
        for (let i = 0; i < data.length; i += 4) {
          const [r, g, b, a] = [data[i], data[i+1], data[i+2], data[i+3]];
          if (a < 80) continue;                         // skip transparent
          const max = Math.max(r, g, b), min = Math.min(r, g, b);
          const lightness = (max + min) / 510;          // 0–1
          if (lightness < 0.12 || lightness > 0.88) continue; // skip near-black/white
          const sat = max === 0 ? 0 : (max - min) / max;
          if (sat > bestSat) { bestSat = sat; bestR = r; bestG = g; bestB = b; }
        }
        resolve(bestSat > 0.15
          ? `rgb(${bestR},${bestG},${bestB})`
          : null);                                       // fall back if icon is grey
      } catch { resolve(null); }
    };
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

export default function HudApp() {
  const [state,      setState]      = useState<HudState>("idle");
  const [payload,    setPayload]    = useState<HudPayload>({ state: "idle" });
  const [appIcon,    setAppIcon]    = useState<string | null>(null);
  const [iconColor,  setIconColor]  = useState<string | null>(null);
  // audioLevel: 0.0–1.0, matches Python scale = min(1.0, rms * 18 + 0.15).
  // Polled from sidecar at ~16 FPS while recording; reset to 0.15 when idle.
  const [audioLevel, setAudioLevel] = useState<number>(0.15);
  const saveTimer      = useRef<ReturnType<typeof setTimeout>  | null>(null);
  const iconTimer      = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioTimer     = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioPollGuard = useRef<boolean>(false); // prevent overlapping fetch calls

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
    if (src) {
      const color = await extractDominantColor(src);
      setIconColor(color);
    } else {
      setIconColor(null);
    }
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

  // ── Live audio level polling ──────────────────────────────────────────────────
  // While recording (hotkey or wake), poll sidecar_get_status every 60 ms (~16 FPS)
  // to read recording_rms and scale WaveformBars heights — matching stable Python
  // _animate_wave which called get_current_rms() every 30 ms.
  //
  // Uses an in-flight guard so slow sidecar responses never stack up.
  // The existing sidecar get_status command already returns recording_rms
  // (added for the wake auto-stop monitor — reused here for free).
  useEffect(() => {
    const isDictatingNow = state === "recording" || state === "wake_recording";

    if (!isDictatingNow) {
      if (audioTimer.current) { clearInterval(audioTimer.current); audioTimer.current = null; }
      setAudioLevel(0.15);
      audioPollGuard.current = false;
      return;
    }

    const poll = async () => {
      if (audioPollGuard.current) return; // previous call still in-flight
      audioPollGuard.current = true;
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const raw = await invoke<string>("sidecar_get_status");
        const status = JSON.parse(raw) as {
          ok: boolean;
          recording_rms?: number | null;
          voice_active?: boolean;
        };
        if (status.ok) {
          const rms = status.recording_rms ?? 0;
          const voiceActive = status.voice_active ?? false;
          // voice_active=true  → full Python formula: bars grow with speech volume
          // voice_active=false → subtle low-level movement; fan/AC noise stays quiet
          const scale = voiceActive
            ? Math.min(1.0, rms * 18 + 0.15)
            : Math.min(0.22, rms * 3 + 0.10);
          setAudioLevel(scale);
        }
      } catch {
        // Non-critical — sidecar may be momentarily busy; keep last value
      } finally {
        audioPollGuard.current = false;
      }
    };

    audioTimer.current = setInterval(poll, 60);
    return () => {
      if (audioTimer.current) { clearInterval(audioTimer.current); audioTimer.current = null; }
    };
  }, [state]);

  const handleMouseDown = async (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().startDragging();
    } catch { /* browser preview */ }
  };

  const cfg     = getConfig(state, payload, audioLevel);
  const subtext = getSubtext(state, payload);
  const label   = cfg.label.length > 58 ? cfg.label.slice(0, 58) + "…" : cfg.label;

  // Border only during active dictation; colour from app icon at low opacity
  const isDictating = state === "recording" || state === "wake_recording";
  const borderColor = isDictating
    ? (iconColor
        ? iconColor.replace("rgb(", "rgba(").replace(")", ", 0.35)")
        : "rgba(10, 132, 255, 0.3)")
    : "transparent";

  // Waveform states: keep the waveform flush-left, but leave breathing room before the text.
  const isWaveform = state === "recording" || state === "wake_recording";

  return (
    <div
      className="w-full h-full flex items-center"
      style={{
        paddingLeft:  isWaveform ? 8 : 13,
        paddingRight: 13,
        gap:          isWaveform ? 10 : 10,
        background:   "rgba(36, 36, 36, 0.96)",
        borderRadius: "10px",
        border:       `1px solid ${borderColor}`,
        cursor:       "grab",
        overflow:     "hidden",
        backdropFilter:       "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        transition:   "border-color 0.3s ease",
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

      {/* Right: target app icon (falls back to Quill icon when no app is focused) */}
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
          src={appIcon ?? quillAppIcon}
          alt=""
          draggable={false}
          style={{
            width:      34,
            height:     34,
            objectFit:  "contain",
            display:    "block",
            borderRadius: 0,
            opacity:    1,
          }}
        />
      </div>
    </div>
  );
}
