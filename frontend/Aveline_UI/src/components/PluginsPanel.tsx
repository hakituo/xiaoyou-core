import React, { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '../api/apiService';
import { Model } from '../types';

interface PluginsPanelProps {
  models: Model[];
  selectedModel: Model | null;
  setSelectedModel: (m: Model | null) => void;
  responseLength: string;
  setResponseLength: (l: string) => void;
}

const PluginsPanel = React.memo(function PluginsPanel({ models, selectedModel, setSelectedModel, responseLength, setResponseLength }: PluginsPanelProps) {
  const llmModels = useMemo(() => models.filter(m => m.type === 'llm' || m.type === 'dashscope'), [models]);
  const imageModels = useMemo(() => models.filter(m => m.type === 'image' || m.type === 'image_gen'), [models]);
  const loraModels = useMemo(() => models.filter(m => m.type === 'lora'), [models]);
  const [selectedImageModel, setSelectedImageModel] = useState<Model | null>(null);
  const [selectedLora, setSelectedLora] = useState<string>("");
  const [loraWeight, setLoraWeight] = useState<number>(0.7);
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

  useEffect(() => {
    if (!selectedImageModel && imageModels.length > 0) {
      setSelectedImageModel(imageModels[0]);
    }
  }, [imageModels, selectedImageModel]); // Simplified dependency

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
      const res = await api.generateImage(trimmed, selectedImageModel?.path || undefined, selectedLora || undefined, loraWeight);
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
    <div className="flex-1 p-8">
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-white/60">LLM</span>
          <select
            value={selectedModel?.id || ''}
            onChange={e => {
              const id = e.target.value;
              const found = llmModels.find(m => m.id === id) || null;
              setSelectedModel(found);
            }}
            className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10"
          >
            <option value="">选择LLM模型</option>
            {llmModels.map(m => (
              <option key={m.id} value={m.id}>
                {m.name} {m.quantized ? '(Quantized)' : ''}
              </option>
            ))}
          </select>
          <span className="text-[10px] text-white/60">当前: {selectedModel?.name || '未选择'}</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-white/60">回复长度</span>
          <select
            value={responseLength}
            onChange={e => setResponseLength(e.target.value)}
            className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10"
          >
            <option value="short">简短 (50 token)</option>
            <option value="normal">正常 (150 token)</option>
            <option value="long">详细 (400 token)</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-white/60">图片模型</span>
          <select
            value={selectedImageModel?.id || ''}
            onChange={e => {
              const id = e.target.value;
              const found = imageModels.find(m => m.id === id) || null;
              setSelectedImageModel(found);
            }}
            className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10"
          >
            <option value="">选择图片生成模型</option>
            {imageModels.map(m => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <span className="text-[10px] text-white/60">当前: {selectedImageModel?.name || '未选择'}</span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedLora}
            onChange={e => setSelectedLora(e.target.value)}
            className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10"
          >
            <option value="">选择LoRA</option>
            {loraModels.map(m => (
              <option key={m.id} value={m.path}>{m.name}</option>
            ))}
          </select>
          <div className="flex items-center gap-1">
            <input type="range" min={0} max={1} step={0.05} value={loraWeight} onChange={e => setLoraWeight(parseFloat(e.target.value))} />
            <span className="text-[10px] text-white/60">{loraWeight.toFixed(2)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            placeholder="输入提示词生成图像或TTS"
            className="flex-1 bg-[#18181b] border border-white/10 rounded-md px-3 py-2 text-white"
          />
          <button onClick={onGenerate} className="px-4 py-2 rounded-md bg-white text-black text-sm hover:bg-gray-200">{isGeneratingImage ? '生成中...' : '生成图像'}</button>
          <button onClick={onPlayTTS} className="px-4 py-2 rounded-md bg-white/10 text-white text-sm hover:bg-white/20">播放TTS</button>
        </div>
        {imageBase64 && (
          <div className="mt-2"><img src={imageBase64} alt="generated" className="rounded-lg max-w-full" /></div>
        )}
        <div className="mt-4 p-3 bg-[#18181b] border border-white/10 rounded-md space-y-2">
          <div className="text-white/70 text-xs">TTS 配置</div>
          <div className="grid grid-cols-3 gap-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-white/60">文本语言</span>
              <select className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10" value={ttsTextLanguage} onChange={e => setTtsTextLanguage(e.target.value)}>
                <option value="中英混合">中英混合</option>
                <option value="中文">中文</option>
                <option value="英文">英文</option>
                <option value="日文">日文</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-white/60">提示语言</span>
              <select className="bg-black/30 text-white/80 text-xs px-2 py-1 rounded-md border border-white/10" value={ttsPromptLanguage} onChange={e => setTtsPromptLanguage(e.target.value)}>
                <option value="中英混合">中英混合</option>
                <option value="中文">中文</option>
                <option value="英文">英文</option>
                <option value="日文">日文</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-white/60">参考音频</span>
              <span className="text-[10px] text-white/40">{referenceAudio ? '已选择' : '未选择'}</span>
              <button onClick={() => fileRef.current?.click()} className="px-2 py-1 rounded-md bg-white text-black text-[10px] hover:bg-gray-200">{uploading ? '上传中...' : '选择文件'}</button>
              <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }} onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
            </div>
            <div className="flex items-center gap-2 col-span-3">
              <span className="text-[10px] text-white/60">速度</span>
              <input type="range" min={0.6} max={1.4} step={0.02} value={ttsSpeed} onChange={e => setTtsSpeed(parseFloat(e.target.value))} />
              <span className="text-[10px] text-white/60">{ttsSpeed.toFixed(2)}</span>
              <span className="text-[10px] text-white/60 ml-3">音高</span>
              <input type="range" min={0.8} max={1.2} step={0.02} value={ttsPitch} onChange={e => setTtsPitch(parseFloat(e.target.value))} />
              <span className="text-[10px] text-white/60">{ttsPitch.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

export default PluginsPanel;
