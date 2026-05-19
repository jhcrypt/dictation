import React from "react";

interface SaveButtonProps {
  onClick: () => void;
  saved?: boolean;
}

export default function SaveButton({ onClick, saved }: SaveButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
        saved
          ? "bg-jarvis-success text-white"
          : "bg-jarvis-accent hover:bg-jarvis-accent-hover text-white"
      }`}
    >
      {saved ? "Saved" : "Save"}
    </button>
  );
}
