import React, { useState, useEffect, useRef } from 'react';
import { Settings } from 'lucide-react';
import { api } from './api/apiService';
import { Message } from './types';
import { SIDEBAR_ITEMS } from './utils/constants';
import { resolveEmotionFromLabel, stripEmotionMarkers, ttsParamsForEmotion } from './utils/emotion';
import { useStatus } from './hooks/useStatus';
import { useModels } from './hooks/useModels';
import { useWebSocket } from './hooks/useWebSocket';

import SidebarButton from './components/SidebarButton';
import DeviceWidget from './components/DeviceWidget';
import ErrorBoundary from './components/ErrorBoundary';
import PluginsPanel from './components/PluginsPanel';
import MemoryPanel from './components/MemoryPanel';
import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';

const STORAGE_KEY = 'aveline_chat_history_v2';

export default function Aveline() {
  // Hooks
  const { stats, clock, emotion, setEmotion, currentColors, setEmotionLockUntil } = useStatus();
  const { models, selectedModel, setSelectedModel } = useModels();

  // WebSocket for Spontaneous Reactions
  useWebSocket({
    onMessage: (msg) => {
      if (msg.type === 'spontaneous_reaction' && msg.content) {
        const reactionMsg: Message = {
          id: Date.now(),
          isUser: false,
          text: msg.content,
          messageType: 'reaction'
        };
        setMessages(prev => [...prev, reactionMsg]);
      }
    }
  });

  // UI State
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('Chat');
  
  // Chat State
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : [{ id: 1, isUser: false, text: "系统就绪。Aveline 核心已加载。" }];
    } catch {
      return [{ id: 1, isUser: false, text: "系统就绪。Aveline 核心已加载。" }];
    }
  });
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [responseLength, setResponseLength] = useState<string>('normal');
  
  // Persona State
  const [persona, setPersona] = useState<any>(null);
  
  // Audio State
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>("");
  const [playingMsgId, setPlayingMsgId] = useState<number | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Effects
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  }, [messages]);

  useEffect(() => {
    api.listVoices({ silent: true }).then((res: any) => {
       const list = res?.data?.voices || [];
       setVoices(list);
       if (list.length > 0) setSelectedVoiceId(String(list[0].id));
    }).catch(() => {});

    // Fetch Persona
    api.getPersona({ silent: true }).then((res: any) => {
      if (res?.data) {
        setPersona(res.data);
      }
    }).catch(() => {});

    // Proactive Greeting (Once per session)
    const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
    if (!hasGreeted) {
      api.getGreeting({ silent: true }).then((res: any) => {
        if (res?.status === 'success' && res.greeting) {
           const greetingMsg: Message = { 
             id: Date.now(), 
             isUser: false, 
             text: res.greeting 
           };
           setMessages(prev => [...prev, greetingMsg]);
           sessionStorage.setItem('aveline_has_greeted', 'true');
        }
      }).catch(() => {});
    }
  }, []);

  // Handlers
  const handleSend = async () => {
    if (!input.trim() || isTyping) return;
    const text = input.trim();
    const userMsg: Message = { id: Date.now(), isUser: true, text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    try {
      const maxTokensMap: Record<string, number> = {
        short: 50,
        normal: 150,
        long: 400
      };
      const maxTokens = maxTokensMap[responseLength] || 150;

      const res = await api.sendMessage(text, { 
        modelName: selectedModel?.id,
        maxTokens: maxTokens
      });
      const fullReply = res?.reply || "Connection Error";
      
      // Parse emotion
      let emoLabel = null;
      
      // 1. Try backend detected emotion
      if (res?.emotion && res.emotion !== 'neutral') {
          emoLabel = res.emotion;
      } 
      // 2. Fallback to regex match
      else {
          const emoMatch = fullReply.match(/\[EMO:\s*\{?([a-zA-Z0-9_]+)\}?\]/) || fullReply.match(/\{([^\}]+)\}/);
          emoLabel = emoMatch ? emoMatch[1] : null;
      }

      const cleanText = stripEmotionMarkers(fullReply);
      
      if (emoLabel) {
        const parsed = resolveEmotionFromLabel(emoLabel);
        setEmotion(parsed);
        setEmotionLockUntil(Date.now() + 45000); // Lock for 45s
      }

      const botMsg: Message = { id: Date.now() + 1, isUser: false, text: cleanText };
      setMessages(prev => [...prev, botMsg]);

      // Auto TTS disabled by user request
      // if (cleanText) {
      //    playTTS(cleanText, botMsg.id, emotion); // Use current emotion or parsed one
      // }

    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: "Error connecting to AI Core." }]);
    } finally {
      setIsTyping(false);
    }
  };

  const playTTS = async (text: string, msgId: number, currentEmotion: string) => {
     try {
       if (audioRef.current) {
         audioRef.current.pause();
         audioRef.current = null;
       }
       
       setPlayingMsgId(msgId);
       
       // Check if audio is already cached
       const msg = messages.find(m => m.id === msgId);
       if (msg?.audioBase64) {
         const audio = new Audio(msg.audioBase64);
         audioRef.current = audio;
         audio.onended = () => {
           setPlayingMsgId(null);
           audioRef.current = null;
         };
         audio.play().catch(() => {
            setPlayingMsgId(null);
         });
         return;
       }

       setLoadingAudio(true);

      const params = ttsParamsForEmotion(currentEmotion as any);
      
      // Create a timeout promise to prevent infinite spinning
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error("TTS Timeout")), 30000)
      );

      const res = await Promise.race([
        api.tts({
          text,
          text_language: "中英混合",
          prompt_language: "中英混合",
          speed: params.speed,
          pitch: params.pitch,
          emotion: params.emotion,
          gpt_sovits_weights: selectedVoiceId
        }),
        timeoutPromise
      ]) as any;

      const b64 = res?.data?.audio_base64;
       if (b64) {
         // Cache the audio
         setMessages(prev => prev.map(m => 
           m.id === msgId ? { ...m, audioBase64: b64 } : m
         ));

         const audio = new Audio(b64);
         audioRef.current = audio;
         audio.onended = () => {
           setPlayingMsgId(null);
           setLoadingAudio(false);
           audioRef.current = null;
         };
         audio.play().catch(() => {
            setPlayingMsgId(null);
            setLoadingAudio(false);
         });
       } else {
         setPlayingMsgId(null);
         setLoadingAudio(false);
       }
     } catch {
       setPlayingMsgId(null);
       setLoadingAudio(false);
     }
  };

  const toggleTTS = (msgId: number) => {
    if (playingMsgId === msgId) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingMsgId(null);
      setLoadingAudio(false);
    } else {
      const msg = messages.find(m => m.id === msgId);
      if (msg && !msg.isUser) {
        playTTS(msg.text, msgId, emotion);
      }
    }
  };

  const handleUpload = async (file: File) => {
    try {
      setMessages(prev => [...prev, {
        id: Date.now(),
        isUser: true,
        text: `[正在上传文件: ${file.name}...]`
      }]);

      const res = await api.upload(file);

      if (res && (res.status === 'success' || res.data?.file_path)) {
        setMessages(prev => [...prev, {
          id: Date.now() + 1,
          isUser: false,
          text: `文件上传成功: ${file.name}`
        }]);
      } else {
        throw new Error(res?.detail || 'Upload failed');
      }
    } catch (e: any) {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        isUser: false,
        text: `上传失败: ${e.message || e}`
      }]);
    }
  };

  const handleDeleteMessage = (id: number) => {
    setMessages(prev => prev.filter(m => m.id !== id));
  };

  return (
    <div 
      className="min-h-screen text-white font-sans selection:bg-white/20 overflow-hidden relative transition-colors duration-1000"
      style={{ background: currentColors[2] }}
    >
      {/* Ambient Background */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
         <div className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full blur-[150px] opacity-40 mix-blend-screen animate-pulse"
              style={{ background: currentColors[0] }} />
         <div className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full blur-[150px] opacity-30 mix-blend-screen animate-pulse"
              style={{ background: currentColors[1], animationDelay: '2s' }} />
         <div className="absolute top-[40%] left-[40%] w-[40%] h-[40%] rounded-full blur-[120px] opacity-20 mix-blend-screen animate-pulse"
              style={{ background: currentColors[3], animationDelay: '4s' }} />
      </div>

      {/* Main Layout */}
      <div className="relative z-10 flex h-screen">
        {/* Sidebar */}
        <div className={`flex flex-col gap-2 p-4 transition-all duration-300 ease-out border-r border-white/5 bg-black/20 backdrop-blur-xl ${sidebarOpen ? 'w-64' : 'w-20'}`}>
           <div className="flex items-center gap-3 px-2 py-4 mb-6 cursor-pointer" onClick={() => setSidebarOpen(!sidebarOpen)}>
              {sidebarOpen && (
                 <div className="flex flex-col">
                  <span className="font-bold tracking-[0.2em] text-3xl" style={{ fontFamily: "'Cinzel', serif" }}>{persona?.name?.toUpperCase() || "AVELINE"}</span>
                  <span className="text-[10px] text-white/40 tracking-[0.2em]">OS V2.0</span>
               </div>
              )}
           </div>

           <div className="flex-1 space-y-1">
              {SIDEBAR_ITEMS.map(item => (
                <SidebarButton 
                  key={item.id} 
                  item={item} 
                  isActive={activeTab === item.id} 
                  isExpanded={sidebarOpen}
                  onClick={() => setActiveTab(item.id)} 
                />
              ))}
           </div>

           <div className="mt-auto pt-4 border-t border-white/10 space-y-2">
             {sidebarOpen && (
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/5 flex items-center justify-between">
                   <div className="flex flex-col">
                      <span className="text-[10px] text-white/40">MODEL</span>
                      <span className="text-xs text-white/80 truncate w-32">{selectedModel?.name || 'Auto'}</span>
                   </div>
                   <Settings size={14} className="text-white/40" />
                </div>
             )}
           </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 flex flex-col relative overflow-hidden">
           {/* Header */}
           <div className="h-16 border-b border-white/5 bg-black/10 backdrop-blur-sm flex items-center justify-between px-8 flex-shrink-0">
              <div className="font-mono text-xs text-white/40 tracking-widest">{clock}</div>
              <div className="flex items-center gap-4">
                 <DeviceWidget 
                   cpu={stats.cpu} 
                   gpu={stats.gpu} 
                   memory={stats.memory} 
                   colors={currentColors} 
                   emotion={emotion} 
                 />
              </div>
           </div>

           {/* Tab Content */}
           {activeTab === 'Chat' && (
             <>
               <ChatPanel 
                 messages={messages} 
                 isTyping={isTyping} 
                 playingMsgId={playingMsgId} 
                 loadingAudio={loadingAudio} 
                 currentColors={currentColors}
                 onToggleTTS={toggleTTS}
                 onDelete={handleDeleteMessage}
               />
               <InputArea 
                 input={input} 
                 setInput={setInput} 
                 onSend={handleSend} 
                 isTyping={isTyping} 
                 voices={voices}
                 selectedVoiceId={selectedVoiceId}
                 setSelectedVoiceId={setSelectedVoiceId}
                 onUpload={handleUpload}
               />
             </>
           )}

           {activeTab === 'Plugins' && (
             <ErrorBoundary componentName="PluginsPanel">
               <PluginsPanel 
                 models={models} 
                 selectedModel={selectedModel} 
                 setSelectedModel={setSelectedModel}
                 responseLength={responseLength}
                 setResponseLength={setResponseLength}
               />
             </ErrorBoundary>
           )}

           {activeTab === 'Memory' && (
             <MemoryPanel 
               messages={messages} 
               setMessages={setMessages} 
               onToggleTTS={toggleTTS} 
               onDelete={handleDeleteMessage}
               storageKey={STORAGE_KEY}
             />
           )}

           {activeTab === 'Console' && (
             <div className="flex-1 p-8 flex items-center justify-center text-white/30">
               Console functionality coming soon...
             </div>
           )}
        </div>
      </div>
    </div>
  );
}
