import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Settings, X } from 'lucide-react';
import { SessionList } from '../SessionList';

type NavItem = {
  id: string;
  icon: React.ReactNode;
  label: string;
};

type MobileSidebarProps = {
  show: boolean;
  connected: boolean;
  activeTab: string;
  navItems: NavItem[];
  currentSessionId: string | null;
  onClose: () => void;
  onOpenSettings: () => void;
  onNavigate: (tabId: string) => void;
  onSelectSession: (id: string) => void;
  onCreateSession: () => void;
  onRequestConfirm: (opts: any) => void;
  triggerHaptic: () => void;
  onTouchStart: (e: React.TouchEvent) => void;
  onTouchMove: (e: React.TouchEvent) => void;
  onTouchEnd: () => void;
};

export function MobileSidebar({
  show,
  connected,
  activeTab,
  navItems,
  currentSessionId,
  onClose,
  onOpenSettings,
  onNavigate,
  onSelectSession,
  onCreateSession,
  onRequestConfirm,
  triggerHaptic,
  onTouchStart,
  onTouchMove,
  onTouchEnd,
}: MobileSidebarProps) {
  return (
    <AnimatePresence>
      {show && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 z-[60] bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="absolute inset-y-0 left-0 w-[80%] max-w-xs z-[70] bg-zinc-900/95 backdrop-blur-2xl flex flex-col shadow-2xl border-r border-white/5"
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
            onTouchCancel={onTouchEnd}
          >
            <div className="flex flex-col h-full pt-[env(safe-area-inset-top)]">
              <div className="p-6 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full ring-4 ring-opacity-20 transition-all duration-500 ${connected ? 'bg-emerald-400 ring-emerald-400' : 'bg-rose-500 ring-rose-500'}`} />
                  <span className="font-cinzel font-bold text-xl tracking-widest text-white">AVELINE</span>
                </div>
                <button onClick={() => { onClose(); triggerHaptic(); }} className="p-2 -mr-2 text-white/40">
                  <X size={20} />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-1">
                <div className="text-[10px] font-bold text-white/20 uppercase tracking-[0.2em] px-3 mb-2 mt-4">Navigation</div>
                {navItems.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      onNavigate(item.id);
                      onClose();
                      triggerHaptic();
                    }}
                    className={`w-full flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 ${
                      activeTab === item.id
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      : 'text-white/40 hover:text-white hover:bg-white/5 border border-transparent'
                    }`}
                  >
                    <span className={activeTab === item.id ? 'scale-110' : ''}>{item.icon}</span>
                    <span className="font-medium">{item.label}</span>
                  </button>
                ))}

                <div className="text-[10px] font-bold text-white/20 uppercase tracking-[0.2em] px-3 mb-2 mt-8">Navigation</div>
                {/* [MODIFIED] Removed Topic History */}
              </div>

              <div className="p-4 mt-auto border-t border-white/5 space-y-2">
                <button
                  onClick={() => {
                    onOpenSettings();
                    onClose();
                    triggerHaptic();
                  }}
                  className="w-full flex items-center gap-4 px-4 py-3.5 rounded-2xl text-white/40 hover:text-white hover:bg-white/5 transition-all"
                >
                  <Settings size={20} />
                  <span className="font-medium">Settings</span>
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
