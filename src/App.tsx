import React, { useState, useEffect } from "react";
import Sidebar, { Page } from "./components/Sidebar";
import { SettingsProvider, useSettings } from "./context/SettingsContext";
import { useGlobalHotkey } from "./hooks/useGlobalHotkey";
import SetupPage from "./pages/SetupPage";
import DictationPage from "./pages/DictationPage";
import AudioPage from "./pages/AudioPage";
import AiCleanupPage from "./pages/AiCleanupPage";
import WritingProfilesPage from "./pages/WritingProfilesPage";
import JarvisPage from "./pages/JarvisPage";
import CustomCommandsPage from "./pages/CustomCommandsPage";
import ContactsPage from "./pages/ContactsPage";
import VocabularyPage from "./pages/VocabularyPage";
import SnippetsPage from "./pages/SnippetsPage";
import CloudPage from "./pages/CloudPage";
import WorkflowsPage from "./pages/WorkflowsPage";
import HistoryPage from "./pages/HistoryPage";
import HelpPage from "./pages/HelpPage";
import quillIcon from "./assets/quill_header_icon.png";

// Tray nav-event → page id mapping
const TRAY_NAV: Record<string, Page> = {
  "nav-setup":          "setup",
  "nav-history":        "history",
  "nav-snippets":       "snippets",
  "nav-customcommands": "customcommands",
  "nav-help":           "help",
};

function AppContent() {
  const [page, setPage] = useState<Page>("dictation");
  const { loadSettings } = useSettings();

  useGlobalHotkey();

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  // Listen for tray navigation events
  useEffect(() => {
    let unlisten: Array<() => void> = [];
    import("@tauri-apps/api/event").then(({ listen }) => {
      Object.entries(TRAY_NAV).forEach(([event, target]) => {
        listen(event, () => setPage(target)).then((fn) => unlisten.push(fn));
      });
    }).catch(() => {});
    return () => unlisten.forEach((fn) => fn());
  }, []);

  const PageComponent: Record<Page, React.FC> = {
    setup:          SetupPage,
    dictation:      DictationPage,
    audio:          AudioPage,
    aicleanup:      AiCleanupPage,
    writingprofiles:WritingProfilesPage,
    jarvis:         JarvisPage,
    customcommands: CustomCommandsPage,
    contacts:       ContactsPage,
    vocabulary:     VocabularyPage,
    snippets:       SnippetsPage,
    cloud:          CloudPage,
    workflows:      WorkflowsPage,
    history:        HistoryPage,
    help:           HelpPage,
  };

  const CurrentPage = PageComponent[page];

  return (
    <div className="flex flex-col h-full w-full" style={{ background: "#141414" }}>
      {/* Title bar */}
      <div
        data-tauri-drag-region
        className="flex-shrink-0 flex items-center justify-center gap-2 select-none"
        style={{
          height: "44px",
          borderBottom: "1px solid #2e2e2e",
          // @ts-ignore
          WebkitAppRegion: "drag",
        }}
      >
        <img
          src={quillIcon}
          alt="Quill"
          style={{ width: 20, height: 20, objectFit: "contain", opacity: 0.85 }}
          className="pointer-events-none"
        />
        <span className="text-[13px] font-semibold text-jarvis-muted pointer-events-none tracking-wide">
          Quill Tauri Preview
        </span>
      </div>

      {/* App body */}
      <div className="flex flex-1 min-h-0 w-full">
        <Sidebar current={page} onChange={setPage} />
        <main className="flex-1 overflow-y-auto p-6" style={{ background: "#141414" }}>
          <CurrentPage />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <SettingsProvider>
      <AppContent />
    </SettingsProvider>
  );
}
