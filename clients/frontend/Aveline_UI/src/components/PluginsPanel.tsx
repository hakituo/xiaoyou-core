import React, { useState, useEffect, useRef, useMemo } from 'react';
import { motion } from 'framer-motion';
import { api } from '../api/apiService';
import { Model } from '../types';
import { useImageModels } from '../hooks/useImageModels';
import ImageModelSelector from './ImageModelSelector';
import { 
  Cpu, 
  Image as ImageIcon, 
  Mic, 
  Upload, 
  Wand2, 
  Play, 
  Settings2,
  Box,
  Layers,
  Sparkles,
  Command,
  Volume2
} from 'lucide-react';
import { InfoCard } from './InfoCard';

interface PluginsPanelProps {
  models: Model[];
  selectedModel: Model | null;
  setSelectedModel: (m: Model | null) => void;
  responseLength: string;
  setResponseLength: (l: string) => void;
  imageModel: ReturnType<typeof useImageModels>;
}

const PluginsPanel = React.memo(function PluginsPanel({ models, selectedModel, setSelectedModel, responseLength, setResponseLength, imageModel }: PluginsPanelProps) {
  const llmModels = useMemo(() => models.filter(m => m.type === 'llm' || m.type === 'dashscope'), [models]);
  const imageModels = useMemo(() => models.filter(m => m.type === 'image' || m.type === 'image_gen'), [models]);
  const loraModels = useMemo(() => models.filter(m => m.type === 'lora'), [models]);
  
  const [prompt, setPrompt] = useState<string>("");
  const [isGeneratingImage, setIsGeneratingImage] = useState<boolean>(false);
  const [imageBase64, setImageBase64] = useState<string>("");
  const [ttsTextLanguage, setTtsTextLanguage] = useState<string>("中英混合");
  const [ttsPromptLanguage, setTtsPromptLanguage] = useState<string>("中英混合");
  const [ttsSpeed, setTtsSpeed] = useState<number>(1.0);
  const [ttsPitch, setTtsPitch] = useState<number>(1.0);
  const [referenceAudio, setReferenceAudio] = useState<string | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [refAudioFiles, setRefAudioFiles] = useState<any[]>([]);

  useEffect(() => {
    const loadRefs = async () => {
      try {
        const res: any = await api.getReferenceAudio();
        if (res?.files) {
          setRefAudioFiles(res.files);
          const saved = sessionStorage.getItem('selected_ref_audio');
          if (saved) {
            setReferenceAudio(saved);
          } else if (res.files.length > 0 && !referenceAudio) {
            const def = res.files.find((f: any) => f.name === 'ref_calm.wav') || res.files[0];
            setReferenceAudio(def.path);
            sessionStorage.setItem('selected_ref_audio', def.path);
          }
        }
      } catch {}
    };
    loadRefs();
  }, []);

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await api.uploadFile('/api/v1/upload', file);
      const p = res?.data?.file_path || '';
      setReferenceAudio(p || null);
    } catch {
    } finally {
      setUploading(false);
    }
  };

  const onGenerate = async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setIsGeneratingImage(true);
    try {
      // Use values from imageModel hook
      const modelPath = imageModel.selectedCheckpoint;
      const loraPath = imageModel.selectedLora;
      const weight = imageModel.loraWeight;
      
      const res = await api.generateImage(trimmed, modelPath || undefined, loraPath || undefined, weight);
      const b64 = res?.data?.image_base64 || '';
      setImageBase64(b64);
    } catch {
      setImageBase64('');
    } finally {
      setIsGeneratingImage(false);
    }
  };

  const onPlayTTS = async () => {
    const t = prompt.trim();
    if (!t) return;
    try {
      const body: any = { text: t, text_language: ttsTextLanguage, prompt_language: ttsPromptLanguage, speed: ttsSpeed, pitch: ttsPitch };
      if (referenceAudio) body.reference_audio = referenceAudio;
      const res = await api.tts(body);
      const audio = res?.data?.audio_base64 || '';
      if (!audio) return;
      const el = new Audio(audio);
      el.loop = false;
      el.play().catch(() => {});
    } catch {}
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-end justify-between border-b border-white/10 pb-6">
          <div>
            <h1 className="text-4xl font-bold tracking-tight text-white mb-2 font-display">
              SYSTEM <span className="text-emerald-500">MODULES</span>
            </h1>
            <div className="flex items-center gap-4 text-xs font-mono text-white/40">
              <span className="flex items-center gap-1"><Cpu size={12}/> CORE: {selectedModel?.name || "AUTO"}</span>
              <span className="flex items-center gap-1"><Layers size={12}/> PLUGINS: {imageModels.length + loraModels.length} LOADED</span>
            </div>
          </div>
          <div className="text-right hidden md:block">
             <div className="text-[10px] uppercase tracking-widest text-white/30 mb-1">Module Status</div>
             <div className="text-emerald-400 font-mono text-sm">ACTIVE // READY</div>
          </div>
        </div>

        <div className="flex flex-col gap-6">
          
          {/* Left Column (Top on mobile): Core Settings & Audio */}
          <div className="space-y-6">
            <InfoCard title="CORE LLM CONFIGURATION" className="h-full">
              <div className="space-y-6">
                
                {/* Model Selection */}
                <div>
                  <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                    <Box size={12} /> INFERENCE ENGINE
                  </div>
                  <select
                    value={selectedModel?.id || ''}
                    onChange={e => {
                      const id = e.target.value;
                      const found = llmModels.find(m => m.id === id) || null;
                      setSelectedModel(found);
                    }}
                    className="w-full bg-black/20 text-white text-sm px-3 py-2 rounded-lg border border-white/10 focus:outline-none focus:border-emerald-500/30 transition-colors font-mono"
                  >
                    <option value="">Select Inference Engine...</option>
                    {llmModels.map(m => (
                      <option key={m.id} value={m.id}>
                        {m.name} {m.quantized ? '(Quantized)' : ''}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Response Length */}
                <div>
                   <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                    <Command size={12} /> RESPONSE PARAMS
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {['short', 'normal', 'long'].map((len) => (
                      <button
                        key={len}
                        onClick={() => setResponseLength(len)}
                        className={`px-3 py-2 rounded-lg border text-xs font-mono transition-colors ${
                          responseLength === len 
                            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' 
                            : 'bg-black/20 border-white/5 text-white/40 hover:bg-white/5'
                        }`}
                      >
                        {len.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>

              </div>
            </InfoCard>

            <InfoCard title="AUDIO SYNTHESIS (TTS)" className="h-full">
               <div className="space-y-6">
                  
                  {/* Language Settings */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                     <div>
                        <div className="text-[10px] text-white/30 font-mono mb-2">TEXT LANG</div>
                        <select 
                          className="w-full bg-black/20 text-white text-xs px-2 py-2 rounded-lg border border-white/10"
                          value={ttsTextLanguage} 
                          onChange={e => setTtsTextLanguage(e.target.value)}
                        >
                          <option value="中英混合">Mix (中英)</option>
                          <option value="中文">Chinese</option>
                          <option value="英文">English</option>
                          <option value="日文">Japanese</option>
                        </select>
                     </div>
                     <div>
                        <div className="text-[10px] text-white/30 font-mono mb-2">PROMPT LANG</div>
                         <select 
                          className="w-full bg-black/20 text-white text-xs px-2 py-2 rounded-lg border border-white/10"
                          value={ttsPromptLanguage} 
                          onChange={e => setTtsPromptLanguage(e.target.value)}
                        >
                          <option value="中英混合">Mix (中英)</option>
                          <option value="中文">Chinese</option>
                          <option value="英文">English</option>
                          <option value="日文">Japanese</option>
                        </select>
                     </div>
                  </div>

                  {/* Reference Audio */}
                  <div>
                    <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                        <Mic size={12} /> VOICE REFERENCE
                    </div>
                    <div className="flex gap-2">
                        <select
                            value={referenceAudio || ''}
                            onChange={e => {
                              setReferenceAudio(e.target.value);
                              sessionStorage.setItem('selected_ref_audio', e.target.value);
                            }}
                            className="flex-1 bg-black/20 text-white text-xs px-2 py-2 rounded-lg border border-white/10 font-mono"
                          >
                            <option value="">Default Voice</option>
                            {refAudioFiles.map((f: any) => (
                              <option key={f.name} value={f.path}>{f.name}</option>
                            ))}
                          </select>
                          <button 
                            onClick={() => fileRef.current?.click()} 
                            className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-white/60 transition-colors"
                          >
                             {uploading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/> : <Upload size={14} />}
                          </button>
                          <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }} onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
                    </div>
                  </div>

                  {/* Sliders */}
                  <div className="space-y-4 pt-2">
                     <div>
                        <div className="flex justify-between text-[10px] text-white/40 mb-1">
                            <span>SPEED</span>
                            <span>{ttsSpeed.toFixed(2)}x</span>
                        </div>
                        <input 
                            type="range" min={0.6} max={1.4} step={0.02} 
                            value={ttsSpeed} 
                            onChange={e => setTtsSpeed(parseFloat(e.target.value))}
                            className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                        />
                     </div>
                     <div>
                        <div className="flex justify-between text-[10px] text-white/40 mb-1">
                            <span>PITCH</span>
                            <span>{ttsPitch.toFixed(2)}</span>
                        </div>
                        <input 
                            type="range" min={0.8} max={1.2} step={0.02} 
                            value={ttsPitch} 
                            onChange={e => setTtsPitch(parseFloat(e.target.value))}
                            className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                        />
                     </div>
                  </div>

               </div>
            </InfoCard>
          </div>

          {/* Right Column: Visual Generation */}
          <div className="space-y-6">
            <InfoCard title="VISUAL CORTEX (IMAGE GEN)" className="h-full bg-purple-900/5 border-purple-500/10">
                <div className="space-y-6">
                    
                    {/* Integrated Model Selector */}
                    <div className="border border-purple-500/10 rounded-xl overflow-hidden">
                       <ImageModelSelector imageModel={imageModel} />
                    </div>

                    {/* Prompt Input */}
                    <div>
                        <div className="text-[10px] text-purple-400/50 font-mono mb-2 flex items-center gap-2">
                            <Wand2 size={12} /> PROMPT MATRIX
                        </div>
                        <textarea
                            value={prompt}
                            onChange={e => setPrompt(e.target.value)}
                            placeholder="Enter visual or auditory description..."
                            className="w-full h-24 bg-black/20 border border-purple-500/10 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-purple-500/30 resize-none font-mono placeholder:text-white/20"
                        />
                    </div>

                    {/* Action Buttons */}
                    <div className="flex flex-col sm:flex-row gap-3">
                        <button 
                            onClick={onGenerate}
                            disabled={isGeneratingImage || !prompt}
                            className="flex-1 py-3 sm:py-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed border border-white/10 rounded-lg text-xs font-mono text-white transition-colors flex items-center justify-center gap-2"
                        >
                            {isGeneratingImage ? (
                                <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"/>
                            ) : (
                                <ImageIcon size={14} />
                            )}
                            GENERATE_IMG
                        </button>
                        <button 
                            onClick={onPlayTTS}
                            disabled={!prompt}
                            className="flex-1 py-3 sm:py-2 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed border border-emerald-500/20 rounded-lg text-xs font-mono text-emerald-400 transition-colors flex items-center justify-center gap-2"
                        >
                            <Volume2 size={14} />
                            SYNTHESIZE_AUDIO
                        </button>
                    </div>

                    {/* Result Preview */}
                    {imageBase64 && (
                        <motion.div 
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="relative rounded-lg overflow-hidden border border-white/10"
                        >
                            <img src={imageBase64} alt="Generated Output" className="w-full object-cover" />
                            <div className="absolute bottom-0 left-0 right-0 p-2 bg-black/60 backdrop-blur-sm text-[10px] text-white/60 font-mono truncate">
                                {prompt}
                            </div>
                        </motion.div>
                    )}

                </div>
            </InfoCard>
          </div>

        </div>
      </div>
    </div>
  );
});

export default PluginsPanel;
