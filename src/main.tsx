import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import HudApp from "./HudApp";
import "./index.css";

// Synchronously detect if this webview is the floating HUD window.
// __TAURI_INTERNALS__ is injected by Tauri before any scripts run.
const isHud =
  (window as any).__TAURI_INTERNALS__?.metadata?.currentWindow?.label === "hud";

if (isHud) {
  document.documentElement.classList.add("hud-mode");
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {isHud ? <HudApp /> : <App />}
  </React.StrictMode>
);
