import React from 'react';
import { MessageSquare, Mic, X, Loader2 } from 'lucide-react';

interface PetControlsProps {
    showInput: boolean;
    onToggleInput: () => void;
    isRecording: boolean;
    isProcessing: boolean;
    onToggleRecording: () => void;
    onClose: () => void;
    visible: boolean;
}

export const PetControls: React.FC<PetControlsProps> = ({
    showInput,
    onToggleInput,
    isRecording,
    isProcessing,
    onToggleRecording,
    onClose,
    visible
}) => {
    return (
        <div className={`absolute -top-10 left-1/2 -translate-x-1/2 flex gap-2 transition-opacity duration-200 z-20 ${visible ? 'opacity-100' : 'opacity-0'}`}>
            <button
                onClick={(e) => { e.stopPropagation(); onToggleInput(); }}
                className={`p-2 rounded-full shadow-sm backdrop-blur-sm transition-colors ${showInput ? 'bg-emerald-500 text-white' : 'bg-slate-800/80 text-white hover:bg-slate-700'}`}
                title="Toggle Chat"
            >
                <MessageSquare size={14} />
            </button>
            <button
                onClick={(e) => { e.stopPropagation(); onToggleRecording(); }}
                className={`p-2 rounded-full shadow-sm backdrop-blur-sm transition-colors ${isRecording ? 'bg-red-500 text-white animate-pulse' : 'bg-slate-800/80 text-white hover:bg-slate-700'}`}
                title="Voice Chat"
            >
                {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
            </button>
            <button
                onClick={(e) => { e.stopPropagation(); onClose(); }}
                className="p-2 bg-rose-500/80 text-white rounded-full hover:bg-rose-600 shadow-sm backdrop-blur-sm"
                title="Close Pet Mode"
            >
                <X size={14} />
            </button>
        </div>
    );
};
