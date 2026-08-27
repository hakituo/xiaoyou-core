import { useState, useRef, useEffect } from 'react';
import { DragControls } from 'framer-motion';

interface UsePetDragProps {
    isElectron: boolean;
    ipcRenderer: any;
    dragControls: DragControls;
    onInteract: () => void;
}

export const usePetDrag = ({ isElectron, ipcRenderer, dragControls, onInteract }: UsePetDragProps) => {
    const [isDragging, setIsDragging] = useState(false);
    const dragStartRef = useRef<{ x: number; y: number } | null>(null);
    const longPressTimerRef = useRef<NodeJS.Timeout | null>(null);

    const handlePointerDown = (e: React.PointerEvent) => {
        if (!isElectron) {
            dragControls.start(e);
            return;
        }
        // For Electron, implement Long Press to Drag
        if (e.button === 0) { // Left click only
            dragStartRef.current = { x: e.screenX, y: e.screenY };

            // Start Long Press Timer (e.g., 500ms)
            longPressTimerRef.current = setTimeout(() => {
                setIsDragging(true);
            }, 500);
        }
    };

    const handlePointerUp = (e: React.PointerEvent) => {
        // Clear timer immediately on release
        if (longPressTimerRef.current) {
            clearTimeout(longPressTimerRef.current);
            longPressTimerRef.current = null;
        }

        if (isDragging) {
            setIsDragging(false);
            dragStartRef.current = null;
        } else {
            // If not dragging, check if it was a valid click
            if (dragStartRef.current) {
                const dist = Math.sqrt(
                    Math.pow(e.screenX - dragStartRef.current.x, 2) +
                    Math.pow(e.screenY - dragStartRef.current.y, 2)
                );
                // If moved less than 5 pixels, treat as click -> Interact
                if (dist < 5) {
                    onInteract();
                }
            }
            dragStartRef.current = null;
        }
    };

    // Global mouse move/up listener for dragging robustness
    useEffect(() => {
        if (!isElectron || !ipcRenderer) return;

        const handleGlobalMouseMove = (e: MouseEvent) => {
            if (isDragging) {
                // Use movementX/Y for delta
                const dx = e.movementX;
                const dy = e.movementY;

                if (dx !== 0 || dy !== 0) {
                    ipcRenderer.send('window-move', { x: dx, y: dy });
                }
            } else if (dragStartRef.current) {
                // If we move too much while holding down BEFORE timer fires, cancel the timer
                const dist = Math.sqrt(
                    Math.pow(e.screenX - dragStartRef.current.x, 2) +
                    Math.pow(e.screenY - dragStartRef.current.y, 2)
                );
                if (dist > 10) {
                    if (longPressTimerRef.current) {
                        clearTimeout(longPressTimerRef.current);
                        longPressTimerRef.current = null;
                    }
                }
            }
        };

        const handleGlobalMouseUp = () => {
            if (longPressTimerRef.current) {
                clearTimeout(longPressTimerRef.current);
                longPressTimerRef.current = null;
            }
            if (isDragging) {
                setIsDragging(false);
            }
            dragStartRef.current = null;
        };

        window.addEventListener('mousemove', handleGlobalMouseMove);
        window.addEventListener('mouseup', handleGlobalMouseUp);
        window.addEventListener('pointerup', handleGlobalMouseUp);

        return () => {
            window.removeEventListener('mousemove', handleGlobalMouseMove);
            window.removeEventListener('mouseup', handleGlobalMouseUp);
            window.removeEventListener('pointerup', handleGlobalMouseUp);
        };
    }, [isDragging, isElectron, ipcRenderer]);

    return {
        isDragging,
        handlePointerDown,
        handlePointerUp
    };
};
