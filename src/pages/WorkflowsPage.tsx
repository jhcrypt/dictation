import React from "react";
import Card from "../components/ui/Card";

interface WorkflowCardProps {
  title: string;
  examples: string[];
  note?: string;
}

function WorkflowCard({ title, examples, note }: WorkflowCardProps) {
  return (
    <Card title={title}>
      <div className="flex flex-col gap-1 mb-2">
        {examples.map((ex) => (
          <code key={ex} className="text-xs bg-jarvis-surface px-2 py-1 rounded-lg text-jarvis-accent font-mono">
            "{ex}"
          </code>
        ))}
      </div>
      {note && <p className="text-xs text-jarvis-muted mt-2">{note}</p>}
    </Card>
  );
}

export default function WorkflowsPage() {
  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Workflows</h2>
        <p className="text-sm text-jarvis-muted mt-1">
          Voice commands that trigger actions. Spoken during or after dictation.
        </p>
      </div>

      <WorkflowCard
        title="Email Drafts"
        examples={["email Jack", "send email to Val", "compose email to King"]}
        note="Opens Spark Desktop → Spark → Mail → Outlook. Contact must exist in your Contacts list."
      />

      <WorkflowCard
        title="Reminders"
        examples={["remind me to call Jack tomorrow", "remind me to review the quote at 3pm"]}
        note="Creates a reminder in Apple Reminders.app via AppleScript."
      />

      <WorkflowCard
        title="Translation"
        examples={["translate that", "translate selected text", "translate to French"]}
        note="Translates clipboard selection. Target language set in Audio & Language settings."
      />

      <WorkflowCard
        title="Open URLs"
        examples={["let's play chess", "open release docs"]}
        note="Configure custom URL triggers in Settings → Custom Commands."
      />

      <WorkflowCard
        title="Open Apps"
        examples={["open Photoshop", "open Finder", "open Terminal"]}
        note="Opens any installed macOS application by name."
      />

      <WorkflowCard
        title="System Controls"
        examples={["set volume to 50", "volume up", "set brightness to 80"]}
        note="Controls system volume and screen brightness via AppleScript."
      />

      <WorkflowCard
        title="Corrections"
        examples={["correct that", "change that to...", "replace ... with ..."]}
        note="Voice-triggered find-and-replace on the last dictation."
      />

      <Card title="Custom Commands">
        <p className="text-sm text-jarvis-muted">
          Add your own trigger phrases in{" "}
          <span className="text-jarvis-accent">Settings → Custom Commands</span>.
          Supports open URL, open app, and type text actions.
        </p>
      </Card>
    </div>
  );
}
