import {
  Settings,
  Globe,
  Mic,
  Wand2,
  BookText,
  Bot,
  Terminal,
  UserRound,
  BookOpen,
  Type,
  Cloud,
  Zap,
  Clock3,
  CircleHelp,
  type LucideIcon,
} from "lucide-react";

export type Page =
  | "setup"
  | "dictation"
  | "audio"
  | "aicleanup"
  | "writingprofiles"
  | "jarvis"
  | "customcommands"
  | "contacts"
  | "vocabulary"
  | "snippets"
  | "cloud"
  | "workflows"
  | "history"
  | "help";

interface NavItem {
  id: Page;
  label: string;
  Icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { id: "setup",          label: "Setup",             Icon: Settings   },
  { id: "dictation",      label: "Dictation",         Icon: Mic        },
  { id: "audio",          label: "Audio & Language",  Icon: Globe      },
  { id: "aicleanup",      label: "AI Cleanup",        Icon: Wand2      },
  { id: "writingprofiles",label: "Writing Profiles",  Icon: BookText   },
  { id: "jarvis",         label: "Jarvis",            Icon: Bot        },
  { id: "customcommands", label: "Custom Commands",   Icon: Terminal   },
  { id: "contacts",       label: "Contacts",          Icon: UserRound  },
  { id: "vocabulary",     label: "Vocabulary",        Icon: BookOpen   },
  { id: "snippets",       label: "Snippets",          Icon: Type       },
  { id: "cloud",          label: "Cloud",             Icon: Cloud      },
  { id: "workflows",      label: "Workflows",         Icon: Zap        },
  { id: "history",        label: "History",           Icon: Clock3     },
  { id: "help",           label: "Help",              Icon: CircleHelp },
];

interface SidebarProps {
  current: Page;
  onChange: (p: Page) => void;
}

export default function Sidebar({ current, onChange }: SidebarProps) {
  return (
    <aside
      className="w-48 flex-shrink-0 flex flex-col"
      style={{ background: "#1a1a1a", borderRight: "1px solid #2e2e2e" }}
    >
      {/* Nav */}
      <nav className="flex-1 py-2 overflow-y-auto">
        {NAV_ITEMS.map(({ id, label, Icon }) => {
          const active = id === current;
          return (
            <button
              key={id}
              onClick={() => onChange(id)}
              className={`flex items-center gap-2.5 px-3 py-2 mx-1 rounded-lg text-left transition-colors ${
                active
                  ? "bg-jarvis-accent/15 text-jarvis-text"
                  : "text-jarvis-muted hover:bg-jarvis-surface hover:text-jarvis-text"
              }`}
              style={{ width: "calc(100% - 8px)" }}
            >
              <Icon
                size={15}
                strokeWidth={1.75}
                className={active ? "text-jarvis-accent" : "text-jarvis-muted"}
              />
              <span className="text-[12.5px] font-medium">{label}</span>
            </button>
          );
        })}
      </nav>

      <div
        className="px-4 py-3"
        style={{ borderTop: "1px solid #2e2e2e" }}
      >
        <div className="text-jarvis-muted text-[11px]">Quill Tauri Preview v0.2.0</div>
      </div>
    </aside>
  );
}
