import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, Check, Folder, ChevronRight } from 'lucide-react';

export interface Option {
  value: string;
  label: string;
  sub?: string;
}

export interface GroupedOption {
  label: string;
  options: Option[];
}

export const CustomSelect = ({ 
  value, 
  onChange, 
  options, 
  groupedOptions,
  placeholder, 
  triggerHaptic,
  disabled = false,
  className = ""
}: { 
  value: string; 
  onChange: (val: string) => void; 
  options?: Option[]; 
  groupedOptions?: GroupedOption[];
  placeholder?: string;
  triggerHaptic?: () => void;
  disabled?: boolean;
  className?: string;
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [buttonRect, setButtonRect] = useState<DOMRect | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  // Flatten options for finding selected label
  const allOptions = React.useMemo(() => {
    const flat = options || [];
    const grouped = groupedOptions ? groupedOptions.flatMap(g => g.options) : [];
    return [...flat, ...grouped];
  }, [options, groupedOptions]);

  const updateRect = () => {
    if (containerRef.current) {
      setButtonRect(containerRef.current.getBoundingClientRect());
    }
  };

  useEffect(() => {
    if (isOpen) {
      updateRect();
      window.addEventListener('resize', updateRect);
      window.addEventListener('scroll', updateRect, true);
    }
    return () => {
      window.removeEventListener('resize', updateRect);
      window.removeEventListener('scroll', updateRect, true);
    };
  }, [isOpen]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        // Also check if click is inside portal content
        const portal = document.getElementById('custom-select-portal-' + uniqueId);
        if (portal && !portal.contains(event.target as Node)) {
          setIsOpen(false);
        }
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Initialize expanded groups - auto expand the group containing the selected value
  useEffect(() => {
    if (groupedOptions && value) {
      const group = groupedOptions.find(g => g.options.some(o => o.value === value));
      if (group) {
        setExpandedGroups(prev => ({ ...prev, [group.label]: true }));
      }
    }
  }, [groupedOptions, value]);

  const toggleGroup = (label: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedGroups(prev => ({ ...prev, [label]: !prev[label] }));
    triggerHaptic?.();
  };

  const selectedOption = allOptions.find(o => o.value === value);
  const uniqueId = React.useRef(Math.random().toString(36).substr(2, 9)).current;

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <button
        onClick={() => {
          if (!disabled) {
            updateRect();
            setIsOpen(!isOpen);
            triggerHaptic?.();
          }
        }}
        disabled={disabled}
        className={`w-full flex items-center justify-between bg-black/20 text-white text-sm px-3 py-3 rounded-xl border border-white/10 transition-all ${
          isOpen ? 'border-emerald-500/30 bg-black/30' : 'hover:bg-white/5'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <div className="flex flex-col items-start truncate pr-2">
          <span className="font-mono text-white/90 truncate w-full text-left">
            {selectedOption ? selectedOption.label : placeholder || 'Select...'}
          </span>
        </div>
        <ChevronDown 
          size={14} 
          className={`text-white/30 transition-transform duration-200 flex-shrink-0 ${isOpen ? 'rotate-180' : ''}`} 
        />
      </button>

      {buttonRect && createPortal(
        <AnimatePresence>
          {isOpen && (
            <motion.div
              id={'custom-select-portal-' + uniqueId}
              initial={{ opacity: 0, y: 5, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 5, scale: 0.98 }}
              transition={{ duration: 0.1 }}
              style={{
                position: 'fixed',
                top: buttonRect.bottom + 8,
                left: buttonRect.left,
                width: buttonRect.width,
                zIndex: 9999
              }}
              className="max-h-60 overflow-y-auto custom-scrollbar bg-zinc-900/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl p-1"
            >
              {/* Flat Options */}
              {options && options.length > 0 && options.map((opt) => (
                <OptionItem 
                  key={opt.value} 
                  option={opt} 
                  isSelected={value === opt.value} 
                  onClick={() => {
                    onChange(opt.value);
                    setIsOpen(false);
                    triggerHaptic?.();
                  }} 
                />
              ))}

              {/* Grouped Options */}
              {groupedOptions && groupedOptions.map((group) => (
                <div key={group.label} className="mb-1">
                  <button
                    onClick={(e) => toggleGroup(group.label, e)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs font-bold text-white/40 uppercase tracking-wider hover:bg-white/5 rounded-lg transition-colors"
                  >
                    <Folder size={10} />
                    <span className="flex-1 text-left truncate">{group.label}</span>
                    <ChevronRight 
                      size={10} 
                      className={`transition-transform duration-200 ${expandedGroups[group.label] ? 'rotate-90' : ''}`}
                    />
                  </button>
                  <AnimatePresence>
                    {expandedGroups[group.label] && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden ml-2 border-l border-white/5"
                      >
                        {group.options.map(opt => (
                          <OptionItem 
                            key={opt.value} 
                            option={opt} 
                            isSelected={value === opt.value} 
                            onClick={() => {
                              onChange(opt.value);
                              setIsOpen(false);
                              triggerHaptic?.();
                            }} 
                          />
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}

              {(!options?.length && !groupedOptions?.length) && (
                <div className="px-3 py-2 text-xs text-white/30 font-mono text-center">No options available</div>
              )}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </div>
  );
};

const OptionItem = ({ option, isSelected, onClick }: { option: Option, isSelected: boolean, onClick: () => void }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-mono transition-colors ${
      isSelected 
        ? 'bg-emerald-500/10 text-emerald-400' 
        : 'text-white/60 hover:bg-white/5 hover:text-white'
    }`}
  >
    <div className="flex flex-col items-start truncate">
      <span className="truncate w-full text-left">{option.label}</span>
      {option.sub && <span className="text-[9px] opacity-50">{option.sub}</span>}
    </div>
    {isSelected && <Check size={12} className="text-emerald-500 ml-2 flex-shrink-0" />}
  </button>
);

