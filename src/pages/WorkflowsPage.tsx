import React from "react";
import Card from "../components/ui/Card";

interface WorkflowCardProps {
  title: string;
  status: "Available now" | "Coming later";
  examples: string[];
  note: string;
}

function WorkflowCard({ title, status, examples, note }: WorkflowCardProps) {
  return (
    <Card title={title}>
      <div className="mb-2">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
          status === "Available now"
            ? "bg-jarvis-accent/10 text-jarvis-accent"
            : "bg-jarvis-surface text-jarvis-muted border border-jarvis-border"
        }`}>
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
          Workflows are voice-triggered actions that go beyond normal dictation. Some are available now through
          Custom Commands, while deeper Jarvis workflows will be added after Wake Word is stable.
        </p>
      </div>

      <Card title="How workflows work">
        <div className="space-y-2 text-sm text-jarvis-muted leading-relaxed">
          <p>
            Use the Option key for normal dictation and custom command triggers. Wake Word is currently paused,
            so workflows should not depend on saying “Hey Jarvis” yet.
          </p>
          <p>
            For now, the safest workflow actions are simple and predictable: open a URL, open an app, or type a
            saved text snippet.
          </p>
        </div>
      </Card>

      <WorkflowCard
        title="Custom Commands"
        status="Available now"
        examples={["open my email", "open client portal", "insert follow up message"]}
        note="Create these in Custom Commands. Supported actions are open URL, open app, and type text. They work with the Option-key workflow when Jarvis Commands is enabled."
      />

      <WorkflowCard
        title="Open URLs"
        status="Available now"
        examples={["open release docs", "open insurance quote form", "open calendar"]}
        note="Best for links you use often. Add a short trigger phrase and the URL in Custom Commands."
      />

      <WorkflowCard
        title="Open Apps"
        status="Available now"
        examples={["open Safari", "open Finder", "open Terminal"]}
        note="Best for launching installed macOS apps by name. Keep trigger phrases simple and at least two words."
      />

      <WorkflowCard
        title="Type Saved Text"
        status="Available now"
        examples={["insert meeting follow up", "type my disclaimer", "insert support reply"]}
        note="Best for reusable text. This is useful for common replies, signatures, disclaimers, and short templates."
      />

      <WorkflowCard
        title="Email Drafts"
        status="Coming later"
        examples={["email Jack", "compose email to Val", "write follow up to client"]}
        note="Planned workflow: create a draft in the user’s default email app. This should not assume Apple Mail because users may use Spark, Outlook, or another default mail client."
      />

      <WorkflowCard
        title="Reminders"
        status="Coming later"
        examples={["remind me to call Jack tomorrow", "remind me to review the quote at 3pm"]}
        note="Planned workflow: create a reminder safely with confirmation and predictable date handling."
      />

      <WorkflowCard
        title="System Controls"
        status="Coming later"
        examples={["set volume to 50", "volume up", "mute"]}
        note="Planned workflow: control system settings only after permissions, safety rules, and undo behavior are clear."
      />
    </div>
  );
}
