import React, { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { Settings, DEFAULT_SETTINGS } from "../types/settings";

interface SettingsContextValue {
  settings: Settings;
  setSettings: (s: Settings) => void;
  updateSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  saveSettings: () => Promise<void>;
  loadSettings: () => Promise<void>;
  saved: boolean;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);

  const setSettings = useCallback((s: Settings) => {
    setSettingsState(s);
  }, []);

  const updateSetting = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettingsState((prev) => ({ ...prev, [key]: value }));
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const loaded = await invoke<Settings>("load_settings");
      setSettingsState({ ...DEFAULT_SETTINGS, ...loaded });
    } catch {
      // Not in Tauri — keep defaults for browser preview
    }
  }, []);

  const saveSettings = useCallback(async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("save_settings", { settings });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      // HUD notification — Python: self.show_message("Saved.", self.GREEN)
      const { hudSaved } = await import("../utils/hudNotify");
      await hudSaved("Saved.");
    } catch {
      // Not in Tauri
    }
  }, [settings]);

  return (
    <SettingsContext.Provider value={{ settings, setSettings, updateSetting, saveSettings, loadSettings, saved }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be inside SettingsProvider");
  return ctx;
}
