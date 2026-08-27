import { useEffect } from 'react';

export const usePetMovement = (
    isElectron: boolean,
    ipcRenderer: any,
    isDragging: boolean,
    isInteracting: boolean // e.g. input open, context menu open
) => {
    useEffect(() => {
        if (!isElectron || !ipcRenderer || isDragging || isInteracting) return;

        // Auto-move logic
        const interval = setInterval(() => {
            if (Math.random() > 0.7) { // 30% chance to move
                const moveX = Math.floor((Math.random() - 0.5) * 50); // -25 to 25 px
                ipcRenderer.send('window-move', { x: moveX, y: 0 });
            }
        }, 5000);

        return () => clearInterval(interval);
    }, [isElectron, ipcRenderer, isDragging, isInteracting]);
};
