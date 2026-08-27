import { useState } from 'react';

interface UseFileDropProps {
    isElectron: boolean;
    onFileTrash: (count: number) => void;
}

export const useFileDrop = ({ isElectron, onFileTrash }: UseFileDropProps) => {
    const [isDragOver, setIsDragOver] = useState(false);

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(true);
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);

        if (isElectron && e.dataTransfer.files.length > 0) {
            const files = Array.from(e.dataTransfer.files);
            const { shell } = (window as any).require('electron');

            let deletedCount = 0;
            files.forEach((file: any) => { // Cast to any to access 'path'
                try {
                    if (file.path) {
                        shell.trashItem(file.path);
                        deletedCount++;
                    }
                } catch (err) {
                    console.error("Failed to trash item", file.path, err);
                }
            });

            if (deletedCount > 0) {
                onFileTrash(deletedCount);
            }
        }
    };

    return {
        isDragOver,
        handleDragOver,
        handleDragLeave,
        handleDrop
    };
};
