import React, { useState, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface CalendarProps {
    selectedDate: Date | null;
    onSelectDate: (date: Date | null) => void;
    onClose: () => void;
    triggerRef?: React.RefObject<HTMLElement>;
}

export const Calendar: React.FC<CalendarProps> = ({ selectedDate, onSelectDate, onClose, triggerRef }) => {
    const [viewDate, setViewDate] = useState(selectedDate || new Date());
    const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

    useLayoutEffect(() => {
        if (triggerRef?.current) {
            const rect = triggerRef.current.getBoundingClientRect();
            // Default: align left with trigger, but check viewport
            let left = rect.left;
            const calendarWidth = 288; // w-72

            // If goes off right screen
            if (left + calendarWidth > window.innerWidth) {
                left = window.innerWidth - calendarWidth - 20;
            }
            
            // Safety check for left overflow
            left = Math.max(10, left);

            setPosition({
                top: rect.bottom + 8,
                left: left
            });
        }
    }, [triggerRef]);

    const getDaysInMonth = (year: number, month: number) => new Date(year, month + 1, 0).getDate();
    const getFirstDayOfMonth = (year: number, month: number) => new Date(year, month, 1).getDay();

    const currentYear = viewDate.getFullYear();
    const currentMonth = viewDate.getMonth();
    const daysInMonth = getDaysInMonth(currentYear, currentMonth);
    const firstDay = getFirstDayOfMonth(currentYear, currentMonth);

    const monthNames = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ];

    const handlePrevMonth = () => {
        setViewDate(new Date(currentYear, currentMonth - 1, 1));
    };

    const handleNextMonth = () => {
        setViewDate(new Date(currentYear, currentMonth + 1, 1));
    };

    const handleDayClick = (day: number) => {
        const newDate = new Date(currentYear, currentMonth, day);
        // Toggle: if clicking the already selected date, clear it
        if (selectedDate && 
            selectedDate.getDate() === day && 
            selectedDate.getMonth() === currentMonth && 
            selectedDate.getFullYear() === currentYear) {
            onSelectDate(null);
        } else {
            onSelectDate(newDate);
        }
    };

    const isSelected = (day: number) => {
        return selectedDate && 
               selectedDate.getDate() === day && 
               selectedDate.getMonth() === currentMonth && 
               selectedDate.getFullYear() === currentYear;
    };

    const isToday = (day: number) => {
        const today = new Date();
        return today.getDate() === day && 
               today.getMonth() === currentMonth && 
               today.getFullYear() === currentYear;
    };

    const content = (
        <motion.div 
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            style={triggerRef && position ? {
                position: 'fixed',
                top: position.top,
                left: position.left,
                zIndex: 9999
            } : undefined}
            className={triggerRef 
                ? "bg-[#0a0a0a] border border-white/10 rounded-xl shadow-2xl p-4 w-72 backdrop-blur-xl" 
                : "absolute z-50 top-full mt-2 right-0 bg-[#0a0a0a] border border-white/10 rounded-xl shadow-2xl p-4 w-72 backdrop-blur-xl"
            }
        >
            <div className="flex items-center justify-between mb-4">
                <button 
                    onClick={handlePrevMonth}
                    className="p-1 hover:bg-white/10 rounded-lg text-white/60 hover:text-white transition-colors"
                >
                    <ChevronLeft size={16} />
                </button>
                <div className="text-sm font-bold text-white/90 font-display">
                    {monthNames[currentMonth]} {currentYear}
                </div>
                <div className="flex items-center gap-1">
                    <button 
                        onClick={handleNextMonth}
                        className="p-1 hover:bg-white/10 rounded-lg text-white/60 hover:text-white transition-colors"
                    >
                        <ChevronRight size={16} />
                    </button>
                    <button 
                        onClick={onClose}
                        className="p-1 hover:bg-rose-500/10 rounded-lg text-white/40 hover:text-rose-400 transition-colors ml-1"
                    >
                        <X size={16} />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-7 gap-1 mb-2">
                {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(day => (
                    <div key={day} className="text-center text-[10px] text-white/30 font-mono">
                        {day}
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-7 gap-1">
                {Array.from({ length: firstDay }).map((_, i) => (
                    <div key={`empty-${i}`} />
                ))}
                {Array.from({ length: daysInMonth }).map((_, i) => {
                    const day = i + 1;
                    const selected = isSelected(day);
                    const today = isToday(day);

                    return (
                        <button
                            key={day}
                            onClick={() => handleDayClick(day)}
                            className={`
                                h-8 w-8 rounded-lg text-xs font-medium transition-all
                                flex items-center justify-center relative
                                ${selected 
                                    ? 'bg-emerald-500 text-black font-bold shadow-lg shadow-emerald-500/20' 
                                    : 'text-white/70 hover:bg-white/10 hover:text-white'
                                }
                                ${today && !selected ? 'border border-emerald-500/30 text-emerald-400' : ''}
                            `}
                        >
                            {day}
                            {today && !selected && (
                                <div className="absolute bottom-1 w-1 h-1 rounded-full bg-emerald-500"></div>
                            )}
                        </button>
                    );
                })}
            </div>
            
            <div className="mt-4 pt-3 border-t border-white/5 flex justify-between items-center">
                 <button 
                    onClick={() => {
                        onSelectDate(new Date());
                    }}
                    className="text-[10px] text-emerald-400/70 hover:text-emerald-300 font-mono uppercase tracking-wider"
                >
                    Jump to Today
                </button>
                {selectedDate && (
                    <button 
                        onClick={() => onSelectDate(null)}
                        className="text-[10px] text-white/30 hover:text-white/50 font-mono uppercase tracking-wider"
                    >
                        Clear
                    </button>
                )}
            </div>
        </motion.div>
    );

    if (triggerRef) {
        // Wait for position to be calculated
        if (!position) return null;
        return createPortal(content, document.body);
    }

    return content;
};
