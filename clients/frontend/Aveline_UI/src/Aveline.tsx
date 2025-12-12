import React, { useState, useEffect, useRef } from 'react';
import { Settings, Cpu, Ghost } from 'lucide-react';
import { api } from './api/apiService';
import { Message } from './types';
import { SIDEBAR_ITEMS } from './utils/constants';
import { resolveEmotionFromLabel, stripEmotionMarkers, ttsParamsForEmotion } from './utils/emotion';
import { useStatus } from './hooks/useStatus';
import { useModels } from './hooks/useModels';
import { useWebSocket } from './hooks/useWebSocket';
import { useImageModels } from './hooks/useImageModels';

import SidebarButton from './components/SidebarButton';
import DesktopPet from './components/DesktopPet';
import DeviceWidget from './components/DeviceWidget';
import ErrorBoundary from './components/ErrorBoundary';
import PluginsPanel from './components/PluginsPanel';
import MemoryPanel from './components/MemoryPanel';
import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';
import ImageModelSelector from './components/ImageModelSelector';
import { useBreathingColors, BreathingBackground } from './components/BreathingSystem';
import EmotionWidget from './components/EmotionWidget';
import StatusPanel from './components/StatusPanel';
import PersonaPanel from './components/PersonaPanel';
import StudyPanel from './components/StudyPanel';
import { SessionList } from './components/SessionList';

const STORAGE_KEY = 'aveline_chat_history_v2';

export default function Aveline() {
  // Hooks
  const { stats, clock, emotion, setEmotion, setEmotionLockUntil, emotionLockUntil } = useStatus();
  const { colors: currentColors, speed: breathingSpeed } = useBreathingColors(stats, emotion, emotionLockUntil);
  const { models, selectedModel, setSelectedModel } = useModels();
  const imageModel = useImageModels();

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
      
      if (msg.type === 'life_status' && msg.data) {
        setLifeStatus(msg.data);
      }

      if (msg.type === 'persona_update' && msg.data) {
        setPersona(msg.data);
      }
    }
  });

  // UI State
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showPet, setShowPet] = useState(false);
  const [activeTab, setActiveTab] = useState('Chat');
  const [lifeStatus, setLifeStatus] = useState<any>(null);
  
  // Proactive Chat State
  const lastInteractionRef = useRef(Date.now());
  const hasProactedRef = useRef(false);

  // Check if we are in Pet Mode (via URL hash)
  useEffect(() => {
    if (window.location.hash === '#/pet-mode') {
      setShowPet(true);
      // In Pet Mode, we might want to hide the rest of the UI visually or just rely on the DesktopPet component overlaying everything.
      // Since DesktopPet is fixed/z-50, we just need to make sure the background is transparent.
      document.body.style.backgroundColor = 'transparent';
      document.documentElement.style.backgroundColor = 'transparent';
      document.body.style.overflow = 'hidden'; // Prevent scrollbars
    }
  }, []);

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
  
  // Session State
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  // Audio State
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>("");
  const [playingMsgId, setPlayingMsgId] = useState<number | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Effects
  // Reset idle timer on user interaction
  const resetIdleTimer = () => {
    lastInteractionRef.current = Date.now();
    hasProactedRef.current = false;
  };

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
                   text: msg.content,
                   // Add extra fields if available
               }));
               if (newMessages.length > 0) {
                   setMessages(newMessages);
               } else {
                   setMessages([{ id: 1, isUser: false, text: "新话题已开启。" }]);
               }
          }
      } catch (e) {
          console.error("Failed to load history", e);
          setMessages([{ id: Date.now(), isUser: false, text: "Failed to load history." }]);
      }
  };

  const handleCreateSession = async () => {
      try {
          const res = await api.createSession();
          if (res.status === 'success') {
              setCurrentSessionId(res.data.id);
              setMessages([{ id: Date.now(), isUser: false, text: "新话题已开启。" }]);
          }
      } catch (e) {
          console.error(e);
          throw e; // Propagate error to caller
      }
  };

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
    
    resetIdleTimer();
    
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

      // Ensure session exists
      let sessionId = currentSessionId;
      if (!sessionId) {
          const res = await api.createSession();
          if (res.status === 'success') {
              sessionId = res.data.id;
              setCurrentSessionId(sessionId);
          }
      }

      const res = await api.sendMessage(text, { 
        modelName: selectedModel?.id,
        maxTokens: maxTokens,
        conversationId: sessionId || undefined
      });
      const fullReply = res?.reply || "Connection Error";
      
      // Handle proactive actions
      // Note: Backend now handles auto-generation if [GEN_IMG] is present.
      // We rely on res.image_url / res.image_base64 being returned.
      /* 
      if (res?.image_prompt) {
          try {
              const { modelPath, loraPath, loraWeight } = imageModel.getGenerationParams();
              api.generateImage(res.image_prompt, modelPath, loraPath, loraWeight);
          } catch (e) {
              console.error("Failed to trigger image generation", e);
          }
      }
      */

      if (res?.voice_id) {
          // Check if this is a voice MESSAGE or just a voice switch
          // For now, if voice_id is returned, we assume the CURRENT message is spoken if it's not a pure text response
          // But the backend doesn't explicitly flag "voice message" yet, so we'll rely on the directive
          // If [VOICE: id] was stripped, res.voice_id is set.
          
          // If the AI suggests a voice, update the selected voice if it exists
          const voiceExists = voices.some(v => v.id === res.voice_id);
          if (voiceExists) {
              setSelectedVoiceId(res.voice_id);
              console.log(`AI switched voice to: ${res.voice_id}`);
          }
      }
      
      // Parse emotion
      let emoLabel = null;
      
      // 1. Try backend detected emotion
      if (res?.emotion && res.emotion !== 'neutral') {
          emoLabel = res.emotion;
      } 
      // 2. Fallback to regex match
      else {
          const emoMatch = fullReply.match(/\[EMO:\s*\{?\s*([a-zA-Z0-9_]+)\s*\}?\]/) || fullReply.match(/\{([^\}]+)\}/);
          emoLabel = emoMatch ? emoMatch[1] : null;
      }

      const cleanText = stripEmotionMarkers(fullReply);
      
      if (emoLabel) {
        const parsed = resolveEmotionFromLabel(emoLabel);
        setEmotion(parsed);
        setEmotionLockUntil(Date.now() + 45000); // Lock for 45s
      }

      // If it's a voice message (implied by having a voice_id set in this turn and user request), 
      // we might want to treat it differently.
      // But for now, let's assume if voice_id is present, it IS a voice message.
      const isVoiceMsg = !!res?.voice_id;

      // Smart splitting for "Daily Mode" feel
      // Don't split code blocks or very short text
      if (cleanText.includes('```') || cleanText.length < 10 || isVoiceMsg || res?.image_url || res?.image_base64) {
         setMessages(prev => [...prev, { 
             id: Date.now() + 1, 
             isUser: false, 
             text: cleanText,
             messageType: isVoiceMsg ? 'voice' : 'text',
             voiceId: res?.voice_id,
             imageUrl: res?.image_url,
             imageBase64: res?.image_base64
         }]);
      } else {
         // Split by sentence terminators
          const parts = cleanText.match(/[^。！？\n~～]+[。！？\n~～]*/g) || [cleanText];
          const segments = parts.map(p => p.trim()).filter(p => p);

         if (segments.length === 0) {
             setMessages(prev => [...prev, { id: Date.now() + 1, isUser: false, text: cleanText }]);
         } else {
             // Send segments sequentially with typing effect
             for (const segment of segments) {
                 setIsTyping(true);
                 // Typing delay: base 400ms + dynamic
                 await new Promise(r => setTimeout(r, 400 + Math.min(segment.length * 30, 2000)));
                 
                 setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: segment }]);
                 setIsTyping(false);
                 
                 // Pause between messages
                 if (segments.length > 1) {
                    await new Promise(r => setTimeout(r, 300));
                 }
             }
         }
      }

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

      // Get reference audio from session storage
      const refAudio = sessionStorage.getItem('selected_ref_audio');

      const res = await Promise.race([
        api.tts({
          text,
          text_language: "中英混合",
          prompt_language: "中英混合",
          speed: params.speed,
          pitch: params.pitch,
          emotion: params.emotion,
          gpt_sovits_weights: msg?.voiceId || selectedVoiceId,
          reference_audio: refAudio
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

  useEffect(() => {
    const checkIdle = async () => {
      const now = Date.now();
      const IDLE_THRESHOLD = 60 * 1000; // 60s idle threshold
      
      if (now - lastInteractionRef.current > IDLE_THRESHOLD && !hasProactedRef.current && messages.length > 0 && !isTyping) {
        // Don't trigger if last message is error
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && !lastMsg.isUser && (lastMsg.text.includes("Error") || lastMsg.text.includes("..."))) return;

        hasProactedRef.current = true;
        
        try {
           const res = await api.sendMessage("[SYSTEM: User has been idle for >1 min. Please initiate a new topic or ask a caring question naturally. Do not mention you are an AI or this is a system prompt. Be brief.]", {
             modelName: selectedModel?.id,
             maxTokens: 100
           });
           
           if (res?.reply) {
             const cleanText = stripEmotionMarkers(res.reply);
             if (cleanText) {
                setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: cleanText }]);
             }
           }
        } catch (e) {
           // Silent fail
        }
      }
    };
    
    const timer = setInterval(checkIdle, 10000);
    return () => clearInterval(timer);
  }, [messages, selectedModel, isTyping]);

  if (showPet && window.location.hash === '#/pet-mode') {
    return (
      <>
          <DesktopPet 
            emotion={emotion} 
            isTyping={isTyping} 
            lastMessage={messages[messages.length - 1] || null} 
            onClose={() => {
              // If we are in web mode, just exit pet mode
              if (window.location.hash !== '#/pet-mode') {
                  setShowPet(false);
              } else {
                  // If in Electron pet mode, close the window
                  if (navigator.userAgent.toLowerCase().includes('electron')) {
                      window.close();
                  } else {
                      window.location.hash = '';
                      window.location.reload();
                  }
              }
            }}
            onInteract={() => {}}
          />
        <div style={{ display: 'none' }}>
          <audio ref={audioRef} onEnded={() => setPlayingMsgId(null)} onError={() => setPlayingMsgId(null)} />
        </div>
      </>
    );
  }

  return (
    <div 
      className="min-h-screen text-white font-sans selection:bg-white/20 overflow-hidden relative transition-colors duration-1000"
      style={{ background: currentColors[2] }}
    >
      {/* Ambient Background */}
      <BreathingBackground colors={currentColors} speed={breathingSpeed} />

      {/* Main Layout */}
      {showPet ? (
         <DesktopPet 
           emotion={emotion} 
           isTyping={isTyping} 
           lastMessage={messages[messages.length - 1]} 
           onClose={() => setShowPet(false)}
           onInteract={() => {
             setShowPet(false);
             setActiveTab('Chat');
           }}
         />
      ) : (
      <div className="relative z-10 flex h-screen">
        {/* Sidebar */}
        <div 
           className={`flex flex-col gap-2 p-4 transition-all duration-300 ease-out border-r border-white/5 bg-black/20 backdrop-blur-xl ${sidebarOpen ? 'w-64' : 'w-20'}`}
           onClick={() => setSidebarOpen(!sidebarOpen)}
        >
           <div className="flex items-center gap-3 px-2 py-4 mb-6 cursor-pointer">
              {sidebarOpen && (
                 <div className="flex flex-col">
                  <span className="font-bold tracking-[0.2em] text-3xl" style={{ fontFamily: "'Cinzel', serif" }}>{persona?.name?.toUpperCase() || "AVELINE"}</span>
                  <span className="text-[10px] text-white/40 tracking-[0.2em]">OS V2.0</span>
               </div>
              )}
           </div>

           <div className="flex-1 flex flex-col min-h-0 space-y-1">
              <div className="flex-shrink-0 space-y-1">
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

              {activeTab === 'Chat' && sidebarOpen && (
                 <div className="flex-1 mt-4 overflow-hidden border-t border-white/5 pt-2">
                    <SessionList 
                        currentSessionId={currentSessionId}
                        onSelectSession={(id) => setCurrentSessionId(id)}
                        onCreateSession={handleCreateSession}
                    />
                 </div>
              )}
           </div>

           <div className="mt-auto pt-4 border-t border-white/10 space-y-2">
             <SidebarButton 
                item={{ id: 'PetMode', icon: <Ghost size={20} />, label: 'Pet Mode', title: 'Desktop Pet Mode' }}
                isActive={showPet}
                isExpanded={sidebarOpen}
                onClick={() => setShowPet(true)} 
             />

             {sidebarOpen ? (
                <div 
                    className="px-3 py-3 rounded-xl bg-white/5 border border-white/5 flex items-center justify-between group hover:bg-white/10 transition-colors cursor-pointer"
                    onClick={(e) => { e.stopPropagation(); }}
                >
                   <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-emerald-500/20 to-blue-500/20 flex items-center justify-center border border-white/10">
                         <Cpu size={14} className="text-white/60" />
                      </div>
                      <div className="flex flex-col">
                          <span className="text-[10px] text-white/40 font-mono tracking-wider">ACTIVE MODEL</span>
                          <span className="text-xs text-white/90 font-medium truncate w-24">{selectedModel?.name || 'Auto'}</span>
                      </div>
                   </div>
                   <Settings size={14} className="text-white/30 group-hover:text-white/60 transition-colors" />
                </div>
             ) : (
                <div className="flex justify-center group">
                    <div className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center border border-white/5 group-hover:bg-white/10 transition-colors">
                        <Cpu size={16} className="text-white/40 group-hover:text-white/60" />
                    </div>
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
                onSuggestionClick={(text) => setInput(text)}
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

          {activeTab === 'Status' && (
            <StatusPanel 
              stats={stats} 
              emotion={emotion} 
              lifeStatus={lifeStatus} 
            />
          )}

          {activeTab === 'Persona' && (
            <PersonaPanel 
              persona={persona}
            />
          )}

          {activeTab === 'Study' && (
            <StudyPanel />
          )}

          {activeTab === 'Plugins' && (
             <ErrorBoundary componentName="PluginsPanel">
               <PluginsPanel 
            models={models}
            selectedModel={selectedModel}
            setSelectedModel={setSelectedModel}
            responseLength={responseLength}
            setResponseLength={setResponseLength}
            imageModel={imageModel}
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
        </div>
      </div>
      )}
    </div>
  );
}
