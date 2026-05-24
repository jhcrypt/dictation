import React from "react";
import Card from "../components/ui/Card";

interface WorkflowCardProps {
  title: string;
  status: "Available in Tauri" | "Python parity pending" | "Paused in Tauri";
  examples: string[];
  note: string;
}

function WorkflowCard({ title, status, examples, note }: WorkflowCardProps) {
  const statusClass =
    status === "Available in Tauri"
      ? "bg-jarvis-accent/10 text-jarvis-accent"
      : status === "Python parity pending"
        ? "bg-amber-500/10 text-amber-300 border border-amber-500/20"
        : "bg-jarvis-surface text-jarvis-muted border border-jarvis-border";

  return (
    <Card title={title}>
      <div className="mb-2">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusClass}`}>
          {status}
        </span>
      </div>

      <div className="flex flex-col gap-1.5 mb-2">
        {examples.map((ex) => (
          <code
            key={ex}
            className="text-xs bg-jarvis-surface px-2 py-1 rounded-lg text-jarvis-accent font-mono whitespace-normal break-words"
          >
            "{ex}"
          </code>
        ))}
      </div>

      <p className="text-xs text-jarvis-muted mt-2 leading-relaxed">{note}</p>
    </Card>
  );
}

export default function WorkflowsPage() {
  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Workflows</h2>
        <p className="text-sm text-jarvis-hint mt-1 leading-relaxed">
          Workflows are voice-triggered actions that go beyond normal dictation. The stable Python app already
          supported many of these workflows. The Tauri version is being brought back to feature parity carefully,
          one workflow at a time.
        </p>
      </div>

      <Card title="Workflow status guide">
        <div className="space-y-2 text-sm text-jarvis-muted leading-relaxed">
          <p>
            <span className="text-jarvis-accent font-medium">Available in Tauri:</span>{" "}
            Confirmed working in the current Tauri build.
          </p>
          <p>
            <span className="text-amber-300 font-medium">Python parity pending:</span>{" "}
            Worked in the stable Python app and needs to be restored or verified in Tauri.
          </p>
          <p>
            <span className="text-jarvis-muted font-medium">Paused in Tauri:</span>{" "}
            Known unsafe or intentionally disabled while the Tauri rebuild stabilizes.
          </p>
        </div>
      </Card>

      <WorkflowCard
        title="Custom Commands"
        status="Available in Tauri"
        examples={["open my email", "open client portal", "insert follow up message"]}
        note="Create these in Custom Commands. Supported actions are open URL, open app, and type text. They work through the Option-key workflow when Jarvis Commands is enabled."
      />

      <WorkflowCard
        title="Open URLs"
        status="Available in Tauri"
        examples={["open release docs", "open insurance quote form", "open calendar"]}
        note="Available through Custom Commands. Add a short trigger phrase and the URL you want to open."
      />

      <WorkflowCard
        title="Open Apps"
        status="Available in Tauri"
        examples={["open Safari", "open Finder", "open Terminal"]}
        note="Available through Custom Commands. Launch installed macOS apps by name."
      />

      <WorkflowCard
        title="Type Saved Text"
        status="Available in Tauri"
        examples={["insert meeting follow up", "type my disclaimer", "insert support reply"]}
        note="Available through Custom Commands. Useful for reusable replies, signatures, disclaimers, and short templates."
      />

      <WorkflowCard
        title="Email Drafts"
        status="Python parity pending"
        examples={["email Jack", "send email to Val", "compose email to King"]}
        note="Worked in the stable Python app. Tauri should restore this without assuming Apple Mail, since users may use Spark, Outlook, or another default email client."
      />

      <WorkflowCard
        title="Open Apps & Websites"
        status="Available in Tauri"
        examples={["open Safari", "open Terminal", "open YouTube", "open Netflix"]}
        note="Say 'open [app name]' to launch any installed app. Say 'open [site]' for YouTube, Netflix, GitHub, Claude, and other popular sites. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Web Search"
        status="Available in Tauri"
        examples={["search for machine learning", "google Python tutorials", "look up recursion"]}
        note="Opens a DuckDuckGo search in your default browser. Works with 'search for', 'google', 'look up', and 'find'. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="System Volume"
        status="Available in Tauri"
        examples={["volume up", "volume down", "mute", "set volume to 50"]}
        note="Controls macOS system volume. 'Volume up/down' adjusts by 10%. 'Set volume to N' sets an exact level 0–100. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Reminders"
        status="Available in Tauri"
        examples={["remind me to call Jack", "set a reminder to buy milk", "add reminder to review the report"]}
        note="Creates a reminder in the Apple Reminders app. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Screenshots"
        status="Available in Tauri"
        examples={["screenshot", "area capture", "scrolling capture", "text recognition"]}
        note="Triggers Shottr shortcuts (Control+W/A/S/T). Requires Shottr installed at /Applications/Shottr.app. If Shottr is missing, a HUD error message appears. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Spotify & Playlists"
        status="Available in Tauri"
        examples={["play lo-fi music on Spotify", "play coding playlist", "play workout playlist"]}
        note="Opens Spotify with a search or a specific playlist URI. Requires Spotify to be installed and Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Close & Quit Apps"
        status="Available in Tauri"
        examples={["close Safari", "kill Chrome", "force quit Slack"]}
        note="'Close [app]' sends a graceful quit. 'Kill [app]' or 'force quit [app]' force-terminates the process. Requires Jarvis Commands to be enabled."
      />

      <WorkflowCard
        title="Scratch, Undo, and Formatting"
        status="Available in Tauri"
        examples={["scratch that", "make bold", "all caps"]}
        note="Scratch/undo deletes the last dictation. Formatting commands (bold, italic, code, heading, bullet, quote, strikethrough) work both inline and standalone. These always work — Safe Mode does not block them."
      />

      <WorkflowCard
        title="Email Drafts"
        status="Python parity pending"
        examples={["email Jack", "send email to Val", "compose email to King"]}
        note="Worked in the stable Python app. Tauri should restore this without assuming Apple Mail, since users may use Spark, Outlook, or another default email client."
      />

      <WorkflowCard
        title="Translation"
        status="Python parity pending"
        examples={["translate that", "translate selected text", "translate to French"]}
        note="Translate My Dictation (auto-translate every dictation) is already available in Audio & Language settings. On-demand 'translate that' voice command is still pending."
      />

      <WorkflowCard
        title="Wake Word"
        status="Available in Tauri"
        examples={["Hey Jarvis"]}
        note="Say 'Hey Jarvis' to start recording hands-free. Enable in Settings → Jarvis. Timing parameters (grace, silence, max) are adjustable."
      />
    </div>
  );
}
