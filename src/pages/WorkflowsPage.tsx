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
        title="Reminders"
        status="Python parity pending"
        examples={["remind me to call Jack tomorrow", "remind me to review the quote at 3pm"]}
        note="Worked in the stable Python app. Tauri should restore the same predictable reminder creation workflow."
      />

      <WorkflowCard
        title="Translation"
        status="Python parity pending"
        examples={["translate that", "translate selected text", "translate to French"]}
        note="Worked in the stable Python app. Tauri should restore selected text, clipboard handling, and target language behavior."
      />

      <WorkflowCard
        title="System Controls"
        status="Python parity pending"
        examples={["set volume to 50", "volume up", "set brightness to 80"]}
        note="Worked in the stable Python app. Tauri should restore this carefully with permission and safety checks."
      />

      <WorkflowCard
        title="Screenshots"
        status="Python parity pending"
        examples={["take a screenshot", "capture window", "extract text"]}
        note="Worked in the stable Python app with Shottr integration. Tauri should restore the same command patterns."
      />

      <WorkflowCard
        title="Scratch, Undo, and Formatting"
        status="Python parity pending"
        examples={["scratch that", "undo last", "make that bold"]}
        note="Worked in the stable Python app. These should be restored as part of command parsing parity."
      />

      <WorkflowCard
        title="Wake Word"
        status="Paused in Tauri"
        examples={["Hey Jarvis"]}
        note="Wake Word worked in Python, but is currently paused in Tauri because enabling it can freeze the app. Option-key dictation remains the safe path."
      />
    </div>
  );
}
