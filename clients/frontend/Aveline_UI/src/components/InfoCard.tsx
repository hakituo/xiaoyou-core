import React from 'react';

interface InfoCardProps {
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export const InfoCard = ({ title, children, className = "" }: InfoCardProps) => (
  <div className={`bg-white/5 border border-white/10 rounded-2xl p-6 ${className}`}>
    {title && (
      <h3 className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
        {title}
      </h3>
    )}
    {children}
  </div>
);
