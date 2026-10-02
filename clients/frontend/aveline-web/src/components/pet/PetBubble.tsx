import React from 'react';
import { motion } from 'framer-motion';
import { Volume2 } from 'lucide-react';
import { Message } from '../../types';

interface PetBubbleProps {
    message: string;
    visible?: boolean;
    onPlayTTS?: (text: string) => void;
}

export const PetBubble: React.FC<PetBubbleProps> = ({ message, visible = true, onPlayTTS }) => {
    if (!visible) return null;
    
    return (
        <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="mb-4 p-3 bg-white/90 dark:bg-slate-800/90 backdrop-blur-md rounded-2xl shadow-lg max-w-[200px] text-xs border border-white/20 relative group/bubble"
        >
            <div className="line-clamp-4 text-slate-700 dark:text-slate-200">
                {message}
            </div>
            {/* TTS Button */}
            {onPlayTTS && (
                <button
                    onClick={(e) => { e.stopPropagation(); onPlayTTS(message); }}
                    className="absolute top-1 right-1 opacity-60 hover:opacity-100 transition-opacity p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                    title="Play TTS"
                >
                    <Volume2 size={14} />
                </button>
            )}
            {/* Triangle */}
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-white/90 dark:bg-slate-800/90 rotate-45" />
        </motion.div>
    );
};
