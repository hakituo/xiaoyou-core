import React, { useMemo, useState } from 'react';
import { Settings, Volume2, Monitor, Eye, Cloud, Key, Server, Save, Mic, MessageSquare, Image as ImageIcon } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

type CloudService = 'stt' | 'tts' | 'image';

type CloudProvider = 'local' | 'siliconflow' | 'openai' | 'custom';

type CloudServiceSettings = {
  provider: CloudProvider;
  api_key: string;
  base_url: string;
  model: string;
};

type CloudSettings = Record<CloudService, CloudServiceSettings>;

interface SettingsModalProps {
  onClose: () => void;
  onUpdateSettings?: (settings: any) => void;
  initialSettings?: any;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ onClose, onUpdateSettings, initialSettings }) => {
  const initialGeneral = useMemo(() => initialSettings?.general ?? {}, [initialSettings]);
  const initialCloud = useMemo<CloudSettings | null>(() => initialSettings?.cloud ?? null, [initialSettings]);
  const [activeTab, setActiveTab] = useState<'general' | 'cloud'>('general');
  const [cloudService, setCloudService] = useState<CloudService>('stt');
  
  // General State
  const [volume, setVolume] = useState(initialGeneral.volume ?? 80);
  const [scale, setScale] = useState(initialGeneral.scale ?? 100);
  const [opacity, setOpacity] = useState(initialGeneral.opacity ?? 100);

  // Cloud State
  const [cloudSettings, setCloudSettings] = useState<CloudSettings>(() => (
    initialCloud ?? {
      stt: { provider: 'local', api_key: '', base_url: '', model: '' },
      tts: { provider: 'local', api_key: '', base_url: '', model: '' },
      image: { provider: 'local', api_key: '', base_url: '', model: '' }
    }
  ));

  const handleCloudChange = (service: CloudService, field: keyof CloudServiceSettings, value: string) => {
    setCloudSettings(prev => ({
      ...prev,
      [service]: {
        ...prev[service],
        [field]: value
      }
    }));
  };

  const handleSave = () => {
    if (onUpdateSettings) {
      onUpdateSettings({
        general: { volume, scale, opacity },
        cloud: cloudSettings
      });
    }
    onClose();
  };

  const providers = {
    stt: ['local', 'siliconflow', 'openai', 'custom'],
    tts: ['local', 'siliconflow', 'openai', 'custom'],
    image: ['local', 'siliconflow', 'openai', 'custom']
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center z-[70] p-4 pointer-events-auto">
      <div 
        className="absolute inset-0 bg-black/40 backdrop-blur-sm" 
        onClick={onClose}
      />
      <motion.div 
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="bg-slate-900/95 backdrop-blur-xl w-full max-w-md rounded-2xl shadow-2xl border border-slate-700/50 overflow-hidden flex flex-col max-h-[80vh]"
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-700/50 flex justify-between items-center bg-slate-800/50">
          <div className="flex items-center gap-2 text-slate-100 font-bold">
            <Settings size={20} className="text-blue-400" />
            <span>Settings</span>
          </div>
          
          {/* Tabs */}
          <div className="flex bg-slate-800 rounded-lg p-1">
            <button 
              onClick={() => setActiveTab('general')}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${activeTab === 'general' ? 'bg-blue-500 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
            >
              General
            </button>
            <button 
              onClick={() => setActiveTab('cloud')}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${activeTab === 'cloud' ? 'bg-blue-500 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
            >
              Cloud API
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto flex-1 custom-scrollbar">
          <AnimatePresence mode="wait">
            {activeTab === 'general' ? (
              <motion.div 
                key="general"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                className="space-y-6"
              >
                {/* Volume */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs text-slate-400 font-medium">
                    <div className="flex items-center gap-2">
                      <Volume2 size={14} /> Voice Volume
                    </div>
                    <span>{volume}%</span>
                  </div>
                  <input 
                    type="range" 
                    min="0" max="100" 
                    value={volume}
                    onChange={(e) => setVolume(Number(e.target.value))}
                    className="w-full h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>

                {/* Scale */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs text-slate-400 font-medium">
                    <div className="flex items-center gap-2">
                      <Monitor size={14} /> Pet Scale
                    </div>
                    <span>{scale}%</span>
                  </div>
                  <input 
                    type="range" 
                    min="50" max="150" 
                    value={scale}
                    onChange={(e) => setScale(Number(e.target.value))}
                    className="w-full h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>

                {/* Opacity */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs text-slate-400 font-medium">
                    <div className="flex items-center gap-2">
                      <Eye size={14} /> Opacity
                    </div>
                    <span>{opacity}%</span>
                  </div>
                  <input 
                    type="range" 
                    min="20" max="100" 
                    value={opacity}
                    onChange={(e) => setOpacity(Number(e.target.value))}
                    className="w-full h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>
              </motion.div>
            ) : (
              <motion.div 
                key="cloud"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-4"
              >
                {/* Sub Tabs */}
                <div className="flex gap-2 mb-4 overflow-x-auto pb-2">
                   <button 
                    onClick={() => setCloudService('stt')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border transition-all ${cloudService === 'stt' ? 'bg-slate-700 border-blue-500/50 text-blue-400' : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:bg-slate-800'}`}
                   >
                     <Mic size={14} /> STT (Hearing)
                   </button>
                   <button 
                    onClick={() => setCloudService('tts')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border transition-all ${cloudService === 'tts' ? 'bg-slate-700 border-blue-500/50 text-blue-400' : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:bg-slate-800'}`}
                   >
                     <Volume2 size={14} /> TTS (Speaking)
                   </button>
                   <button 
                    onClick={() => setCloudService('image')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border transition-all ${cloudService === 'image' ? 'bg-slate-700 border-blue-500/50 text-blue-400' : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:bg-slate-800'}`}
                   >
                     <ImageIcon size={14} /> Image (Vision)
                   </button>
                </div>

                <div className="space-y-4 bg-slate-800/30 p-4 rounded-xl border border-slate-700/50">
                    {/* Provider */}
                    <div className="space-y-1">
                        <label className="text-xs text-slate-400 font-medium flex items-center gap-1">
                            <Cloud size={12} /> Provider
                        </label>
                        <select 
                            value={cloudSettings[cloudService].provider}
                            onChange={(e) => handleCloudChange(cloudService, 'provider', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
                        >
                            {providers[cloudService].map(p => (
                                <option key={p} value={p}>{p.toUpperCase()}</option>
                            ))}
                        </select>
                    </div>

                    {/* API Key */}
                    <div className="space-y-1">
                        <label className="text-xs text-slate-400 font-medium flex items-center gap-1">
                            <Key size={12} /> API Key
                        </label>
                        <input 
                            type="password"
                            placeholder="sk-..."
                            value={cloudSettings[cloudService].api_key}
                            onChange={(e) => handleCloudChange(cloudService, 'api_key', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 placeholder-slate-600"
                        />
                    </div>
                    
                    {/* Model */}
                    <div className="space-y-1">
                        <label className="text-xs text-slate-400 font-medium flex items-center gap-1">
                            <Server size={12} /> Model Name
                        </label>
                        <input 
                            type="text"
                            placeholder={cloudService === 'stt' ? 'whisper-1' : cloudService === 'tts' ? 'tts-1' : 'dall-e-3'}
                            value={cloudSettings[cloudService].model}
                            onChange={(e) => handleCloudChange(cloudService, 'model', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 placeholder-slate-600"
                        />
                    </div>

                    {/* Base URL */}
                     <div className="space-y-1">
                        <label className="text-xs text-slate-400 font-medium flex items-center gap-1">
                            <Server size={12} /> Base URL (Optional)
                        </label>
                        <input 
                            type="text"
                            placeholder="https://api.openai.com/v1"
                            value={cloudSettings[cloudService].base_url}
                            onChange={(e) => handleCloudChange(cloudService, 'base_url', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 placeholder-slate-600"
                        />
                    </div>
                </div>
                
                <div className="text-[10px] text-slate-500 px-2">
                    * Settings are applied immediately to the current session backend.
                </div>

              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700/50 bg-slate-800/50 flex justify-end gap-2">
            <button 
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
            >
                Cancel
            </button>
            <button 
                onClick={handleSave}
                className="px-4 py-2 rounded-lg text-xs font-medium bg-blue-500 hover:bg-blue-600 text-white shadow-lg shadow-blue-500/20 flex items-center gap-2 transition-all"
            >
                <Save size={14} />
                Save Changes
            </button>
        </div>

      </motion.div>
    </div>
  );
};

export default SettingsModal;
