import React from 'react';
import { motion } from 'framer-motion';
import { Trash2 } from 'lucide-react';
import AvelineCore from '../AvelineCore';
import { EMOTIONS } from '../../utils/emotion';

interface PetAvatarProps {
    emotion: string;
    isDragging: boolean;
    isDragOver?: boolean;
    status?: 'idle' | 'thinking' | 'speaking' | 'listening';
    action?: 'idle' | 'feed' | 'drink' | 'play' | 'sleep' | 'pet' | 'trash';
    scale?: number;
    onPointerDown?: (e: React.PointerEvent) => void;
    onPointerUp?: (e: React.PointerEvent) => void;
    onContextMenu?: (e: React.MouseEvent) => void;
    onMouseEnter?: () => void;
    onMouseLeave?: () => void;
}

export const PetAvatar: React.FC<PetAvatarProps> = ({
    emotion,
    isDragging,
    isDragOver = false,
    status = 'idle',
    action = 'idle',
    scale = 1,
    onPointerDown,
    onPointerUp,
    onContextMenu,
    onMouseEnter,
    onMouseLeave
}) => {
    const currentEmotion = EMOTIONS[emotion as keyof typeof EMOTIONS] || EMOTIONS.neutral;
    
    // Map status to AvelineCore supported status
    const coreStatus = status === 'listening' ? 'thinking' : status;

    const actionAnimation = (() => {
        if (isDragging) return { scale: scale * 1.1, opacity: 0.9 };
        if (action === 'feed') return { scale: scale * 1.07, rotate: [0, -3, 3, 0] };
        if (action === 'drink') return { scale: scale * 1.06, y: [0, -2, 0] };
        if (action === 'play') return { rotate: [0, -6, 6, 0] };
        if (action === 'sleep') return { scale: scale * 0.98, opacity: 0.85 };
        if (action === 'pet') return { 
            scale: [scale, scale * 1.1, scale],
            rotate: [0, -5, 5, 0],
            filter: ["brightness(1)", "brightness(1.2)", "brightness(1)"],
            transition: { duration: 0.5 }
        };
        if (action === 'trash') return { rotate: [0, 8, -8, 0] };
        return { scale: scale, opacity: 1 };
    })();

    return (
        <div
            className="relative group"
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <motion.div
                whileHover={{ scale: scale * 1.05 }}
                whileTap={{ scale: scale * 0.95 }}
                animate={actionAnimation as any}
                onPointerDown={onPointerDown}
                onPointerUp={onPointerUp}
                onContextMenu={onContextMenu}
                className={`w-32 h-32 relative ${isDragging ? 'cursor-grabbing' : 'cursor-move'}`}
            >
                {/* Background Glow */}
                <div
                    className="absolute inset-0 rounded-full blur-2xl opacity-40 transition-colors duration-500"
                    style={{ backgroundColor: isDragOver ? '#ef4444' : currentEmotion.colors[1] }}
                />

                {/* 3D Component */}
                <div className="w-full h-full rounded-full overflow-hidden relative z-10">
                    <AvelineCore
                        status={coreStatus}
                        emotionColor={isDragOver ? '#ef4444' : currentEmotion.colors[0]}
                        audioLevel={0}
                    />

                    {/* Trash Icon Overlay when Dragging */}
                    {isDragOver && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/40 text-white">
                            <Trash2 size={32} />
                        </div>
                    )}
                </div>
            </motion.div>
        </div>
    );
};
