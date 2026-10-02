import React, { useEffect } from 'react';
import { MessageSquare, LogOut, Phone, Activity, Utensils, Droplet, Gamepad2, Moon, Settings } from 'lucide-react';

interface PetContextMenuProps {
    x: number;
    y: number;
    onClose: () => void;
    onChat: () => void;
    onDashboard: () => void;
    onCall: () => void;
    onStats: () => void;
    onFeed?: () => void;
    onDrink?: () => void;
    onPlay?: () => void;
    onSleep?: () => void;
    onShop?: () => void;
    onSettings?: () => void;
}

export const PetContextMenu: React.FC<PetContextMenuProps> = ({
    x,
    y,
    onClose,
    onChat,
    onDashboard,
    onCall,
    onStats,
    onFeed,
    onDrink,
    onPlay,
    onSleep,
    onShop,
    onSettings
}) => {
    // Close context menu on click elsewhere
    useEffect(() => {
        const handleClick = () => onClose();
        window.addEventListener('click', handleClick);
        return () => window.removeEventListener('click', handleClick);
    }, [onClose]);

    return (
        <div
            className="fixed z-[60] bg-slate-800/90 backdrop-blur-md border border-slate-700 text-slate-200 rounded-lg shadow-xl py-1 w-40 flex flex-col overflow-hidden"
            style={{ left: x, top: y }}
            onContextMenu={(e) => e.preventDefault()}
        >
            {onFeed && (
                <button
                    onClick={(e) => { e.stopPropagation(); onFeed(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Utensils size={14} className="text-orange-400" />
                    <span>Feed</span>
                </button>
            )}
            {onDrink && (
                <button
                    onClick={(e) => { e.stopPropagation(); onDrink(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Droplet size={14} className="text-cyan-400" />
                    <span>Drink</span>
                </button>
            )}
            {onPlay && (
                <button
                    onClick={(e) => { e.stopPropagation(); onPlay(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Gamepad2 size={14} className="text-emerald-400" />
                    <span>Play</span>
                </button>
            )}
            {onSleep && (
                <button
                    onClick={(e) => { e.stopPropagation(); onSleep(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Moon size={14} className="text-indigo-300" />
                    <span>Sleep</span>
                </button>
            )}
            {(onFeed || onDrink || onPlay || onSleep) && (
                <div className="h-px bg-slate-700/60 my-1" />
            )}
            <button
                onClick={(e) => { e.stopPropagation(); onChat(); onClose(); }}
                className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
            >
                <MessageSquare size={14} />
                <span>Chat Here</span>
            </button>
            {onShop && (
                <button
                    onClick={(e) => { e.stopPropagation(); onShop(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Utensils size={14} className="text-rose-400" />
                    <span>Food</span>
                </button>
            )}
            {onSettings && (
                <button
                    onClick={(e) => { e.stopPropagation(); onSettings(); onClose(); }}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
                >
                    <Settings size={14} className="text-blue-400" />
                    <span>Settings</span>
                </button>
            )}
            <button
                onClick={(e) => { e.stopPropagation(); onDashboard(); onClose(); }}
                className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
            >
                <LogOut size={14} className="rotate-180" />
                <span>Open Dashboard</span>
            </button>
            <button
                onClick={(e) => {
                    e.stopPropagation();
                    onCall();
                    onClose();
                }}
                className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
            >
                <Phone size={14} className="text-green-400" />
                <span>Call Aveline</span>
            </button>
            <button
                onClick={(e) => { e.stopPropagation(); onStats(); onClose(); }}
                className="flex items-center gap-2 px-4 py-2 hover:bg-slate-700/50 text-sm text-left transition-colors"
            >
                <Activity size={14} className="text-blue-400" />
                <span>Stats</span>
            </button>
        </div>
    );
};
