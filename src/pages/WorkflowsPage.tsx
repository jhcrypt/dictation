import React from "react";
import Card from "../components/ui/Card";

interface WorkflowCardProps {
  title: string;
  status: "Available" | "Voice Command" | "Deferred";
  examples: string[];
  note: string;
}

function WorkflowCard({ title, status, examples, note }: WorkflowCardProps) {
  const statusClass =
    status === "Available"
      ? "bg-jarvis-accent/10 text-jarvis-accent"
      : status === "Voice Command"
        ? "bg-purple-500/10 text-purple-300 border border-purple-500/20"
        : "bg-jarvis-surface text-jarvis-muted border border-jarvis-border";

  const statusLabel =
    status === "Available"
      ? "Available"
      : status === "Voice Command"
        ? "Voice Command"
        : "Deferred";

  return (
    <Card title={title}>
      <div className="mb-2">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusClass}`}>
          {statusLabel}
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
          Workflows are voice-triggered actions beyond plain dictation — opening apps, composing emails,
          controlling volume, taking screenshots, and more. Commands marked "Voice Command" can be spoken
          using the record button, hotkey, or wake word.
        </p>
      </div>

      {/* ── Always-on workflows ─────────────────────────────────────── */}

      <WorkflowCard
        title="Scratch, Undo & Redo"
        status="Available"
        examples={[
          "scratch that",
          "undo that",
          "scratch last 2",
          "scratch all",
          "redo dictation",
        ]}
        note="Scratch/undo deletes your last dictation and sends the matching number of backspaces. Redo re-inserts whatever was last scratched. These always work regardless of Safe Mode or Voice Commands settings."
      />

      <WorkflowCard
        title="Formatting"
        status="Available"
        examples={[
          "make bold",
          "all caps",
          "format as code",
          "make heading",
          "make bullet",
          "italic that",
          "strikethrough that",
        ]}
        note="Works both inline (say the command right after your text) and standalone (formats the last dictation). Always available — Safe Mode does not block formatting commands."
      />

      <WorkflowCard
        title="Punctuation & Navigation"
        status="Available"
        examples={[
          "period",
          "comma",
          "new line",
          "new paragraph",
          "tab",
          "select all",
        ]}
        note="Punctuation commands insert the symbol directly. 'New line' sends Shift+Enter in chat apps (Slack, Messages, Discord, Teams) so your message isn't accidentally sent, and a plain Return everywhere else."
      />

      <WorkflowCard
        title="Copy & Paste"
        status="Available"
        examples={[
          "copy that",
          "copy last",
          "copy all",
          "paste",
        ]}
        note="'Copy that' / 'copy last' copies the last dictation to clipboard. 'Copy all' selects everything and copies. 'Paste' sends Cmd+V."
      />

      <WorkflowCard
        title="Snippets"
        status="Available"
        examples={[
          "insert follow up message",
          "type my disclaimer",
          "support reply",
          "create snippet",
        ]}
        note="Say any snippet trigger phrase to instantly insert saved text. To create a snippet by voice, say 'create snippet', then speak the trigger phrase, then speak the content. Manage snippets in Settings → Snippets."
      />

      <WorkflowCard
        title="Wake Word"
        status="Available"
        examples={["Hey Jarvis"]}
        note="Say 'Hey Jarvis' to start recording hands-free — no button press needed. Enable in Settings → Jarvis. Grace period and silence timeout are adjustable."
      />

      <WorkflowCard
        title="Translation"
        status="Available"
        examples={[
          "translate that",
          "translate selected text",
        ]}
        note="'Translate that' sends the last dictation through Ollama and pastes the English translation. Requires Ollama with a capable model (qwen2.5:3b or larger). You can also turn on Translate My Dictation in Audio & Language to auto-translate every dictation."
      />

      <WorkflowCard
        title="History & Navigation"
        status="Available"
        examples={[
          "show history",
          "dictation history",
          "correct that",
          "add correction",
        ]}
        note="'Show history' opens the History page. 'Correct that' / 'add correction' opens the Vocabulary page so you can add the misheard word."
      />

      {/* ── Jarvis Commands workflows ────────────────────────────────── */}

      <WorkflowCard
        title="Custom Commands"
        status="Voice Command"
        examples={[
          "open my email",
          "open client portal",
          "insert follow up message",
        ]}
        note="Create your own trigger phrases in Settings → Custom Commands. Say them using the record button, hotkey, or wake word. Supported actions: open URL, open app, and type text."
      />

      <WorkflowCard
        title="Open Apps & Websites"
        status="Voice Command"
        examples={[
          "open Safari",
          "open Terminal",
          "open Slack",
          "open YouTube",
          "open Netflix",
          "open GitHub",
        ]}
        note="Say these phrases using the record button, hotkey, or wake word. Say 'open [app name]' to launch any installed macOS app. Say 'open [site]' for popular websites (YouTube, Netflix, GitHub, Claude, Spotify, and more)."
      />

      <WorkflowCard
        title="Web Search"
        status="Voice Command"
        examples={[
          "search for machine learning",
          "google Python tutorials",
          "look up recursion",
          "find best coffee grinders",
        ]}
        note="Opens a DuckDuckGo search in your default browser. Works with 'search for', 'google', 'look up', and 'find'."
      />

      <WorkflowCard
        title="System Volume"
        status="Voice Command"
        examples={[
          "volume up",
          "volume down",
          "mute",
          "unmute",
          "set volume to 50",
        ]}
        note="'Volume up / down' adjusts system volume by 10%. 'Set volume to N' sets an exact level from 0 to 100."
      />

      <WorkflowCard
        title="Reminders"
        status="Voice Command"
        examples={[
          "remind me to call Jack",
          "set a reminder to buy milk",
          "add reminder to review the report",
        ]}
        note="Creates a reminder in the Apple Reminders app immediately. The full spoken phrase (minus the 'remind me to' prefix) becomes the reminder title."
      />

      <WorkflowCard
        title="Email Drafts"
        status="Voice Command"
        examples={[
          "email Jack",
          "send email to Val",
          "compose email to the team saying we're on for Thursday",
        ]}
        note="Opens your default mail client with the To field pre-filled from your Contacts. Add a body by saying 'telling them…', 'saying…', or 'letting them know…' after the name. Manage contacts in Settings → Contacts."
      />

      <WorkflowCard
        title="Screenshots"
        status="Voice Command"
        examples={[
          "screenshot",
          "capture window",
          "area capture",
          "scrolling capture",
          "text recognition",
        ]}
        note="Triggers Shottr shortcuts (full screen, window, area, scrolling, and OCR). Requires Shottr installed at /Applications/Shottr.app. If Shottr is missing, a HUD error appears."
      />

      <WorkflowCard
        title="Spotify & Playlists"
        status="Voice Command"
        examples={[
          "play lo-fi music on Spotify",
          "play coding playlist",
          "play workout playlist",
          "play playlist 4",
        ]}
        note="Opens Spotify with a search URI or a named playlist. Requires Spotify installed."
      />

      <WorkflowCard
        title="Close & Quit Apps"
        status="Voice Command"
        examples={[
          "close Safari",
          "quit Chrome",
          "force quit Slack",
        ]}
        note="'Close [app]' or 'quit [app]' sends a graceful quit. 'Force quit [app]' terminates the process immediately."
      />
    </div>
  );
}
