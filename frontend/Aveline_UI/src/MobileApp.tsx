import React, { useState, useEffect, useRef } from 'react';
import { Settings, Menu, ArrowLeft } from 'lucide-react';
import { api } from './api/apiService';
import { Message } from './types';
import { resolveEmotionFromLabel, stripEmotionMarkers, ttsParamsForEmotion } from './utils/emotion';
import { useStatus } from './hooks/useStatus';
import { useModels } from './hooks/useModels';

import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';
import ErrorBoundary from './components/ErrorBoundary';

const STORAGE_KEY = 'aveline_chat_history_v2';

export function MobileApp() {
  // Hooks
  const { stats, connected, clock, emotion, setEmotion, currentColors, setEmotionLockUntil } = useStatus();
  const { models, selectedModel, setSelectedModel } = useModels();

  // UI State
  const [showMenu, setShowMenu] = useState(false);
  
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
          const emoMatch = fullReply.match(/\[EMO:\s*\{?([a-zA-Z0-9_]+)\}?\]/) || fullReply.match(/\{([a-zA-Z]+)\}/);
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
           audioRef.current = null;
         };
         audio.play().catch(() => {
            setPlayingMsgId(null);
         });
       }
     } catch (e) {
       console.error("TTS Error", e);
     } finally {
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

  const handleDeleteMessage = (id: number) => {
    setMessages(prev => prev.filter(m => m.id !== id));
  };

  // Styles
  const currentTheme = {
    bg: 'bg-zinc-950',
    fg: 'text-zinc-100',
    accent: 'text-emerald-400',
    border: 'border-zinc-800',
  };

  return (
    <ErrorBoundary>
      <div className={`fixed inset-0 flex flex-col ${currentTheme.bg} ${currentTheme.fg}`}>
        {/* Mobile Header */}
        <div className={`h-14 flex items-center justify-between px-4 border-b ${currentTheme.border} bg-zinc-900/80 backdrop-blur z-10`}>
          <div className="flex items-center gap-3">
             {/* Status Dot */}
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-red-500'}`} />
            <span className="font-cinzel font-semibold text-lg tracking-wider">AVELINE</span>
          </div>
          <button 
            onClick={() => setShowMenu(!showMenu)}
            className="p-2 rounded-full hover:bg-zinc-800 transition-colors"
          >
            <Settings size={20} className="text-zinc-400" />
          </button>
        </div>

        {/* Settings Menu (Overlay) */}
        {showMenu && (
          <div className="absolute inset-0 z-50 bg-zinc-950/95 backdrop-blur-sm p-4 flex flex-col">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-xl font-semibold">Settings</h2>
              <button onClick={() => setShowMenu(false)} className="p-2 bg-zinc-800 rounded-full">
                <ArrowLeft size={20} />
              </button>
            </div>
            
            <div className="space-y-4">
               <div className="bg-zinc-900 p-4 rounded-lg border border-zinc-800">
                 <label className="block text-sm text-zinc-400 mb-2">Model</label>
                 <select 
                   value={selectedModel?.id || ''}
                   onChange={(e) => {
                     const m = models.find(x => x.id === e.target.value);
                     if(m) setSelectedModel(m);
                   }}
                   className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm outline-none focus:border-emerald-500/50"
                 >
                   {models.map(m => (
                     <option key={m.id} value={m.id}>{m.id}</option>
                   ))}
                 </select>
               </div>

               <div className="bg-zinc-900 p-4 rounded-lg border border-zinc-800">
                 <label className="block text-sm text-zinc-400 mb-2">Response Length</label>
                 <div className="flex bg-zinc-950 rounded p-1 border border-zinc-800">
                   {['short', 'normal', 'long'].map((len) => (
                     <button
                       key={len}
                       onClick={() => setResponseLength(len)}
                       className={`flex-1 py-1.5 text-xs rounded capitalize transition-all ${
                         responseLength === len 
                           ? 'bg-emerald-500/10 text-emerald-400 font-medium' 
                           : 'text-zinc-500 hover:text-zinc-300'
                       }`}
                     >
                       {len}
                     </button>
                   ))}
                 </div>
               </div>

               <div className="bg-zinc-900 p-4 rounded-lg border border-zinc-800">
                 <label className="block text-sm text-zinc-400 mb-2">Voice</label>
                 <select 
                   value={selectedVoiceId}
                   onChange={(e) => setSelectedVoiceId(e.target.value)}
                   className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm outline-none focus:border-emerald-500/50"
                 >
                   {voices.map(v => (
                     <option key={v.id} value={v.id}>{v.name}</option>
                   ))}
                 </select>
               </div>
            </div>
            
            <div className="mt-auto text-xs text-center text-zinc-600">
               Aveline Mobile v1.0
               <br />
               {clock}
            </div>
          </div>
        )}

        {/* Chat Area */}
        <div className="flex-1 overflow-hidden relative">
          <ChatPanel 
             messages={messages}
             isTyping={isTyping}
             playingMsgId={playingMsgId}
             loadingAudio={loadingAudio}
             currentColors={currentColors}
             onToggleTTS={toggleTTS}
             onDelete={handleDeleteMessage}
          />
        </div>

        {/* Input Area */}
        <div className="flex-none bg-zinc-900/50 border-t border-zinc-800 pb-safe">
           <InputArea 
             input={input}
             setInput={setInput}
             onSend={handleSend}
             isTyping={isTyping}
             voices={voices}
             selectedVoiceId={selectedVoiceId}
             setSelectedVoiceId={setSelectedVoiceId}
           />
        </div>
      </div>
    </ErrorBoundary>
  );
}
