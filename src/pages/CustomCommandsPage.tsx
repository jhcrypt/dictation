import React, { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import Card from "../components/ui/Card";

type ActionType = "open_url" | "open_app" | "type_text";

interface CustomCommand {
  trigger: string;
  action: ActionType;
  target: string;
}

const ACTION_LABELS: Record<ActionType, string> = {
  open_url:  "Open URL",
  open_app:  "Open App",
  type_text: "Type Text",
};

export default function CustomCommandsPage() {
  const [commands, setCommands] = useState<CustomCommand[]>([]);
  const [trigger, setTrigger] = useState("");
  const [action, setAction] = useState<ActionType>("open_url");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    invoke<CustomCommand[]>("load_custom_commands")
      .then(setCommands)
      .catch(() => setCommands([]))
      .finally(() => setLoading(false));
  }, []);

  const flash = (msg: string) => {
    setStatus(msg);
    setTimeout(() => setStatus(""), 2500);
  };

  const save = async (updated: CustomCommand[], hudMsg?: string) => {
    await invoke("save_custom_commands", { commands: updated });
    setCommands(updated);
    if (hudMsg) {
      // HUD — Python: self.show_message(f"Saved '{t}'", self.GREEN)
      const { hudSaved } = await import("../utils/hudNotify");
      hudSaved(hudMsg);
    }
  };

  const addCommand = async () => {
    const words = trigger.trim().split(/\s+/).filter(Boolean);
    if (words.length < 2) {
      flash("Trigger must be at least 2 words.");
      return;
    }
    if (!target.trim()) {
      flash("Target cannot be empty.");
      return;
    }
    const newCmd: CustomCommand = { trigger: trigger.trim(), action, target: target.trim() };
    await save([...commands, newCmd], `Saved '${trigger.trim()}'`);
    setTrigger(""); setTarget("");
    flash("Command added.");
  };

  const deleteCommand = async (i: number) => {
    await save(commands.filter((_, idx) => idx !== i), "Saved.");
    flash("Deleted.");
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Custom Commands</h2>
        <p className="text-sm text-jarvis-hint mt-1">
          Say the trigger phrase to run an action. Triggers must be at least 2 words.
        </p>
      </div>

      <Card title="Add Command">
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-xs text-jarvis-muted mb-1 block">Trigger phrase (≥ 2 words)</label>
            <input
              type="text"
              placeholder='e.g. "open my email"'
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
            />
          </div>

          <div>
            <label className="text-xs text-jarvis-muted mb-1 block">Action</label>
            <div className="flex gap-2">
              {(["open_url", "open_app", "type_text"] as ActionType[]).map((a) => (
                <button
                  key={a}
                  onClick={() => setAction(a)}
                  className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-colors ${
                    action === a
                      ? "bg-jarvis-accent border-jarvis-accent text-white"
                      : "bg-jarvis-surface border-jarvis-border text-jarvis-muted hover:text-jarvis-text"
                  }`}
                >
                  {ACTION_LABELS[a]}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-jarvis-muted mb-1 block">
              {action === "open_url" ? "URL" : action === "open_app" ? "App name" : "Text to type"}
            </label>
            <input
              type="text"
              placeholder={
                action === "open_url" ? "https://..." :
                action === "open_app" ? "Safari" :
                "Text to insert..."
              }
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="w-full bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
            />
          </div>

          {status && <p className="text-xs text-jarvis-hint">{status}</p>}

          <div className="flex justify-end">
            <button
              onClick={addCommand}
              className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors"
            >
              Add Command
            </button>
          </div>
        </div>
      </Card>

      <Card title={`Commands (${commands.length})`}>
        {loading ? (
          <p className="text-sm text-jarvis-muted">Loading…</p>
        ) : commands.length === 0 ? (
          <p className="text-sm text-jarvis-muted">No custom commands yet.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {commands.map((cmd, i) => (
              <div key={i} className="flex items-start justify-between px-3 py-2.5 bg-jarvis-surface rounded-lg gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-jarvis-text font-medium truncate">"{cmd.trigger}"</div>
                  <div className="text-xs text-jarvis-muted mt-0.5">
                    <span className="text-jarvis-hint">{ACTION_LABELS[cmd.action]}</span>
                    {" → "}
                    <span className="truncate">{cmd.target}</span>
                  </div>
                </div>
                <button
                  onClick={() => deleteCommand(i)}
                  className="text-xs text-jarvis-muted hover:text-jarvis-danger transition-colors px-2 pt-0.5 flex-shrink-0"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
