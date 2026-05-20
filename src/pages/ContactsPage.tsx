import React, { useState, useEffect } from "react";
import Card from "../components/ui/Card";

interface Contact {
  name: string;
  email: string;
  aliases: string;
}

const DUMMY_CONTACTS: Contact[] = [
  { name: "Valerie Henry", email: "henryval3@aol.com", aliases: "Val" },
  { name: "Kingler Bercy", email: "kingler@me.com", aliases: "King" },
  { name: "Hubert Henry", email: "mymanfitygran@aol.com", aliases: "Bob" },
];

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>(DUMMY_CONTACTS);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [aliases, setAliases] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    loadContacts();
  }, []);

  async function loadContacts() {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const loaded = await invoke<Contact[]>("load_contacts");
      setContacts(loaded);
    } catch { /* preview */ }
  }

  async function saveContacts(updated: Contact[], hudMsg?: string) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("save_contacts", { contacts: updated });
      if (hudMsg) {
        // HUD — Python: self.show_message("Saved.", self.GREEN)
        const { hudSaved } = await import("../utils/hudNotify");
        hudSaved(hudMsg);
      }
    } catch { /* preview */ }
  }

  const addContact = async () => {
    if (!name.trim() || !email.trim()) {
      setStatus("Name and email are required.");
      return;
    }
    const updated = [...contacts, { name: name.trim(), email: email.trim(), aliases: aliases.trim() }];
    setContacts(updated);
    await saveContacts(updated, `Saved '${name.trim()}'`);
    setName(""); setEmail(""); setAliases("");
    setStatus("Contact added.");
    setTimeout(() => setStatus(""), 2000);
  };

  const deleteContact = async (i: number) => {
    const updated = contacts.filter((_, idx) => idx !== i);
    setContacts(updated);
    await saveContacts(updated, "Saved.");
  };

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div>
        <h2 className="text-lg font-semibold text-jarvis-text">Contacts</h2>
        <p className="text-sm text-jarvis-hint mt-1">People you can email by voice. "Email Val" → looks up alias.</p>
      </div>

      <Card title="Add Contact">
        <div className="flex flex-col gap-2">
          <input
            placeholder="Full name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <input
            placeholder="Email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <input
            placeholder="Aliases (e.g. Val, Valerie)"
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            className="bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent placeholder:text-jarvis-muted"
          />
          <div className="flex items-center gap-3 mt-1">
            <button
              onClick={addContact}
              className="px-4 py-2 bg-jarvis-accent hover:bg-jarvis-accent-hover text-white rounded-lg text-sm font-medium transition-colors"
            >
              Add Contact
            </button>
            {status && <span className="text-xs text-jarvis-muted">{status}</span>}
          </div>
        </div>
      </Card>

      <Card title={`Contacts (${contacts.length})`}>
        {contacts.length === 0 ? (
          <p className="text-sm text-jarvis-muted">No contacts yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {contacts.map((c, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-jarvis-surface rounded-lg">
                <div>
                  <div className="text-sm font-medium text-jarvis-text">{c.name}</div>
                  <div className="text-xs text-jarvis-muted">{c.email}</div>
                  {c.aliases && <div className="text-xs text-jarvis-muted">Aliases: {c.aliases}</div>}
                </div>
                <button
                  onClick={() => deleteContact(i)}
                  className="text-xs text-jarvis-muted hover:text-jarvis-recording transition-colors px-2 py-1"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
