import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '../utils/common';
import { SIDEBAR_ITEMS } from '../utils/constants';

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
      onClick={onClick}
      title={isExpanded ? undefined : item.title}
      className={cn(
        "w-full flex items-center gap-4 p-3 rounded-xl transition-all duration-200 group relative",
        isActive
          ? "bg-white/10 text-white shadow-sm"
          : "text-white/40 hover:text-white hover:bg-white/5"
      )}
    >
      <span className={cn(
         "transition-transform duration-200",
         isActive ? "scale-100" : "group-hover:scale-110"
      )}>
         {item.icon}
      </span>

      <AnimatePresence>
        {isExpanded && (
           <motion.span 
             initial={{ opacity: 0, x: -10 }}
             animate={{ opacity: 1, x: 0 }}
             exit={{ opacity: 0, x: -10 }}
             transition={{ duration: 0.2 }}
             className="text-sm font-medium whitespace-nowrap"
           >
             {item.label}
           </motion.span>
        )}
      </AnimatePresence>
      
      {isActive && (
         <motion.div 
           layoutId="active-pill"
           className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-white rounded-r-full"
         />
      )}
    </button>
  );
};

export default SidebarButton;
