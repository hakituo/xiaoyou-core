import React, { useMemo } from 'react';
import { Image, Layers, Box } from 'lucide-react';
import { useImageModels } from '../hooks/useImageModels';
import { CustomSelect, Option, GroupedOption } from './ui/CustomSelect';

interface ImageModelSelectorProps {
    imageModel: ReturnType<typeof useImageModels>;
    triggerHaptic?: () => void;
}

const groupModels = (models: { name: string, path: string }[]) => {
    const groups: Record<string, Option[]> = {};
    const flat: Option[] = [];

    models.forEach(m => {
        const parts = m.name.split(/[/\\]/);
        if (parts.length > 1) {
            const folder = parts.slice(0, -1).join('/');
            const label = parts[parts.length - 1];
            if (!groups[folder]) groups[folder] = [];
            groups[folder].push({ value: m.path, label: label });
        } else {
            flat.push({ value: m.path, label: m.name });
        }
    });

    const groupedOptions: GroupedOption[] = Object.entries(groups)
        .map(([label, options]) => ({ label, options }))
        .sort((a, b) => a.label.localeCompare(b.label));

    return { flat, grouped: groupedOptions };
};

const ImageModelSelector: React.FC<ImageModelSelectorProps> = ({ imageModel, triggerHaptic }) => {
    const { 
        models, 
        selectedType, 
        setSelectedType, 
        selectedCheckpoint, 
        setSelectedCheckpoint,
        selectedLora,
        setSelectedLora,
        loraWeight,
        setLoraWeight
    } = imageModel;

    const sd15Checkpoints = models?.sd15?.checkpoints || [];
    const sd15Loras = models?.sd15?.loras || [];
    const sdxlModels = models?.sdxl?.models || [];
    const safeLoraWeight = Number.isFinite(loraWeight) ? loraWeight : 0.7;

    const sd15LorasGrouped = useMemo(() => groupModels(sd15Loras), [sd15Loras]);
    
    // Attempt to group SDXL models if they have folder structure, though typically check points are flat
    const sdxlModelsGrouped = useMemo(() => groupModels(sdxlModels), [sdxlModels]);

    return (
        <div className="p-4 bg-white/5 rounded-xl border border-white/10 space-y-4">
            <div className="flex items-center gap-2 mb-2">
                <Image size={16} className="text-emerald-400" />
                <span className="text-sm font-medium text-white/90">Image Generation Settings</span>
            </div>

            {/* Type Selection */}
            <div className="flex gap-2">
                <button
                    onClick={() => setSelectedType('sd15')}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-colors ${
                        selectedType === 'sd15' 
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
                            : 'bg-white/5 text-white/50 hover:bg-white/10 border border-transparent'
                    }`}
                >
                    SD 1.5
                </button>
                <button
                    onClick={() => setSelectedType('sdxl')}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-colors ${
                        selectedType === 'sdxl' 
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
                            : 'bg-white/5 text-white/50 hover:bg-white/10 border border-transparent'
                    }`}
                >
                    SDXL
                </button>
            </div>

            {selectedType === 'sd15' && (
                <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-300">
                    {/* Checkpoint */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Box size={10} /> Checkpoint
                        </label>
                        <CustomSelect
                            value={selectedCheckpoint}
                            onChange={(val) => setSelectedCheckpoint(val)}
                            options={sd15Checkpoints.map(m => ({ value: m.path, label: m.name }))}
                            triggerHaptic={triggerHaptic}
                            className="w-full"
                        />
                    </div>

                    {/* LoRA */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Layers size={10} /> LoRA
                        </label>
                        <CustomSelect
                            value={selectedLora}
                            onChange={(val) => setSelectedLora(val)}
                            options={[{ value: '', label: 'None' }, ...sd15LorasGrouped.flat]}
                            groupedOptions={sd15LorasGrouped.grouped}
                            triggerHaptic={triggerHaptic}
                            placeholder="Select LoRA..."
                            className="w-full"
                        />
                    </div>

                    {/* LoRA Weight */}
                    {selectedLora && (
                        <div className="space-y-1">
                            <div className="flex justify-between text-[10px] text-white/40">
                                <span>Weight</span>
                                <span>{safeLoraWeight.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min="0.1"
                                max="1.5"
                                step="0.1"
                                value={safeLoraWeight}
                                onChange={(e) => {
                                    const next = parseFloat(e.target.value);
                                    if (Number.isFinite(next)) setLoraWeight(next);
                                }}
                                className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                            />
                        </div>
                    )}
                </div>
            )}

            {selectedType === 'sdxl' && (
                <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-300">
                     {/* SDXL Checkpoint */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Box size={10} /> SDXL Checkpoint
                        </label>
                        <CustomSelect
                            value={selectedCheckpoint}
                            onChange={(val) => setSelectedCheckpoint(val)}
                            options={sdxlModelsGrouped.flat}
                            groupedOptions={sdxlModelsGrouped.grouped}
                            triggerHaptic={triggerHaptic}
                            className="w-full"
                        />
                    </div>

                    {/* SDXL LoRA - Note: Using sdxlModels for LoRA seems to be a placeholder/bug in original code, preserving behavior but updating UI */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Layers size={10} /> SDXL LoRA
                        </label>
                         <CustomSelect
                            value={selectedLora}
                            onChange={(val) => setSelectedLora(val)}
                            options={[{ value: '', label: 'None' }, ...sdxlModelsGrouped.flat]}
                            groupedOptions={sdxlModelsGrouped.grouped}
                            triggerHaptic={triggerHaptic}
                            placeholder="Select LoRA..."
                            className="w-full"
                        />
                    </div>

                    {/* LoRA Weight */}
                    {selectedLora && (
                        <div className="space-y-1">
                            <div className="flex justify-between text-[10px] text-white/40">
                                <span>Weight</span>
                                <span>{safeLoraWeight.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min="0.1"
                                max="1.5"
                                step="0.1"
                                value={safeLoraWeight}
                                onChange={(e) => {
                                    const next = parseFloat(e.target.value);
                                    if (Number.isFinite(next)) setLoraWeight(next);
                                }}
                                className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                            />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default ImageModelSelector;
