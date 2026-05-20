import React from "react";

interface SelectProps<T extends string> {
  value: T;
  options: T[];
  onChange: (v: T) => void;
  label?: string;
}

export default function Select<T extends string>({ value, options, onChange, label }: SelectProps<T>) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label className="text-[11px] text-jarvis-muted font-medium uppercase tracking-wider">
          {label}
        </label>
      )}
      {/* Wrapper strips native macOS gray overlay via appearance-none */}
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value as T)}
          className="w-full appearance-none bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 pr-8 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent cursor-pointer"
        >
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>

        {/* Custom chevron — matches NumericStepper arrow style; pointer-events-none so clicks reach <select> */}
        <div className="pointer-events-none absolute inset-y-0 right-0 flex flex-col items-center justify-center gap-[3px] pr-2.5">
          <svg width="8" height="5" viewBox="0 0 8 5" className="text-jarvis-muted" fill="currentColor">
            <path d="M4 0.5L7.5 4.5H0.5L4 0.5Z" />
          </svg>
          <svg width="8" height="5" viewBox="0 0 8 5" className="text-jarvis-muted" fill="currentColor">
            <path d="M4 4.5L0.5 0.5H7.5L4 4.5Z" />
          </svg>
        </div>
      </div>
    </div>
  );
}
