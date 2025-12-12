import React, { useState, useEffect, useRef } from 'react';
import { Settings, Menu, ArrowLeft, Save, MessageSquare, Database, LayoutGrid, User, Activity, X, BookOpen } from 'lucide-react';
import { api } from './api/apiService';
import config from './api/config';
import { Message } from './types';
import { resolveEmotionFromLabel, stripEmotionMarkers, ttsParamsForEmotion, inferEmotionFromText } from './utils/emotion';
import { useStatus } from './hooks/useStatus';
import { useBreathingColors, BreathingBackground } from './components/BreathingSystem';
import { useModels } from './hooks/useModels';
import { useWebSocket } from './hooks/useWebSocket';
import { useImageModels } from './hooks/useImageModels';

// Components
import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';
import ErrorBoundary from './components/ErrorBoundary';
import DeviceWidget from './components/DeviceWidget';
import MemoryPanel from './components/MemoryPanel';
import PluginsPanel from './components/PluginsPanel';
import PersonaPanel from './components/PersonaPanel';
import StatusPanel from './components/StatusPanel';
import StudyPanel from './components/StudyPanel';
import { SessionList } from './components/SessionList';

const STORAGE_KEY = 'aveline_chat_history_v2';

export function MobileApp() {
  // Hooks
  const { stats, connected, clock, emotion, setEmotion, emotionLockUntil, setEmotionLockUntil } = useStatus();
  const { colors: currentColors, speed: breathingSpeed } = useBreathingColors(stats, emotion, emotionLockUntil);
  const { models, selectedModel, setSelectedModel } = useModels();
  const imageModel = useImageModels();

  // UI State
  const [activeTab, setActiveTab] = useState('Chat');
  const [showSettings, setShowSettings] = useState(false);
  const [showSessions, setShowSessions] = useState(false);
  const [serverUrl, setServerUrl] = useState(() => localStorage.getItem('AVELINE_API_URL') || config.apiBaseUrl);
  
  // Chat State
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      // If we have saved messages, use them.
      // If not, return empty array and let the proactive greeting (or system init) handle the first message.
      // This prevents "System Ready" + "Greeting" double message on fresh start.
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [responseLength, setResponseLength] = useState<string>('normal');
  
  // Persona & Session State
  const [persona, setPersona] = useState<any>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [lifeStatus, setLifeStatus] = useState<any>(null);

  // Audio State
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>("");
  const [playingMsgId, setPlayingMsgId] = useState<number | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // WebSocket
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
      
      if (msg.type === 'life_status' && msg.data) {
        setLifeStatus(msg.data);
        // Sync emotion from life_status if available
        if (msg.data.emotion) {
             // If it's a string, resolve it. If it's an object/number, might need mapping.
             // Assuming it sends the emotion label (e.g., 'happy', 'neutral')
             const emo = resolveEmotionFromLabel(msg.data.emotion);
             // Only update if not locked (e.g. by recent chat response)
             if (Date.now() > emotionLockUntil) {
                setEmotion(emo);
             }
        }
      }

      if (msg.type === 'persona_update' && msg.data) {
        setPersona(msg.data);
      }
    }
  });

  // Effects
  useEffect(() => {
    // Expose Aveline Native Interface
    (window as any).aveline = {
      autoSend: (text: string) => {
        setPendingAutoSend(text);
      }
    };
    return () => {
      delete (window as any).aveline;
    };
  }, []);

  const [pendingAutoSend, setPendingAutoSend] = useState<string | null>(null);

  useEffect(() => {
    if (pendingAutoSend) {
      setInput(pendingAutoSend);
      const timer = setTimeout(() => {
          handleSendWithText(pendingAutoSend);
          setPendingAutoSend(null);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [pendingAutoSend]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  }, [messages]);

  // Initial Data Fetch
  useEffect(() => {
    api.listVoices({ silent: true }).then((res: any) => {
       const list = res?.data?.voices || [];
       setVoices(list);
       if (list.length > 0) setSelectedVoiceId(String(list[0].id));
    }).catch(() => {});

    api.getPersona({ silent: true }).then((res: any) => {
      if (res?.data) setPersona(res.data);
    }).catch(() => {});

    // Proactive Greeting
    const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
    if (!hasGreeted && messages.length === 0) {
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

  // Session Management Logic
  useEffect(() => {
      const last = localStorage.getItem('aveline_last_session_id');
      if (last) setCurrentSessionId(last);
  }, []);

  useEffect(() => {
      if (currentSessionId) {
          localStorage.setItem('aveline_last_session_id', currentSessionId);
          loadSessionHistory(currentSessionId);
      }
  }, [currentSessionId]);

  const loadSessionHistory = async (sessionId: string) => {
      if (!sessionId || sessionId === 'null') return;
      try {
          const res = await api.getSessionHistory(sessionId);
          if (res.status === 'success' && Array.isArray(res.data)) {
               const newMessages = res.data.map((msg: any, index: number) => ({
                   id: index + Date.now(),
                   isUser: msg.role === 'user',
                   text: stripEmotionMarkers(msg.content),
               }));
               
               if (newMessages.length > 0) {
                   setMessages(newMessages);
                   
                   // Try to restore emotion from the last assistant message
                   const lastMsg = res.data[res.data.length - 1];
                   if (lastMsg && (lastMsg.role === 'assistant' || !lastMsg.role)) {
                        const fullReply = lastMsg.content;
                        const emoMatch = fullReply.match(/\[EMO:\s*\{?\s*([a-zA-Z0-9_]+)\s*\}?\]/) 
                                        || fullReply.match(/\{([a-zA-Z]+)\}/)
                                        || fullReply.match(/\[([a-zA-Z]+)\]/);
                        if (emoMatch) {
                            const parsed = resolveEmotionFromLabel(emoMatch[1]);
                            setEmotion(parsed);
                        }
                   }
               } else {
                   setMessages([]);
               }
          }
      } catch (e) {
          console.error("Failed to load history", e);
      }
  };

  const handleCreateSession = async () => {
      try {
          const res = await api.createSession();
          if (res.status === 'success') {
              setCurrentSessionId(res.data.id);
              // Clear messages first
              setMessages([]);
              
              // Only add greeting if not proactive
              const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
              if (!hasGreeted) {
                  // Wait for greeting or show simple text
                  setMessages([{ id: Date.now(), isUser: false, text: "新话题已开启。" }]);
              } else {
                  // Do not add "新话题已开启" text if we want a clean state, 
                  // but user might want confirmation. Let's keep it minimal.
                  // Or maybe just empty?
                  // User complained about "duplicate greeting". 
                  // If we start a new session, we probably don't want the "Greeting" API to fire again?
                  // But "New Topic" text is local.
              }
              
              setShowSessions(false); // Close drawer on new session
          }
      } catch (e) {
          console.error(e);
          throw e;
      }
  };

  // Handlers
  const handleSendWithText = async (textToSend: string) => {
      if (!textToSend.trim() || isTyping) return;
      
      const userMsg: Message = { id: Date.now(), isUser: true, text: textToSend };
      setMessages(prev => [...prev, userMsg]);
      setInput('');
      setIsTyping(true);
  
      try {
        const maxTokensMap: Record<string, number> = {
          short: 50,
          normal: 150,
          long: 400
        };
        // Remove token limit for Study mode
        const maxTokens = activeTab === 'Study' ? 4096 : (maxTokensMap[responseLength] || 150);

      // Ensure session exists
      let sessionId = currentSessionId;
      if (!sessionId) {
          const res = await api.createSession();
          if (res.status === 'success') {
              sessionId = res.data.id;
              setCurrentSessionId(sessionId);
          }
      }

      const res = await api.sendMessage(textToSend, { 
        modelName: selectedModel?.id,
        maxTokens: maxTokens,
        conversationId: sessionId || undefined
      });
      
      await processResponse(res);
    } catch (e) {
        setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: "Error connecting to AI Core." }]);
      } finally {
        setIsTyping(false);
      }
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    await handleSendWithText(input.trim());
  };

  const processResponse = async (res: any) => {
      const fullReply = res?.response || res?.reply || "Connection Error";
      
      // Update session ID if new
      if (res?.conversation_id && res.conversation_id !== currentSessionId) {
          setCurrentSessionId(res.conversation_id);
      }

      // Parse emotion
      let emoLabel = null;
      if (res?.emotion) {
          emoLabel = res.emotion;
      } else {
          // Fallback regex for [EMO:happy], {happy}, or [happy]
          const emoMatch = fullReply.match(/\[EMO:\s*\{?\s*([a-zA-Z0-9_]+)\s*\}?\]/) 
                        || fullReply.match(/\{([a-zA-Z]+)\}/)
                        || fullReply.match(/\[([a-zA-Z]+)\]/);
          emoLabel = emoMatch ? emoMatch[1] : null;
      }

      const cleanText = stripEmotionMarkers(fullReply);
      
      // If no explicit emotion tag, infer from text content
      if (!emoLabel || emoLabel === 'neutral') {
          const inferred = inferEmotionFromText(cleanText);
          if (inferred !== 'neutral') {
              emoLabel = inferred;
          }
      }
      
      if (emoLabel) {
        const parsed = resolveEmotionFromLabel(emoLabel);
        setEmotion(parsed);
        setEmotionLockUntil(Date.now() + 5000); 
      }

      // Smart splitting
      if (cleanText.includes('```') || cleanText.length < 10) {
         setMessages(prev => [...prev, { id: Date.now() + 1, isUser: false, text: cleanText }]);
         setIsTyping(false);
         return;
      }

      const parts = cleanText.match(/[^。！？\n~～]+[。！？\n~～]*/g) || [cleanText];
      const segments = parts.map(p => p.trim()).filter(p => p);

      if (segments.length === 0) {
          setIsTyping(false);
          return;
      }

      for (const segment of segments) {
          setIsTyping(true);
          await new Promise(r => setTimeout(r, 400 + Math.min(segment.length * 30, 2000)));
          setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: segment }]);
          setIsTyping(false);
          if (segments.length > 1) await new Promise(r => setTimeout(r, 300));
      }
  };

  const playTTS = async (text: string, msgId: number, currentEmotion: string) => {
     try {
       if (audioRef.current) {
         audioRef.current.pause();
         audioRef.current = null;
       }
       
       setPlayingMsgId(msgId);
       
       const msg = messages.find(m => m.id === msgId);
       if (msg?.audioBase64) {
         const audio = new Audio(msg.audioBase64);
         audioRef.current = audio;
         audio.onended = () => {
           setPlayingMsgId(null);
           audioRef.current = null;
         };
         audio.play().catch(() => setPlayingMsgId(null));
         return;
       }

       setLoadingAudio(true);
       const params = ttsParamsForEmotion(currentEmotion as any);
       
       const timeoutPromise = new Promise((_, reject) => 
         setTimeout(() => reject(new Error("TTS Timeout")), 30000)
       );

       const refAudio = sessionStorage.getItem('selected_ref_audio');
      const res = await Promise.race([
        api.tts({
          text,
          text_language: "中英混合",
          prompt_language: "中英混合",
          speed: params.speed,
          pitch: params.pitch,
          emotion: params.emotion,
          gpt_sovits_weights: selectedVoiceId,
          reference_audio: refAudio || undefined
        }),
        timeoutPromise
      ]) as any;

       const b64 = res?.data?.audio_base64;
       if (b64) {
         setMessages(prev => prev.map(m => m.id === msgId ? { ...m, audioBase64: b64 } : m));
         const audio = new Audio(b64);
         audioRef.current = audio;
         audio.onended = () => {
           setPlayingMsgId(null);
           audioRef.current = null;
         };
         audio.play().catch(() => setPlayingMsgId(null));
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

  const handleSaveUrl = () => {
    localStorage.setItem('AVELINE_API_URL', serverUrl);
    window.location.reload();
  };

  // Mobile Navigation Items
  const navItems = [
    { id: 'Chat', icon: <MessageSquare size={20} />, label: 'Chat' },
    { id: 'Memory', icon: <Database size={20} />, label: 'Memory' },
    { id: 'Study', icon: <BookOpen size={20} />, label: 'Study' },
    { id: 'Plugins', icon: <LayoutGrid size={20} />, label: 'Apps' },
    { id: 'Status', icon: <Activity size={20} />, label: 'Status' },
    { id: 'Settings', icon: <User size={20} />, label: 'Me' },
  ];

  return (
    <ErrorBoundary>
      <div 
        className="fixed inset-0 flex flex-col text-zinc-100 overflow-hidden transition-colors duration-1000"
        style={{ background: currentColors[2] }}
      >
        {/* Background Breathing */}
        <div className="absolute inset-0 z-0 opacity-60 pointer-events-none">
            <BreathingBackground colors={currentColors} speed={breathingSpeed} />
        </div>
        
        {/* Header */}
        <div className="h-12 flex items-center justify-between px-4 border-b border-zinc-800 bg-zinc-900/80 backdrop-blur z-20 flex-none">
          <div className="flex items-center gap-3">
            <button onClick={() => setShowSessions(true)} className="p-1 -ml-1 text-zinc-400 hover:text-white">
                <Menu size={20} />
            </button>
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-red-500'}`} />
            <span className="font-cinzel font-semibold text-lg tracking-wider">AVELINE</span>
          </div>
          <div className="flex items-center gap-2">
             {/* Emotion Indicator */}
             <div className="px-2 py-0.5 rounded-full bg-white/5 text-[10px] uppercase tracking-wider text-zinc-400 border border-white/10">
                 {emotion}
             </div>
             <button onClick={() => setShowSettings(!showSettings)} className="p-2 -mr-2 text-zinc-400 hover:text-white">
                <Settings size={18} />
             </button>
          </div>
        </div>

        {/* Sessions Overlay */}
        {showSessions && (
          <div className="absolute inset-0 z-50 bg-zinc-950/95 backdrop-blur-md flex flex-col animate-in slide-in-from-left duration-200">
             <div className="flex items-center p-4 border-b border-zinc-800 justify-between">
                <span className="font-semibold text-lg">Sessions</span>
                <button onClick={() => setShowSessions(false)} className="p-2 -mr-2 hover:bg-zinc-800 rounded-full">
                    <X size={20} />
                </button>
             </div>
             <div className="flex-1 overflow-hidden p-4">
                <SessionList 
                    currentSessionId={currentSessionId}
                    onSelectSession={(id) => {
                        setMessages([]); // Clear messages when explicitly switching sessions
                        setCurrentSessionId(id);
                        setShowSessions(false);
                    }}
                    onCreateSession={handleCreateSession}
                />
             </div>
          </div>
        )}

        {/* Settings Overlay */}
        {showSettings && (
          <div className="absolute inset-0 z-50 bg-zinc-950/95 backdrop-blur-md flex flex-col animate-in fade-in duration-200">
             <div className="flex items-center p-4 border-b border-zinc-800">
                <button onClick={() => setShowSettings(false)} className="p-2 -ml-2 hover:bg-zinc-800 rounded-full">
                    <ArrowLeft size={20} />
                </button>
                <h2 className="ml-2 font-medium">Global Settings</h2>
             </div>
             <div className="p-4 space-y-6 overflow-y-auto flex-1">
                 <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase font-medium tracking-wider">Server Connection</label>
                    <div className="flex gap-2">
                        <input 
                          type="text" 
                          value={serverUrl}
                          onChange={(e) => setServerUrl(e.target.value)}
                          className="flex-1 bg-zinc-900 border border-zinc-800 rounded p-3 text-sm outline-none focus:border-emerald-500/50"
                          placeholder="http://192.168.1.X:8000"
                        />
                        <button onClick={handleSaveUrl} className="p-3 bg-emerald-500/20 text-emerald-400 rounded hover:bg-emerald-500/30">
                            <Save size={18} />
                        </button>
                    </div>
                 </div>

                 <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase font-medium tracking-wider">AI Model</label>
                    <select 
                      value={selectedModel?.id || ''}
                      onChange={(e) => {
                        const m = models.find(x => x.id === e.target.value);
                        if(m) setSelectedModel(m);
                      }}
                      className="w-full bg-zinc-900 border border-zinc-800 rounded p-3 text-sm outline-none focus:border-emerald-500/50"
                    >
                      {models.map(m => (
                        <option key={m.id} value={m.id}>{m.id}</option>
                      ))}
                    </select>
                 </div>

                 <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase font-medium tracking-wider">Voice</label>
                    <select 
                      value={selectedVoiceId}
                      onChange={(e) => setSelectedVoiceId(e.target.value)}
                      className="w-full bg-zinc-900 border border-zinc-800 rounded p-3 text-sm outline-none focus:border-emerald-500/50"
                    >
                      {voices.map(v => (
                        <option key={v.id} value={v.id}>{v.name}</option>
                      ))}
                    </select>
                 </div>

                 <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase font-medium tracking-wider">Response Length</label>
                    <div className="flex bg-zinc-900 rounded p-1 border border-zinc-800">
                        {['short', 'normal', 'long'].map((len) => (
                            <button
                            key={len}
                            onClick={() => setResponseLength(len)}
                            className={`flex-1 py-2 text-xs rounded capitalize transition-all ${
                                responseLength === len 
                                ? 'bg-zinc-800 text-emerald-400 font-medium shadow-sm' 
                                : 'text-zinc-500'
                            }`}
                            >
                            {len}
                            </button>
                        ))}
                    </div>
                 </div>
             </div>
          </div>
        )}

        {/* Main Content Area */}
        <div className="flex-1 overflow-hidden relative z-10 flex flex-col">
           {activeTab === 'Chat' && (
               <>
                <div className="flex-1 overflow-hidden relative flex flex-col">
                    <ChatPanel 
                        messages={messages}
                        isTyping={isTyping}
                        playingMsgId={playingMsgId}
                        loadingAudio={loadingAudio}
                        currentColors={currentColors}
                        onToggleTTS={toggleTTS}
                        onDelete={handleDeleteMessage}
                        onSuggestionClick={(text) => handleSendWithText(text)}
                    />
                </div>
                <div className="flex-none bg-zinc-900/50 border-t border-zinc-800 backdrop-blur-sm">
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
               </>
           )}

           {activeTab === 'Memory' && (
               <div className="flex-1 overflow-y-auto p-4">
                   <MemoryPanel 
                        messages={messages}
                        setMessages={setMessages}
                        onToggleTTS={toggleTTS}
                        onDelete={handleDeleteMessage}
                        storageKey={STORAGE_KEY}
                   />
               </div>
           )}

           {activeTab === 'Study' && (
               <div className="flex-1 overflow-hidden relative flex flex-col">
                   <StudyPanel />
               </div>
           )}

           {activeTab === 'Plugins' && (
               <div className="flex-1 overflow-y-auto p-4">
                   <PluginsPanel 
                        models={models}
                        selectedModel={selectedModel}
                        setSelectedModel={setSelectedModel}
                        responseLength={responseLength}
                        setResponseLength={setResponseLength}
                        imageModel={imageModel}
                   />
               </div>
           )}

            {activeTab === 'Status' && (
               <div className="flex-1 overflow-y-auto p-4 space-y-4">
                   <StatusPanel 
                        stats={stats}
                        emotion={emotion}
                        lifeStatus={lifeStatus}
                   />
                   <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-4">
                        <DeviceWidget 
                            cpu={stats.cpu} 
                            gpu={stats.gpu} 
                            memory={stats.memory} 
                            colors={currentColors} 
                            emotion={emotion} 
                        />
                   </div>
               </div>
           )}

           {activeTab === 'Settings' && (
               <div className="flex-1 overflow-y-auto p-4">
                   <PersonaPanel persona={persona} />
               </div>
           )}
        </div>

        {/* Bottom Navigation */}
        <div className="h-16 bg-zinc-950 border-t border-zinc-900 flex items-center justify-around px-2 z-20 pb-safe">
            {navItems.map((item) => (
                <button
                    key={item.id}
                    onClick={() => setActiveTab(item.id)}
                    className={`flex flex-col items-center justify-center w-full h-full space-y-1 transition-all duration-200 ${
                        activeTab === item.id 
                        ? 'text-emerald-400' 
                        : 'text-zinc-600 hover:text-zinc-400'
                    }`}
                >
                    <div className={`p-1 rounded-xl transition-all ${activeTab === item.id ? 'bg-emerald-500/10' : ''}`}>
                        {item.icon}
                    </div>
                    <span className="text-[10px] font-medium tracking-wide">{item.label}</span>
                </button>
            ))}
        </div>
      </div>
    </ErrorBoundary>
  );
}
