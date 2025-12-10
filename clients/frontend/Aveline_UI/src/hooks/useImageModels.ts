import { useState, useEffect } from 'react';
import { api } from '../api/apiService';

export interface ImageModelInfo {
    name: string;
    path: string;
    is_default?: boolean;
}

export interface ImageModelsData {
    sd15: {
        checkpoints: ImageModelInfo[];
        loras: ImageModelInfo[];
    };
    sdxl: {
        models: ImageModelInfo[];
    };
}

export const useImageModels = () => {
    const [models, setModels] = useState<ImageModelsData>({ 
        sd15: { checkpoints: [], loras: [] }, 
        sdxl: { models: [] } 
    });
    const [loading, setLoading] = useState(false);
    
    // Selection State
    const [selectedType, setSelectedType] = useState<'sd15' | 'sdxl'>('sd15');
    const [selectedCheckpoint, setSelectedCheckpoint] = useState<string>('');
    const [selectedLora, setSelectedLora] = useState<string>('');
    const [loraWeight, setLoraWeight] = useState<number>(0.7);

    useEffect(() => {
        setLoading(true);
        api.getImageModels({ silent: true })
            .then(res => {
                if (res.status === 'success' && res.data) {
                    setModels(res.data);
                    
                    // Set defaults
                    if (res.data.sd15?.checkpoints?.length > 0) {
                         setSelectedCheckpoint(res.data.sd15.checkpoints[0].path);
                    }
                }
            })
            .catch(err => console.error("Failed to load image models", err))
            .finally(() => setLoading(false));
    }, []);

    // Helper to get current generation params
    const getGenerationParams = () => {
        if (selectedType === 'sdxl') {
            // Allow user to select SDXL model if multiple exist, otherwise default
            const sdxlModel = models.sdxl.models.find(m => m.path === selectedCheckpoint) || models.sdxl.models[0];
            return {
                modelPath: sdxlModel ? sdxlModel.path : undefined,
                loraPath: selectedLora || undefined,
                loraWeight: selectedLora ? loraWeight : undefined
            };
        } else {
            return {
                modelPath: selectedCheckpoint,
                loraPath: selectedLora || undefined,
                loraWeight: selectedLora ? loraWeight : undefined
            };
        }
    };

    return {
        models,
        loading,
        selectedType,
        setSelectedType,
        selectedCheckpoint,
        setSelectedCheckpoint,
        selectedLora,
        setSelectedLora,
        loraWeight,
        setLoraWeight,
        getGenerationParams
    };
};
