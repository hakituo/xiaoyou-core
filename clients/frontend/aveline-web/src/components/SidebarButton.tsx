import React from 'react';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { cn } from '../utils/common';
import { SIDEBAR_ITEMS } from '../utils/constants';
import { isNative } from '../utils/nativeService';

const SidebarButton = ({ 
  item, 
  isActive, 
  isExpanded, 
  onClick 
}: {
  item: typeof SIDEBAR_ITEMS[0];
  isActive: boolean;
  isExpanded: boolean;
  onClick: () => void;
}) => {
  return (
    <button 
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={isExpanded ? undefined : item.title}
      className={cn(
        "w-full h-11 flex items-center px-3 mx-auto rounded-xl transition-all duration-300 group relative mb-1",
        isActive
          ? "bg-white/10 text-white shadow-[0_0_20px_rgba(255,255,255,0.05)] border border-white/5"
          : "text-white/40 hover:text-white hover:bg-white/5 border border-transparent"
      )}
    >
      <div className="flex items-center min-w-0 gap-3">
        <span className={cn(
          "transition-all duration-300 flex items-center justify-center w-8 h-8 shrink-0",
          isActive
            ? "text-white/90"
            : "group-hover:scale-110 group-hover:text-white/90"
        )}>
          {item.icon}
        </span>

        {isExpanded && (
          <div className="flex items-center overflow-hidden">
            <span className="text-sm font-medium tracking-wide whitespace-nowrap opacity-90">
              {item.label}
            </span>
          </div>
        )}
      </div>
      
    </button>
  );
};

export default SidebarButton;
