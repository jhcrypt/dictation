import { Mic, Check, Zap, AlertCircle } from "lucide-react";

export type HudState = "idle" | "recording" | "transcribing" | "inserted" | "command" | "error";

interface HudProps {
  state: HudState;
  subtext?: string;
}

function PulsingDot() {
  return (
    <div className="relative w-4 h-4 flex items-center justify-center flex-shrink-0">
      <div className="absolute inset-0 rounded-full bg-jarvis-accent/25 animate-ping" />
      <div className="w-2.5 h-2.5 rounded-full bg-jarvis-accent" />
    </div>
  );
}

function Spinner() {
  return (
    <div
      className="w-4 h-4 rounded-full animate-spin flex-shrink-0"
      style={{ border: "2px solid rgba(108,99,255,0.2)", borderTopColor: "#6c63ff" }}
    />
  );
}

export default function Hud({ state, subtext }: HudProps) {
  type Config = { icon: React.ReactNode; label: string; sub: string; labelClass: string };

  const cfg: Config = {
    idle: {
      icon: <Mic size={15} strokeWidth={1.75} className="text-jarvis-muted flex-shrink-0" />,
      label: "Jarvis Ready",
      sub: "Hold Right Option to dictate",
      labelClass: "text-jarvis-muted",
    },
    recording: {
      icon: <PulsingDot />,
      label: "Recording…",
      sub: "Release to transcribe",
      labelClass: "text-jarvis-text",
    },
    transcribing: {
      icon: <Spinner />,
      label: "Transcribing…",
      sub: "Processing speech",
      labelClass: "text-jarvis-text",
    },
    inserted: {
      icon: <Check size={15} strokeWidth={2} className="text-jarvis-success flex-shrink-0" />,
      label: "Inserted",
      sub: subtext || "",
      labelClass: "text-jarvis-text",
    },
    command: {
      icon: <Zap size={15} strokeWidth={1.75} className="text-jarvis-accent flex-shrink-0" />,
      label: subtext || "Done",
      sub: "",
      labelClass: "text-jarvis-text",
    },
    error: {
      icon: <AlertCircle size={15} strokeWidth={1.75} className="text-red-400 flex-shrink-0" />,
      label: subtext || "Error",
      sub: "Check permissions",
      labelClass: "text-red-400",
    },
  }[state];

  return (
    <div
      className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2.5 rounded-xl pointer-events-none"
      style={{
        background: "#2a2a34",
        border: "1px solid rgba(255,255,255,0.10)",
        boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
        minWidth: "196px",
      }}
    >
      {cfg.icon}
      <div className="min-w-0">
        <div className={`text-[13px] font-semibold leading-tight ${cfg.labelClass}`}>{cfg.label}</div>
        {cfg.sub && (
          <div className="text-[11px] text-jarvis-muted mt-0.5 leading-tight">{cfg.sub}</div>
        )}
      </div>
    </div>
  );
}
