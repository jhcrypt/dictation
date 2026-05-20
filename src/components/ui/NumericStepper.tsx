import React from "react";

interface Props {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  className?: string;
}

/**
 * Numeric stepper that uses the same chevron arrow style as the custom Select
 * component — no native OS spin buttons.
 */
export default function NumericStepper({ value, min, max, step, onChange, className = "" }: Props) {
  const round = (n: number) => parseFloat(n.toFixed(6));

  const inc = () => {
    const next = round(value + step);
    if (next <= max) onChange(next);
  };

  const dec = () => {
    const next = round(value - step);
    if (next >= min) onChange(next);
  };

  return (
    <div
      className={`flex items-center bg-jarvis-surface border border-jarvis-border rounded-lg overflow-hidden w-20 ${className}`}
    >
      {/* Value */}
      <span className="flex-1 text-sm text-jarvis-text text-center select-none pl-2">
        {value}
      </span>

      {/* Arrow column — same visual as the select chevron pill */}
      <div className="flex flex-col self-stretch border-l border-jarvis-border">
        <button
          onClick={inc}
          disabled={value >= max}
          aria-label="Increment"
          className="flex-1 flex items-center justify-center px-1.5 text-jarvis-muted hover:text-jarvis-text disabled:opacity-30 transition-colors"
        >
          {/* Up chevron */}
          <svg width="8" height="6" viewBox="0 0 8 6" fill="currentColor">
            <path d="M4 0.5L7.5 5.5H0.5L4 0.5Z" />
          </svg>
        </button>
        <div className="border-t border-jarvis-border" />
        <button
          onClick={dec}
          disabled={value <= min}
          aria-label="Decrement"
          className="flex-1 flex items-center justify-center px-1.5 text-jarvis-muted hover:text-jarvis-text disabled:opacity-30 transition-colors"
        >
          {/* Down chevron */}
          <svg width="8" height="6" viewBox="0 0 8 6" fill="currentColor">
            <path d="M4 5.5L0.5 0.5H7.5L4 5.5Z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
