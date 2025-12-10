import React, { useState, useEffect, useRef } from 'react';
import { motion, useDragControls } from 'framer-motion';
import { X, MessageSquare, Mic, Image as ImageIcon } from 'lucide-react';
import { Message } from '../types';

interface DesktopPetProps {
  emotion: string;
  isTyping: boolean;
  lastMessage: Message | null;
  onClose: () => void;
  onInteract: () => void;
}

const DesktopPet: React.FC<DesktopPetProps> = ({ 
  emotion, 
  isTyping, 
  lastMessage, 
  onClose,
  onInteract
}) => {
  const dragControls = useDragControls();
  const [showBubble, setShowBubble] = useState(false);
  
  // Check for Electron
  const isElectron = typeof window !== 'undefined' && 
    navigator.userAgent.toLowerCase().includes('electron');
  
  // Get IPC if available
  const ipcRenderer = isElectron && (window as any).require 
    ? (window as any).require('electron').ipcRenderer 
    : null;

  // Auto-show bubble when new message arrives
  useEffect(() => {
    if (lastMessage && !lastMessage.isUser) {
      setShowBubble(true);
      const timer = setTimeout(() => setShowBubble(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [lastMessage]);

  // Handle Electron Click-Through
  useEffect(() => {
    if (isElectron && ipcRenderer) {
      // Initially let clicks pass through (forward: true means forward to OS)
      ipcRenderer.send('set-ignore-mouse-events', true, { forward: true });
    }
  }, [isElectron, ipcRenderer]);

  const handleMouseEnter = () => {
    if (isElectron && ipcRenderer) {
      // Capture mouse events when hovering the pet
      ipcRenderer.send('set-ignore-mouse-events', false);
    }
  };

  const handleMouseLeave = () => {
    if (isElectron && ipcRenderer) {
      // Let clicks pass through when leaving the pet
      ipcRenderer.send('set-ignore-mouse-events', true, { forward: true });
    }
  };

  // Emotion color mapping
  const getEmotionColor = (emo: string) => {
    const map: Record<string, string> = {
      happy: 'bg-emerald-400',
      sad: 'bg-blue-400',
      angry: 'bg-red-400',
      anxious: 'bg-amber-400',
      excited: 'bg-pink-400',
      neutral: 'bg-slate-300',
      tired: 'bg-purple-300',
      shy: 'bg-rose-300',
      jealous: 'bg-lime-400',
      wronged: 'bg-indigo-300',
      lost: 'bg-gray-400',
      coquetry: 'bg-fuchsia-400'
    };
    return map[emo.toLowerCase()] || 'bg-slate-300';
  };

  return (
    <motion.div
      drag={!isElectron}
      dragControls={dragControls}
      dragMomentum={false}
      initial={!isElectron ? { x: window.innerWidth - 150, y: window.innerHeight - 150 } : undefined}
      className={`fixed z-50 flex flex-col items-center pointer-events-auto ${isElectron ? 'inset-0 justify-center w-full h-full' : ''}`}
    >
      <div 
        className="flex flex-col items-center relative"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {/* Chat Bubble */}
        {showBubble && lastMessage && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="mb-2 p-3 bg-white/90 dark:bg-slate-800/90 backdrop-blur-md rounded-2xl shadow-lg max-w-[200px] text-xs border border-white/20 relative"
          >
            <div className="line-clamp-4 text-slate-700 dark:text-slate-200">
              {lastMessage.text}
            </div>
            {/* Triangle */}
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-white/90 dark:bg-slate-800/90 rotate-45" />
          </motion.div>
        )}

        {/* Pet Avatar Container */}
        <div className="relative group">
          {/* Controls (visible on hover) */}
          <div className="absolute -top-8 left-1/2 -translate-x-1/2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button 
              onClick={onInteract}
              className="p-1.5 bg-slate-800 text-white rounded-full hover:bg-slate-700 shadow-sm"
              title="Open Chat"
              style={isElectron ? { WebkitAppRegion: 'no-drag' } as any : {}}
            >
              <MessageSquare size={12} />
            </button>
            <button 
              onClick={onClose}
              className="p-1.5 bg-rose-500 text-white rounded-full hover:bg-rose-600 shadow-sm"
              title="Close Pet Mode"
              style={isElectron ? { WebkitAppRegion: 'no-drag' } as any : {}}
            >
              <X size={12} />
            </button>
          </div>

          {/* Avatar Body */}
          <motion.div
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            animate={{ 
              y: isTyping ? [0, -5, 0] : 0,
            }}
            transition={{ 
              y: { repeat: isTyping ? Infinity : 0, duration: 0.6 }
            }}
            onPointerDown={(e) => !isElectron && dragControls.start(e)}
            className={`w-24 h-24 rounded-full shadow-2xl border-4 border-white dark:border-slate-700 flex items-center justify-center relative overflow-hidden bg-slate-100 dark:bg-slate-800 cursor-move ${isTyping ? 'ring-2 ring-sky-400' : ''}`}
            style={isElectron ? { WebkitAppRegion: 'drag' } as any : {}}
          >
            {/* Background / Aura based on emotion */}
            <div className={`absolute inset-0 opacity-20 ${getEmotionColor(emotion)} blur-xl`} />
            
            {/* Simple Face Construction (CSS Art) */}
            <div className="relative z-10 flex flex-col items-center">
              {/* Eyes */}
              <div className="flex gap-4 mb-1">
                <motion.div 
                  animate={{ scaleY: isTyping ? [1, 0.1, 1] : 1 }}
                  transition={{ duration: 3, repeat: Infinity, repeatDelay: Math.random() * 5 }}
                  className="w-2 h-3 bg-slate-700 dark:bg-slate-200 rounded-full" 
                />
                <motion.div 
                  animate={{ scaleY: isTyping ? [1, 0.1, 1] : 1 }}
                  transition={{ duration: 3, repeat: Infinity, repeatDelay: Math.random() * 5 }}
                  className="w-2 h-3 bg-slate-700 dark:bg-slate-200 rounded-full" 
                />
              </div>
              
              {/* Blush */}
              {(emotion === 'shy' || emotion === 'excited' || emotion === 'coquetry') && (
                <div className="flex gap-8 absolute top-4 w-full justify-center opacity-50">
                  <div className="w-2 h-1 bg-rose-400 rounded-full blur-[1px]" />
                  <div className="w-2 h-1 bg-rose-400 rounded-full blur-[1px]" />
                </div>
              )}

              {/* Mouth */}
              <div className="mt-1">
                {emotion === 'happy' && <div className="w-4 h-2 border-b-2 border-slate-700 dark:border-slate-200 rounded-full" />}
                {emotion === 'sad' && <div className="w-4 h-2 border-t-2 border-slate-700 dark:border-slate-200 rounded-full mt-1" />}
                {emotion === 'angry' && <div className="w-4 h-1 bg-slate-700 dark:border-slate-200 rounded-full" />}
                {(emotion === 'neutral' || !emotion) && <div className="w-2 h-2 bg-slate-700 dark:bg-slate-200 rounded-full" />}
                {isTyping && <div className="w-3 h-3 border-2 border-slate-700 dark:border-slate-200 rounded-full animate-pulse" />}
              </div>
            </div>

            {/* Status Icons Overlay */}
            <div className="absolute bottom-2 right-2 flex gap-1">
               {/* If generating image or voice, maybe show small icon */}
            </div>
          </motion.div>
        </div>
      </div>
    </motion.div>
  );
};

export default DesktopPet;
