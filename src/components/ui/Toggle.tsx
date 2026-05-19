import React from "react";

interface ToggleProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}

export default function Toggle({ checked, onChange, label, description }: ToggleProps) {
  return (
    <div
      className="flex items-center justify-between py-2 cursor-pointer"
      onClick={() => onChange(!checked)}
    >
      <div>
        <div className="text-sm text-jarvis-text font-medium">{label}</div>
        {description && <div className="text-xs text-jarvis-muted mt-0.5">{description}</div>}
      </div>
      <div
        className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ml-4 ${
          checked ? "bg-jarvis-accent" : "bg-jarvis-border"
        }`}
      >
        <div
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </div>
    </div>
  );
}
