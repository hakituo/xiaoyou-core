import React, { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../api/apiService';
import { Model } from '../types';
import { useImageModels } from '../hooks/useImageModels';
import ImageModelSelector from './ImageModelSelector';
import { useAvelineStore } from '../store/useStore';
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
  Volume2,
  Activity,
  ChevronDown,
  Check,
  Zap,
  Smile,
  BookOpen
} from 'lucide-react';
import { InfoCard } from './InfoCard';
import { EMOTIONS } from '../utils/emotion';
import { CustomSelect } from './ui/CustomSelect';

interface PluginsPanelProps {
  models: Model[];
  selectedModel: Model | null;
  setSelectedModel: (m: Model | null) => void;
  responseLength: string;
  setResponseLength: (l: string) => void;
  imageModel: ReturnType<typeof useImageModels>;
  breathingRate: number;
  setBreathingRate: (r: number) => void;
  setEmotion?: (emotion: any) => void;
  setEmotionMix?: (mix: Record<string, number>) => void;
  emotion?: string;
  currentModel?: string;
  onSwitchModel?: (type: 'cloud' | 'local') => void;
  triggerHaptic?: (style?: any) => void;
  onUpdateSettings?: (settings: { tts?: { provider: string; model: string } }) => void;
}

const PluginsPanel = React.memo(function PluginsPanel({ 
  models, 
  selectedModel, 
  setSelectedModel, 
  responseLength, 
  setResponseLength, 
  imageModel, 
  breathingRate, 
  setBreathingRate,
  setEmotion,
  setEmotionMix,
  emotion,
  currentModel,
  onSwitchModel,
  triggerHaptic,
  onUpdateSettings
}: PluginsPanelProps) {
  const llmModels = useMemo(() => models.filter(m => m.type === 'llm' || m.type === 'dashscope' || m.type === 'openai' || m.type === 'siliconflow' || m.type === 'deepseek' || m.type === 'aveline'), [models]);
  const imageModels = useMemo(() => models.filter(m => m.type === 'image' || m.type === 'image_gen'), [models]);
  const loraModels = useMemo(() => models.filter(m => m.type === 'lora'), [models]);
  
  const [prompt, setPrompt] = useState<string>("");
  const [numImages, setNumImages] = useState<number>(1);
  const [isGeneratingImage, setIsGeneratingImage] = useState<boolean>(false);
  const [imagesBase64, setImagesBase64] = useState<string[]>([]);
  const {
    autoTtsEnabled,
    setAutoTtsEnabled,
    replyDisplayMode,
    setReplyDisplayMode,
    ttsTextLanguage,
    setTtsTextLanguage,
    ttsPromptLanguage,
    setTtsPromptLanguage,
    ttsSpeed,
    setTtsSpeed,
    ttsPitch,
    setTtsPitch,
    ttsProvider,
    setTtsProvider,
    ttsModel,
    setTtsModel,
    referenceAudio,
    setReferenceAudio,
    studyMode,
    setStudyMode,
  } = useAvelineStore();
  const [uploading, setUploading] = useState<boolean>(false);

  const handleToggleStudyMode = async () => {
    const newMode = !studyMode;
    setStudyMode(newMode);
    try {
        await api.updatePreferences({ mode: newMode ? 'study' : 'normal' });
    } catch (e) {
        console.error("Failed to update study mode", e);
        setStudyMode(!newMode); // revert
    }
  };

  const fileRef = useRef<HTMLInputElement>(null);
  const [refAudioFiles, setRefAudioFiles] = useState<any[]>([]);
  const [sensitiveEnabled, setSensitiveEnabled] = useState<boolean>(false);
  const [sensitiveLoading, setSensitiveLoading] = useState<boolean>(false);

  const safeTtsSpeed = Number.isFinite(ttsSpeed) ? ttsSpeed : 1.0;
  const safeTtsPitch = Number.isFinite(ttsPitch) ? ttsPitch : 1.0;
  const ttsProviderOptions = [
    { value: 'local', label: '本地' },
    { value: 'siliconflow', label: 'SiliconFlow' },
    { value: 'openai', label: 'OpenAI' },
    { value: 'custom', label: '自定义' },
  ];
  const ttsLocalModelOptions = [
    { value: 'gpt_sovits', label: 'GPT-SoVITS' },
    { value: 'qwen3', label: 'Qwen3-TTS' },
  ];

  const emitTtsSettings = (nextProvider: string, nextModel: string) => {
    if (!onUpdateSettings) return;
    onUpdateSettings({ tts: { provider: nextProvider, model: nextModel } });
  };

  useEffect(() => {
    const loadRefs = async () => {
      try {
        const res: any = await api.getReferenceAudio();
        const files = Array.isArray(res?.files) ? res.files : [];
        setRefAudioFiles(files);
        try {
          const saved = sessionStorage.getItem('selected_ref_audio');
          if (saved && !referenceAudio) {
            setReferenceAudio(saved);
            return;
          }
        } catch {}
        if (files.length > 0 && !referenceAudio) {
          const def = files.find((f: any) => f?.name === 'ref_calm.wav') || files[0];
          if (def?.path) setReferenceAudio(def.path);
        }
      } catch {}
    };
    
    const loadSensitiveStatus = async () => {
        try {
            const res = await api.getSensitiveStatus();
            if (res && typeof res.enabled === 'boolean') {
                setSensitiveEnabled(res.enabled);
            }
        } catch {}
    };

    loadRefs();
    loadSensitiveStatus();
  }, []);

  const toggleSensitive = async () => {
      setSensitiveLoading(true);
      try {
          const newState = !sensitiveEnabled;
          await api.toggleSensitive(newState);
          setSensitiveEnabled(newState);
      } catch (e) {
          console.error("Failed to toggle Sensitive", e);
      } finally {
          setSensitiveLoading(false);
      }
  };

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
    setImagesBase64([]);
    try {
      // Use values from imageModel hook
      const modelPath = imageModel.selectedCheckpoint;
      const loraPath = imageModel.selectedLora;
      const weight = imageModel.loraWeight;
      
      const res = await api.generateImage(trimmed, modelPath || undefined, loraPath || undefined, weight, numImages);
      
      if (res?.images && Array.isArray(res.images)) {
          const imgs = res.images.map((img: any) => img.image_base64).filter(Boolean);
          setImagesBase64(imgs);
      } else if (res?.image_base64) {
          setImagesBase64([res.image_base64]);
      } else {
          setImagesBase64([]);
      }
    } catch {
      setImagesBase64([]);
    } finally {
      setIsGeneratingImage(false);
    }
  };

  const onPlayTTS = async () => {
    const t = prompt.trim();
    if (!t) return;
    try {
      const body: any = { text: t, text_language: ttsTextLanguage, prompt_language: ttsPromptLanguage, speed: safeTtsSpeed, pitch: safeTtsPitch };
      if (referenceAudio) body.reference_audio = referenceAudio;
      const res = await api.tts(body);
      const audio = (res?.data?.audio_base64 || '').trim();
      if (!audio) return;
      const src = audio.startsWith('data:') || audio.startsWith('blob:') || audio.startsWith('http')
        ? audio
        : `data:audio/wav;base64,${audio}`;
      const el = new Audio(src);
      el.loop = false;
      el.play().catch(() => {});
    } catch {}
  };

  return (
    <div className="flex-1 p-4 sm:p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-end justify-between border-b border-white/10 pb-6">
          <div>
            <h1 className="text-2xl sm:text-4xl font-bold tracking-tight text-white mb-2 font-display">
              SYSTEM <span className="text-emerald-500">MODULES</span>
            </h1>
            <div className="flex items-center gap-4 text-xs font-mono text-white/40">
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
                
                {/* Model Selector */}
                <div>
                   <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                    <Cpu size={12} /> ACTIVE MODEL SYSTEM
                  </div>
                  
                  {onSwitchModel && (
                      <div className="grid grid-cols-2 gap-3 mb-3">
                        <button
                            type="button"
                            onClick={(e) => {
                              // Prevent double-tap issues on some mobile browsers
                              e.preventDefault();
                              e.stopPropagation();
                              if (currentModel !== 'cloud') {
                                  onSwitchModel('cloud');
                                  triggerHaptic?.();
                              }
                            }}
                            className={`p-3 rounded-xl border text-sm font-medium transition-all text-left relative overflow-hidden active:scale-95 touch-manipulation ${
                                currentModel === 'cloud'
                                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.1)]'
                                : 'bg-black/20 border-white/10 text-white/60'
                            }`}
                        >
                            <div className="text-[10px] opacity-60 mb-1 font-mono uppercase">CLOUD API</div>
                            <div className="font-bold">DeepSeek</div>
                            {currentModel === 'cloud' && (
                                <div className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            )}
                        </button>
                        <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              if (currentModel !== 'local') {
                                  onSwitchModel('local');
                                  triggerHaptic?.();
                              }
                            }}
                            className={`p-3 rounded-xl border text-sm font-medium transition-all text-left relative overflow-hidden active:scale-95 touch-manipulation ${
                                currentModel === 'local'
                                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.1)]'
                                : 'bg-black/20 border-white/10 text-white/60'
                            }`}
                        >
                            <div className="text-[10px] opacity-60 mb-1 font-mono uppercase">LOCAL GPU</div>
                            <div className="font-bold">Local Model</div>
                            {currentModel === 'local' && (
                                <div className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            )}
                        </button>
                      </div>
                  )}

                  <div className="relative z-20">
                    <CustomSelect
                      value={selectedModel?.id || ''}
                      onChange={(val) => {
                        const m = models.find(mod => mod.id === val);
                        setSelectedModel(m || null);
                        if (m) {
                           const provider = m.type === 'llm' ? 'local' : (m.type || 'local');
                           api.switchModel(m.id, provider).catch(err => {
                               console.error("Failed to switch model:", err);
                           });
                        }
                      }}
                      options={llmModels.filter(m => {
                          if (!onSwitchModel || !currentModel) return true;
                          if (m.category) {
                              return m.category === currentModel;
                          }
                          if (m.path && typeof m.path === 'string') {
                              const isCloud = m.path.startsWith('cloud:');
                              return currentModel === 'cloud' ? isCloud : !isCloud;
                          }
                          if (currentModel === 'cloud') return m.type !== 'llm';
                          if (currentModel === 'local') return m.type === 'llm';
                          return true;
                      }).map(m => ({
                        value: m.id,
                        label: m.name || m.id,
                        sub: (m.provider || m.type || '').toUpperCase()
                      }))}
                      placeholder={onSwitchModel 
                        ? (currentModel === 'cloud' ? 'Select Cloud Model...' : 'Select Local Model...')
                        : 'Select a model...'
                      }
                      triggerHaptic={triggerHaptic}
                    />
                  </div>

                  {selectedModel && !onSwitchModel && (
                    <div className="mt-1.5 flex items-center gap-2">

                      <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                      <span className="text-[9px] text-emerald-500/60 font-mono uppercase tracking-wider">
                        {selectedModel.provider || 'Local'} // {selectedModel.type?.toUpperCase()}
                      </span>
                    </div>
                  )}
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

                {/* Breathing Rate */}
                <div>
                   <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                    <Sparkles size={12} /> ATMOSPHERE RATE
                  </div>
                  <div className="flex items-center gap-3">
                     <input 
                        type="range" min={0.1} max={3.0} step={0.1} 
                        value={breathingRate} 
                        onChange={e => setBreathingRate(parseFloat(e.target.value))}
                        className="flex-1 h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                    />
                    <span className="text-xs font-mono text-emerald-400 w-8 text-right">{breathingRate.toFixed(1)}x</span>
                  </div>
                </div>

                {/* Study Mode Switch */}
                <div className="pt-2 border-t border-white/5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                       <div className={`p-1.5 rounded-lg ${studyMode ? 'bg-cyan-500/20 text-cyan-400' : 'bg-white/5 text-white/40'}`}>
                         <BookOpen size={14} />
                       </div>
                       <div>
                          <div className="text-[10px] text-white/30 font-mono uppercase tracking-wider mb-0.5">Study Mode</div>
                          <div className="text-xs text-white/70">Structured Learning</div>
                       </div>
                    </div>
                    <button
                      onClick={handleToggleStudyMode}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
                        studyMode ? 'bg-cyan-500/40' : 'bg-white/10'
                      }`}
                    >
                      <span
                        className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                          studyMode ? 'translate-x-5' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>

                {/* Sensitive Switch */}
                <div className="pt-2 border-t border-white/5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${sensitiveEnabled ? 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]' : 'bg-white/20'}`} />
                      <div className="text-[10px] text-white/30 font-mono uppercase tracking-wider">Local Mode Override</div>
                    </div>
                    <button
                      onClick={toggleSensitive}
                      disabled={sensitiveLoading}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
                        sensitiveEnabled ? 'bg-rose-500/40' : 'bg-white/10'
                      }`}
                    >
                      <span
                        className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                          sensitiveEnabled ? 'translate-x-5' : 'translate-x-1'
                        }`}
                      />
                      {sensitiveLoading && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/20 rounded-full">
                           <div className="w-2 h-2 border border-white/30 border-t-white rounded-full animate-spin" />
                        </div>
                      )}
                    </button>
                  </div>
                  <div className="mt-1 text-[10px] font-mono text-white/40 tracking-tight">
                    {sensitiveEnabled ? "LOCAL MODE ACTIVE // FULL CONTENT ACCESS" : "CLOUD MODE ACTIVE // STANDARD FILTERING"}
                  </div>
                </div>

                {/* Emotion Debug */}
                {setEmotion && (
                  <div>
                    <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                      <Activity size={12} /> EMOTION DEBUG
                    </div>
                    <CustomSelect
                      value={emotion || 'neutral'}
                      onChange={(val) => {
                        setEmotion(val);
                        if (setEmotionMix) {
                          setEmotionMix({ [val]: 1.0 });
                        }
                      }}
                      options={Object.keys(EMOTIONS).map(emo => ({
                        value: emo,
                        label: emo.toUpperCase()
                      }))}
                      placeholder="Select Emotion"
                      className="w-full"
                    />
                  </div>
                )}

              </div>
            </InfoCard>

            <InfoCard title="AUDIO SYNTHESIS (TTS)" className="h-full">
               <div className="space-y-6">

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <div className="text-[10px] text-white/30 font-mono mb-2">REPLY MODE</div>
                      <CustomSelect
                        value={replyDisplayMode}
                        onChange={(val) => setReplyDisplayMode(val === 'tts_only' ? 'tts_only' : 'text_and_tts')}
                        options={[
                          { value: 'text_and_tts', label: '文字+语音' },
                          { value: 'tts_only', label: '仅语音' }
                        ]}
                        triggerHaptic={triggerHaptic}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <div className="text-[10px] text-white/30 font-mono mb-2">AUTO PLAY</div>
                      <div className="flex items-center justify-between bg-black/20 border border-white/10 rounded-lg px-3 py-2">
                        <span className="text-xs font-mono text-white/60">自动播放</span>
                        <button
                          onClick={() => setAutoTtsEnabled(!autoTtsEnabled)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
                            autoTtsEnabled ? 'bg-emerald-500/40' : 'bg-white/10'
                          }`}
                        >
                          <span
                            className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                              autoTtsEnabled ? 'translate-x-5' : 'translate-x-1'
                            }`}
                          />
                        </button>
                      </div>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <div className="text-[10px] text-white/30 font-mono mb-2">TTS PROVIDER</div>
                      <CustomSelect
                        value={ttsProvider}
                        onChange={(val) => {
                          const nextProvider = val || 'local';
                          let nextModel = ttsModel;
                          if (nextProvider === 'local' && !['gpt_sovits', 'qwen3'].includes(ttsModel)) {
                            nextModel = 'gpt_sovits';
                          }
                          setTtsProvider(nextProvider);
                          if (nextModel !== ttsModel) setTtsModel(nextModel);
                          emitTtsSettings(nextProvider, nextModel);
                        }}
                        options={ttsProviderOptions}
                        triggerHaptic={triggerHaptic}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <div className="text-[10px] text-white/30 font-mono mb-2">TTS MODEL</div>
                      {ttsProvider === 'local' ? (
                        <CustomSelect
                          value={ttsModel}
                          onChange={(val) => {
                            const nextModel = val || 'gpt_sovits';
                            setTtsModel(nextModel);
                            emitTtsSettings(ttsProvider, nextModel);
                          }}
                          options={ttsLocalModelOptions}
                          triggerHaptic={triggerHaptic}
                          className="w-full"
                        />
                      ) : (
                        <input
                          value={ttsModel}
                          onChange={(e) => {
                            const nextModel = e.target.value;
                            setTtsModel(nextModel);
                            emitTtsSettings(ttsProvider, nextModel);
                          }}
                          placeholder="Model Name"
                          className="w-full bg-black/20 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-emerald-500/30 font-mono placeholder:text-white/30"
                        />
                      )}
                    </div>
                  </div>

                  {/* Language Settings */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                     <div>
                        <div className="text-[10px] text-white/30 font-mono mb-2">TEXT LANG</div>
                        <CustomSelect
                          value={ttsTextLanguage}
                          onChange={(val) => setTtsTextLanguage(val)}
                          options={[
                            { value: '中英混合', label: 'Mix (中英)' },
                            { value: '中文', label: 'Chinese' },
                            { value: '英文', label: 'English' },
                            { value: '日文', label: 'Japanese' }
                          ]}
                          triggerHaptic={triggerHaptic}
                          className="w-full"
                        />
                     </div>
                     <div>
                        <div className="text-[10px] text-white/30 font-mono mb-2">PROMPT LANG</div>
                         <CustomSelect 
                          value={ttsPromptLanguage} 
                          onChange={(val) => setTtsPromptLanguage(val)}
                          options={[
                            { value: '中英混合', label: 'Mix (中英)' },
                            { value: '中文', label: 'Chinese' },
                            { value: '英文', label: 'English' },
                            { value: '日文', label: 'Japanese' }
                          ]}
                          triggerHaptic={triggerHaptic}
                          className="w-full"
                        />
                     </div>
                  </div>

                  {/* Reference Audio */}
                  <div>
                    <div className="text-[10px] text-white/30 font-mono mb-2 flex items-center gap-2">
                        <Mic size={12} /> VOICE REFERENCE
                    </div>
                    <div className="flex gap-2">
                        <div className="flex-1">
                          <CustomSelect
                              value={referenceAudio || ''}
                              onChange={(val) => setReferenceAudio(val)}
                              options={[
                                { value: '', label: 'Default Voice' },
                                ...refAudioFiles.map((f: any) => ({ value: f.path, label: f.name }))
                              ]}
                              triggerHaptic={triggerHaptic}
                              placeholder="Select Voice..."
                              className="w-full"
                            />
                        </div>
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
                            <span>{safeTtsSpeed.toFixed(2)}x</span>
                        </div>
                        <input 
                            type="range" min={0.6} max={1.4} step={0.02} 
                            value={safeTtsSpeed} 
                            onChange={e => {
                              const next = parseFloat(e.target.value);
                              if (Number.isFinite(next)) setTtsSpeed(next);
                            }}
                            className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                        />
                     </div>
                     <div>
                        <div className="flex justify-between text-[10px] text-white/40 mb-1">
                            <span>PITCH</span>
                            <span>{safeTtsPitch.toFixed(2)}</span>
                        </div>
                        <input 
                            type="range" min={0.8} max={1.2} step={0.02} 
                            value={safeTtsPitch} 
                            onChange={e => {
                              const next = parseFloat(e.target.value);
                              if (Number.isFinite(next)) setTtsPitch(next);
                            }}
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
                       <ImageModelSelector imageModel={imageModel} triggerHaptic={triggerHaptic} />
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

                    {/* Image Quantity Slider */}
                    <div>
                         <div className="flex justify-between items-center mb-2">
                             <div className="text-[10px] text-purple-400/50 font-mono flex items-center gap-2">
                                 <Layers size={12} /> BATCH SIZE
                             </div>
                             <div className="text-[10px] text-purple-400 font-mono">
                                 {numImages}
                             </div>
                         </div>
                         <input 
                             type="range" min={1} max={4} step={1} 
                             value={numImages} 
                             onChange={e => setNumImages(parseInt(e.target.value))}
                             className="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-purple-500"
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
                    {imagesBase64.length > 0 && (
                        <div className={`grid gap-2 ${imagesBase64.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`}>
                            {imagesBase64.map((b64, idx) => (
                                <motion.div 
                                    key={idx}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: idx * 0.1 }}
                                    className="relative rounded-lg overflow-hidden border border-white/10"
                                >
                                    <img src={b64} alt={`Generated Output ${idx + 1}`} className="w-full object-cover" />
                                    <div className="absolute bottom-0 left-0 right-0 p-2 bg-black/60 backdrop-blur-sm text-[10px] text-white/60 font-mono truncate">
                                        {prompt}
                                    </div>
                                </motion.div>
                            ))}
                        </div>
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
