import React from 'react';
import { motion } from 'framer-motion';
import { Send } from 'lucide-react';

interface PetInputProps {
    value: string;
    onChange: (val: string) => void;
    onSend: () => void;
    onClose?: () => void;
}

export const PetInput: React.FC<PetInputProps> = ({ value, onChange, onSend, onClose }) => {
    return (
        <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-4 w-60 relative"
        >
            {onClose && (
                <button 
                    onClick={onClose}
                    className="absolute -top-6 right-0 text-white/50 hover:text-white text-xs"
                >
                    Close
                </button>
            )}
            <div className="bg-slate-800/90 backdrop-blur-md rounded-full p-1 flex items-center border border-slate-700 shadow-xl">
                <input
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && onSend()}
                    placeholder="Say something..."
                    className="bg-transparent border-none text-white text-xs px-3 py-1 flex-1 focus:outline-none placeholder:text-slate-500"
                    autoFocus
                />
                <button
                    onClick={onSend}
                    disabled={!value.trim()}
                    className="p-1.5 bg-indigo-500 text-white rounded-full hover:bg-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Send size={12} />
                </button>
            </div>
        </motion.div>
    );
};
