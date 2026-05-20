import React, { ReactNode } from "react";

interface CardProps {
  title?: string;
  children: ReactNode;
  className?: string;
}

export default function Card({ title, children, className = "" }: CardProps) {
  return (
    <div className={`bg-jarvis-surface border border-[#383838] rounded-xl p-4 ${className}`}>
      {title && (
        <h3 className="text-xs font-semibold text-jarvis-muted uppercase tracking-wider mb-3">
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}
