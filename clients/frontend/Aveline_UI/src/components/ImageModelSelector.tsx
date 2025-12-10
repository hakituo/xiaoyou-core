import React from 'react';
import { Image, Layers, Box } from 'lucide-react';
import { useImageModels } from '../hooks/useImageModels';

interface ImageModelSelectorProps {
    imageModel: ReturnType<typeof useImageModels>;
}

const ImageModelSelector: React.FC<ImageModelSelectorProps> = ({ imageModel }) => {
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
                        <select
                            value={selectedCheckpoint}
                            onChange={(e) => setSelectedCheckpoint(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white/80 focus:outline-none focus:border-emerald-500/50"
                        >
                            {models.sd15.checkpoints.map((m) => (
                                <option key={m.path} value={m.path} className="bg-gray-900">
                                    {m.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* LoRA */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Layers size={10} /> LoRA
                        </label>
                        <select
                            value={selectedLora}
                            onChange={(e) => setSelectedLora(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white/80 focus:outline-none focus:border-emerald-500/50"
                        >
                            <option value="" className="bg-gray-900">None</option>
                            {models.sd15.loras.map((m) => (
                                <option key={m.path} value={m.path} className="bg-gray-900">
                                    {m.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* LoRA Weight */}
                    {selectedLora && (
                        <div className="space-y-1">
                            <div className="flex justify-between text-[10px] text-white/40">
                                <span>Weight</span>
                                <span>{loraWeight.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min="0.1"
                                max="1.5"
                                step="0.1"
                                value={loraWeight}
                                onChange={(e) => setLoraWeight(parseFloat(e.target.value))}
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
                        <select
                            value={selectedCheckpoint}
                            onChange={(e) => setSelectedCheckpoint(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white/80 focus:outline-none focus:border-emerald-500/50"
                        >
                            {models.sdxl.models.map((m) => (
                                <option key={m.path} value={m.path} className="bg-gray-900">
                                    {m.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* SDXL LoRA */}
                    <div className="space-y-1">
                        <label className="text-[10px] uppercase tracking-wider text-white/40 flex items-center gap-1">
                            <Layers size={10} /> SDXL LoRA
                        </label>
                        <select
                            value={selectedLora}
                            onChange={(e) => setSelectedLora(e.target.value)}
                            className="w-full bg-black/20 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white/80 focus:outline-none focus:border-emerald-500/50"
                        >
                            <option value="" className="bg-gray-900">None</option>
                            {models.sdxl.models.map((m) => (
                                <option key={m.path} value={m.path} className="bg-gray-900">
                                    {m.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* LoRA Weight */}
                    {selectedLora && (
                        <div className="space-y-1">
                            <div className="flex justify-between text-[10px] text-white/40">
                                <span>Weight</span>
                                <span>{loraWeight.toFixed(1)}</span>
                            </div>
                            <input
                                type="range"
                                min="0.1"
                                max="1.5"
                                step="0.1"
                                value={loraWeight}
                                onChange={(e) => setLoraWeight(parseFloat(e.target.value))}
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
