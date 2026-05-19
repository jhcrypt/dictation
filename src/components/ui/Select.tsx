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
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="bg-jarvis-surface border border-jarvis-border rounded-lg px-3 py-2 text-sm text-jarvis-text focus:outline-none focus:border-jarvis-accent cursor-pointer"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}
