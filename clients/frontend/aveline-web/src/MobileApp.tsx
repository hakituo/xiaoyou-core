import React, { useState, useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { MessageSquare, Database, LayoutGrid, User, Activity, BookOpen, Utensils, Calendar } from 'lucide-react';
import { ImpactStyle } from '@capacitor/haptics';
import { api } from './api/apiService';
import config from './api/config';
import { Message } from './types';
import { resolveEmotionFromLabel, stripEmotionMarkers, stripSystemTags, inferEmotionFromText } from './utils/emotion';
import { smartSegmentText, isRetractionSegment, segmentByRetractionOnly } from './utils/text';
import { useStatus } from './hooks/useStatus';
import { useAvelineStore } from './store/useStore';
import { useBreathingSystem, BreathingBackground } from './systems/BreathingSystem';
import { useWebSocket } from './hooks/useWebSocket';
import { useImageModels } from './hooks/useImageModels';
import { useModels } from './hooks/useModels';
import { useContextSync } from './hooks/useContextSync';
import { useMobileHaptics } from './hooks/useMobileHaptics';
import { useMobileViewport } from './hooks/useMobileViewport';
import { useMobileBackgroundMode } from './hooks/useMobileBackgroundMode';
import { useMobileNativeBack } from './hooks/useMobileNativeBack';
import { useMobileDeepLink } from './hooks/useMobileDeepLink';
import { useMobileKeyboardResize } from './hooks/useMobileKeyboardResize';
import { useMobileNativeSync } from './hooks/useMobileNativeSync';
import { useMobileInitialData } from './hooks/useMobileInitialData';
import { useMobileSidebarSwipe } from './hooks/useMobileSidebarSwipe';
import { useMobileSessionHistory } from './hooks/useMobileSessionHistory';
import { useMobileTTS } from './hooks/useMobileTTS';
import { useMobileStudyMode } from './hooks/useMobileStudyMode';
import { useMobileWebSocketHandler } from './hooks/useMobileWebSocketHandler';
import { useMobileMessageActions } from './hooks/useMobileMessageActions';
import { useMobileFileUpload } from './hooks/useMobileFileUpload';
import { useMobileSessionActions } from './hooks/useMobileSessionActions';

// Components
import ErrorBoundary from './components/ErrorBoundary';
import { ConfirmDialog } from './components/ui/ConfirmDialog';
import { MobileSidebar } from './components/mobile/MobileSidebar';
import { MobileSettingsOverlay } from './components/mobile/MobileSettingsOverlay';
import { MobileMainContent } from './components/mobile/MobileMainContent';
import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';
import MemoryPanel from './components/MemoryPanel';
import DailyDataPanel from './components/DailyDataPanel';
import StudyPanel from './components/StudyPanel';
import PersonaPanel from './components/PersonaPanel';
import PluginsPanel from './components/PluginsPanel';
import EmotionWidget from './components/EmotionWidget';
import { MobileStatusPanel } from './components/mobile/MobileStatusPanel';
import ShopPanel from './components/ShopPanel';

const STORAGE_KEY = 'aveline_chat_history_v2';

export function MobileApp() {
  // Enable mobile device context sync
  useContextSync();

  useEffect(() => {
    const prevBodyBg = document.body.style.backgroundColor;
    const prevHtmlBg = document.documentElement.style.backgroundColor;
    document.body.style.backgroundColor = '#18181b';
    document.documentElement.style.backgroundColor = '#18181b';
    return () => {
      document.body.style.backgroundColor = prevBodyBg;
      document.documentElement.style.backgroundColor = prevHtmlBg;
    };
  }, []);

  // Dialog State
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {}
  });

  // Hooks
  const { connected, clock } = useStatus();
  const {
    stats,
    emotion,
    setEmotion,
    emotionLockUntil,
    setEmotionLockUntil,
    emotionMix,
    setEmotionMix,
    autoTtsEnabled,
    replyDisplayMode,
  } = useAvelineStore();

  const { triggerHaptic, handleAutonomousVibration } = useMobileHaptics();
  
  const imageModel = useImageModels();
  const { models, selectedModel, setSelectedModel } = useModels();

  // UI State
  const [activeTab, setActiveTab] = useState('Chat');
  const [showSidebar, setShowSidebar] = useState(false);

  useMobileBackgroundMode(() => setActiveTab('Chat'));
  useMobileKeyboardResize();
  const [showSettings, setShowSettings] = useState(false);
  const [serverUrl, setServerUrl] = useState(() => localStorage.getItem('AVELINE_API_URL') || config.apiBaseUrl);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
  const [hasNative, setHasNative] = useState(false);
  const [residentEnabled, setResidentEnabled] = useState(false);

  useMobileNativeBack({
    showSettings,
    showSidebar,
    activeTab,
    setShowSettings,
    setShowSidebar,
    setActiveTab,
  });
  const viewportHeight = useMobileViewport();
  useMobileNativeSync();
  const {
    onAppTouchStart,
    onAppTouchMove,
    onAppTouchEnd,
    onSidebarTouchStart,
    onSidebarTouchMove,
    onSidebarTouchEnd,
  } = useMobileSidebarSwipe({
    showSidebar,
    showSettings,
    onOpenSidebar: () => setShowSidebar(true),
    onCloseSidebar: () => setShowSidebar(false),
  });

  // Chat State
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
           // Ensure history is properly segmented and retraction styles are preserved
           return parsed.flatMap((m: Message) => {
             if (m.isUser) return [m];
             if (m.messageType === 'retraction') return [m];
             // Skip splitting if it has rich content or is a special type
             if (m.audioBase64 || m.imageUrl || m.imageBase64 || (m.messageType && m.messageType !== 'text')) return [m];
             if (!m.text) return [m];
             
             const segments = smartSegmentText(m.text, false);
             if (segments.length <= 1 && !isRetractionSegment(m.text)) return [m];
             
             // Check if already segmented (heuristic: if previous/next messages have same ID prefix, maybe don't touch? 
             // But here we process one by one. If it's a big chunk, we split it.)
             // To avoid splitting already split messages, we can check if the text looks like a full sentence/paragraph.
             // But smartSegmentText is idempotent-ish? No.
             // If "A" is passed, it returns ["A"].
             // If "A. B" is passed, it returns ["A", "B"].
             // If the history already has "A" and "B" as separate messages, we process "A" -> ["A"], "B" -> ["B"]. Safe.
             
             return segments.map((seg, i) => ({
                 ...m,
                 id: i === 0 ? m.id : `${m.id}-${i}`,
                 text: seg,
                 messageType: isRetractionSegment(seg) ? 'retraction' : (m.messageType || 'text')
             }));
           });
        }
        return [];
      }
      return [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showTypingIndicator, setShowTypingIndicator] = useState(false);
  const [responseLength, setResponseLength] = useState<string>('normal');
  const [breathingRate, setBreathingRate] = useState<number>(1.0);
  const messagesRef = useRef<Message[]>(messages);
  const autoTtsHandledRef = useRef<Record<string, true>>({});

  useEffect(() => {
    if (!messages.length) return;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const item = messages[i];
      if (!item || item.isUser) continue;
      const baseId = String(item.id ?? '');
      if (!baseId || baseId.includes('-')) continue;
      const hasParts = messages.some(m => String(m.id).startsWith(`${baseId}-`));
      if (hasParts) continue;
      if (item.audioBase64 || item.imageUrl || item.imageBase64 || (item.messageType && item.messageType !== 'text')) continue;
      const clean = stripEmotionMarkers(String(item.text || ''));
      const segments = smartSegmentText(clean, false);
      if (segments.length <= 1) continue;
      const firstNormalIndex = segments.findIndex(seg => !isRetractionSegment(seg));
      const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
      const nextMessages = segments.map((segment, index) => {
        const isRetract = isRetractionSegment(segment);
        return {
          ...item,
          id: index === baseIndex ? baseId : `${baseId}-${index}`,
          text: segment,
          messageType: isRetract ? 'retraction' : (item.messageType || 'text')
        };
      });
      setMessages(prev => {
        const idx = prev.findIndex(m => String(m.id) === baseId);
        if (idx < 0) return prev;
        const next = [...prev];
        next.splice(idx, 1, ...nextMessages);
        return next;
      });
      break;
    }
  }, [messages, setMessages]);

  const normalizeAudioSrc = (raw: string): string => {
    const s = String(raw || '').trim();
    if (!s) return '';
    if (s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('http')) return s;
    return `data:audio/wav;base64,${s}`;
  };

  useEffect(() => {
    messagesRef.current = messages;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  }, [messages]);

  const applyEmotionFromText = (rawText: string, meta?: any) => {
    const fullReply = typeof rawText === 'string' ? rawText : '';
    const cleanText = stripEmotionMarkers(fullReply);

    let emoLabel: any = null;
    const explicit = meta?.emotion;
    if (explicit && String(explicit).toLowerCase() !== 'neutral') {
      emoLabel = explicit;
    } else {
      const emoMatch =
        fullReply.match(/\[EMO:\s*\{?\s*([a-zA-Z0-9_]+)\s*\}?\]/) ||
        fullReply.match(/\{([^\}]+)\}/) ||
        fullReply.match(/\[([^\]]+)\]/);
      emoLabel = emoMatch ? emoMatch[1] : null;
    }

    if (!emoLabel || String(emoLabel).toLowerCase() === 'neutral') {
      const inferred = inferEmotionFromText(cleanText);
      if (inferred !== 'neutral') {
        emoLabel = inferred;
      }
    }

    const internal = meta?.emotion_internal;
    if (internal && typeof internal === 'object') {
      setEmotionMix(internal);
    } else if (emoLabel) {
      setEmotionMix({ [String(emoLabel)]: 1.0 });
    }

    if (emoLabel && Date.now() > emotionLockUntil) {
      const parsed = resolveEmotionFromLabel(String(emoLabel));
      setEmotion(parsed);
      setEmotionLockUntil(Date.now() + 45000);
    }
  };
  
  // Persona & Session State
  const [persona, setPersona] = useState<any>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [lifeStatus, setLifeStatus] = useState<any>(null);

  // Breathing System
  const breathingState = useBreathingSystem({ 
    stats, 
    emotion, 
    emotionMix,
    lifeStatus,
    isThinking: isTyping 
  });
  const { colors: currentColors, speed: breathingSpeed, pattern: breathingPattern } = breathingState;

  // Audio State
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>("");
  const [currentModel, setCurrentModel] = useState<string>('cloud');

  useMobileInitialData({
    setVoices,
    setSelectedVoiceId,
    setPersona,
    setLifeStatus,
  });

  const { studyMode, toggleStudyMode: handleToggleStudyMode } = useMobileStudyMode({
    setMessages,
  });

  const { playingMsgId, loadingAudio, playTTS, toggleTTS } = useMobileTTS({
    messagesRef,
    setMessages,
    selectedVoiceId,
    emotion,
    normalizeAudioSrc,
  });


  // Sync currentModel UI state with actual selectedModel
  useEffect(() => {
    if (selectedModel) {
        // Robust check for cloud vs local using id, category, or path
        const id = String(selectedModel.id);
        const isCloud = id.startsWith('cloud:') || 
                        selectedModel.category === 'cloud' || 
                        (typeof selectedModel.path === 'string' && selectedModel.path.startsWith('cloud:'));
        
        // Only update if different to avoid cycles
        const newModelType = isCloud ? 'cloud' : 'local';
        if (currentModel !== newModelType) {
            setCurrentModel(newModelType);
        }
    }
  }, [selectedModel, currentModel]);

  const resolveMessageTimestamp = (value?: any) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return Date.now();
    return num < 1e12 ? num * 1000 : num;
  };

  const { loadSessionHistory } = useMobileSessionHistory({
    currentSessionId,
    setCurrentSessionId,
    setMessages,
    setEmotion,
    normalizeAudioSrc,
    resolveMessageTimestamp,
    stripEmotionMarkers,
    smartSegmentText,
    isRetractionSegment,
    segmentByRetractionOnly,
    resolveEmotionFromLabel,
  });

  const { handleSend, handleSendWithText, sendWithText } = useMobileMessageActions({
    input,
    setInput,
    isTyping,
    setIsTyping,
    setShowTypingIndicator,
    currentSessionId,
    setCurrentSessionId,
    selectedModel,
    loadSessionHistory,
    setMessages,
    setEmotionMix,
    setEmotion,
    setEmotionLockUntil,
    autoTtsEnabled,
    normalizeAudioSrc,
    playTTS,
    stripEmotionMarkers,
    inferEmotionFromText,
    resolveEmotionFromLabel,
    autoTtsHandledRef,
    stripSystemTags,
  });

  const { handleUpload } = useMobileFileUpload({
    setMessages,
  });

  const { handleCreateSession, handleClearHistory, handleDeleteMessage } = useMobileSessionActions({
    storageKey: STORAGE_KEY,
    messages,
    currentSessionId,
    setMessages,
    setCurrentSessionId,
    setShowSidebar,
    setConfirmDialog,
  });

  const { scheduleAutoSend } = useMobileDeepLink({
    setActiveTab,
    setInput,
    handleSendWithText: sendWithText,
  });

  const { onMessage } = useMobileWebSocketHandler({
    setCurrentModel,
    triggerHaptic,
    handleAutonomousVibration,
    setMessages,
    setLifeStatus,
    setPersona,
    applyEmotionFromText,
    setIsTyping,
    setShowTypingIndicator,
    autoTtsEnabled,
    playTTS,
    autoTtsHandledRef,
    stripEmotionMarkers,
    stripSystemTags,
    resolveMessageTimestamp,
    studyMode,
  });

  const { sendMessage } = useWebSocket({
    onMessage,
  });

  // Effects
  useEffect(() => {
    if ('Notification' in window) {
      Notification.requestPermission();
    }
    (window as any).aveline = {
      autoSend: (text: string) => {
        scheduleAutoSend(text);
      }
    };
    return () => {
      delete (window as any).aveline;
    };
  }, [scheduleAutoSend]);

  useEffect(() => {
    const native = (window as any)?.aveline_native;
    setHasNative(!!native);
    if (native?.isResidentModeEnabled) {
      try {
        setResidentEnabled(!!native.isResidentModeEnabled());
      } catch {
        setResidentEnabled(false);
      }
    }
  }, [showSettings]);



  // Proactive Greeting
  useEffect(() => {
    const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
    if (!hasGreeted && messages.length === 0) {
      sessionStorage.setItem('aveline_has_greeted', 'pending');
      api.getGreeting(undefined, { silent: true }).then((res: any) => {
        if (res?.status === 'success' && res.greeting) {
           const greetingMsg: Message = { 
             id: Date.now(), 
             isUser: false, 
             text: res.greeting 
           };
           setMessages(prev => {
             // Prevent duplicates
             const last = prev[prev.length - 1];
             if (last && !last.isUser && last.text === res.greeting) {
               return prev;
             }
             return [...prev, greetingMsg];
           });
           sessionStorage.setItem('aveline_has_greeted', 'true');
        } else {
           sessionStorage.removeItem('aveline_has_greeted');
        }
      }).catch(() => {
           sessionStorage.removeItem('aveline_has_greeted');
      });
    }
  }, []);

  // Session Management Logic
  useEffect(() => {
    const last = localStorage.getItem('aveline_last_session_id');
    if (last) setCurrentSessionId(last);
  }, []);


  const handleSwitchModel = (type: 'cloud' | 'local') => {
    sendMessage({ type: 'mobile_switch_model', model: type });
    setCurrentModel(type);
    
    // [Fix] Update selectedModel for HTTP requests (api.sendMessage uses selectedModel.id)
    if (models && models.length > 0) {
        let targetModel = null;
        if (type === 'local') {
            // Find first available local model
            targetModel = models.find(m => !String(m.id).startsWith('cloud:') && m.category !== 'cloud');
        } else {
            // Find first available cloud model
            targetModel = models.find(m => String(m.id).startsWith('cloud:') || m.category === 'cloud');
        }
        
        if (targetModel) {
            setSelectedModel(targetModel);
            console.log(`[Mobile] Switched HTTP model to: ${targetModel.id}`);
        }
    }

    triggerHaptic(ImpactStyle.Medium);
  };

  const handleUpdateSettings = (settings: { tts?: { provider: string; model: string } }) => {
    sendMessage({ type: 'update_settings', settings });
  };

  const handleSaveUrl = () => {
    const url = serverUrl.trim();
    if (!url) return;
    
    // 1. Save to LocalStorage (for Axios/Fetch)
    localStorage.setItem('AVELINE_API_URL', url);
    
    // 2. Sync to Native (for background tasks/native requests)
    if ((window as any).aveline_native?.setBackendUrl) {
        (window as any).aveline_native.setBackendUrl(url);
    }
    
    // 3. Reload to apply changes
    window.location.reload();
  };

  const handleTestConnection = async () => {
    const url = serverUrl.trim();
    if (!url) {
      setTestStatus('error');
      setTimeout(() => setTestStatus('idle'), 3000);
      return;
    }
    setTestStatus('testing');
    try {
      const res = await fetch(`${url.replace(/\/$/, '')}/health`, { method: 'GET' });
      if (res.ok) {
        setTestStatus('success');
      } else {
        setTestStatus('error');
      }
    } catch {
      setTestStatus('error');
    }
    setTimeout(() => setTestStatus('idle'), 3000);
  };

  const handleToggleResident = () => {
    const native = (window as any)?.aveline_native;
    if (!native) return;

    const next = !residentEnabled;
    try {
      if (next) {
        native.startResidentMode?.();
      } else {
        native.stopResidentMode?.();
      }
    } catch {}
    setResidentEnabled(next);
  };

  const handleOpenNativeSettings = () => {
    const native = (window as any)?.aveline_native;
    if (native?.openNativeSettingsPage) {
      native.openNativeSettingsPage();
      return;
    }
    native?.openQuickSettings?.();
  };

  const handleRequestHealthPermissions = () => {
    (window as any)?.aveline_native?.requestHealthPermissions?.();
  };

  const handleOpenUsageSettings = () => {
    (window as any)?.aveline_native?.openUsageAccessSettings?.();
  };

  const handleOpenNotificationSettings = () => {
    (window as any)?.aveline_native?.openNotificationAccessSettings?.();
  };

  // Mobile Navigation Items
  const navItems = [
    { id: 'Chat', icon: <MessageSquare size={20} />, label: 'Chat' },
    { id: 'Status', icon: <Activity size={20} />, label: 'Status' },
    { id: 'DailyData', icon: <Calendar size={20} />, label: 'Daily' },
    { id: 'Memory', icon: <Database size={20} />, label: 'Memory' },
    { id: 'Study', icon: <BookOpen size={20} />, label: 'Study' },
    { id: 'Persona', icon: <User size={20} />, label: 'Persona' },
    { id: 'Shop', icon: <Utensils size={20} />, label: 'Food' },
    { id: 'Plugins', icon: <LayoutGrid size={20} />, label: 'Plugins' },
  ];

  return (
    <ErrorBoundary>
      <div 
        className="fixed left-0 top-0 w-full flex flex-col text-zinc-100 overflow-hidden bg-zinc-950"
        style={{ height: viewportHeight ? `${viewportHeight}px` : 'var(--app-height, 100dvh)' }}
        onTouchStart={onAppTouchStart}
        onTouchMove={onAppTouchMove}
        onTouchEnd={onAppTouchEnd}
        onTouchCancel={onAppTouchEnd}
      >
        {/* Background Breathing */}
        <div className="absolute inset-0 z-0 opacity-100 pointer-events-none">
            <BreathingBackground state={{ ...breathingState, speed: breathingSpeed / breathingRate }} />
        </div>
        
        <MobileSidebar
          show={showSidebar}
          connected={connected}
          activeTab={activeTab}
          navItems={navItems}
          currentSessionId={currentSessionId}
          onClose={() => setShowSidebar(false)}
          onOpenSettings={() => {
            setShowSettings(true);
            setShowSidebar(false);
            triggerHaptic();
          }}
          onNavigate={(id) => {
            setActiveTab(id);
            setShowSidebar(false);
            triggerHaptic();
          }}
          onSelectSession={(id) => {
            setMessages([]);
            setCurrentSessionId(id);
            setShowSidebar(false);
          }}
          onCreateSession={handleCreateSession}
          onRequestConfirm={(opts) => setConfirmDialog({
            ...opts,
            isOpen: true,
            onConfirm: async () => {
              if (opts.onConfirm) await opts.onConfirm();
              setConfirmDialog(prev => ({ ...prev, isOpen: false }));
            }
          })}
          triggerHaptic={triggerHaptic}
          onTouchStart={onSidebarTouchStart}
          onTouchMove={onSidebarTouchMove}
          onTouchEnd={onSidebarTouchEnd}
        />

        <MobileSettingsOverlay
          show={showSettings}
          serverUrl={serverUrl}
          onServerUrlChange={setServerUrl}
          onClose={() => { setShowSettings(false); triggerHaptic(); }}
          onSaveUrl={handleSaveUrl}
          onTestConnection={handleTestConnection}
          testStatus={testStatus}
          hasNative={hasNative}
          residentEnabled={residentEnabled}
          onToggleResident={handleToggleResident}
          onOpenNativeSettings={handleOpenNativeSettings}
          onOpenUsageSettings={handleOpenUsageSettings}
          onOpenNotificationSettings={handleOpenNotificationSettings}
          onRequestHealthPermissions={handleRequestHealthPermissions}
          voices={voices}
          selectedVoiceId={selectedVoiceId}
          onVoiceChange={setSelectedVoiceId}
          responseLength={responseLength}
          onResponseLengthChange={setResponseLength}
          onClearHistory={handleClearHistory}
          triggerHaptic={triggerHaptic}
        />

        {/* Main Content Area */}
        <div className="flex-1 overflow-hidden relative z-10 flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
           <AnimatePresence mode="wait">
             <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="flex-1 w-full h-full flex flex-col overflow-hidden"
             >
               {activeTab === 'Chat' && (
                   <>
                    <div className="flex-1 overflow-hidden relative flex flex-col">
                        <ChatPanel 
                            messages={messages}
                            isTyping={isTyping}
                            showTypingIndicator={showTypingIndicator}
                            playingMsgId={playingMsgId}
                            loadingAudio={loadingAudio}
                            currentColors={currentColors}
                            replyDisplayMode={replyDisplayMode}
                            onToggleTTS={toggleTTS}
                            onDelete={handleDeleteMessage}
                            onSuggestionClick={(text: string) => handleSendWithText(text)}
                            studyMode={studyMode}
                        />
                    </div>
                    <div className="flex-none pb-safe-bottom bg-zinc-950/50 backdrop-blur-xl border-t border-white/5">
                        <InputArea 
                            input={input}
                            setInput={setInput}
                            onSend={handleSend}
                            isTyping={isTyping}
                            voices={voices}
                            selectedVoiceId={selectedVoiceId}
                            setSelectedVoiceId={setSelectedVoiceId}
                            onUpload={handleUpload}
                            isMobile={true}
                        />
                    </div>
                   </>
               )}

               {activeTab === 'Memory' && (
                   <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                       <MemoryPanel 
                            memoryData={messages}
                            onClearHistory={handleClearHistory}
                       />
                   </div>
               )}

               {activeTab === 'DailyData' && (
                   <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                       <DailyDataPanel />
                   </div>
               )}

               {activeTab === 'Study' && (
                   <div className="flex-1 overflow-hidden relative flex flex-col p-2">
                       <StudyPanel />
                   </div>
               )}

               {activeTab === 'Persona' && (
                   <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                       <PersonaPanel 
                            persona={persona}
                            onPersonaChange={setPersona}
                       />
                   </div>
               )}

               {activeTab === 'Plugins' && (
                   <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                       <PluginsPanel 
                            models={models}
                            selectedModel={selectedModel}
                            setSelectedModel={setSelectedModel}
                            responseLength={responseLength}
                            setResponseLength={setResponseLength}
                            imageModel={imageModel}
                            breathingRate={breathingRate}
                            setBreathingRate={setBreathingRate}
                            setEmotion={setEmotion}
                            setEmotionMix={setEmotionMix}
                            emotion={emotion}
                            currentModel={currentModel}
                            onSwitchModel={handleSwitchModel}
                            onUpdateSettings={handleUpdateSettings}
                       />
                   </div>
               )}

                {activeTab === 'Status' && (
                  <div className="flex-1 overflow-y-auto px-4 pt-4 pb-6 space-y-4 custom-scrollbar">
                       <EmotionWidget 
                           emotion={emotion} 
                           sidebarOpen={true} 
                           lifeStatus={lifeStatus} 
                           colors={currentColors}
                           speed={breathingSpeed}
                           pattern={breathingPattern}
                       />
                      <MobileStatusPanel
                        connected={connected}
                        clock={clock}
                        stats={stats}
                        lifeStatus={lifeStatus}
                        colors={currentColors}
                        emotion={emotion}
                      />
                   </div>
               )}

               {activeTab === 'Shop' && (
                   <div className="flex-1 overflow-hidden relative flex flex-col p-2 pt-16">
                      <ShopPanel platform="mobile" />
                   </div>
               )}
             </motion.div>
           </AnimatePresence>
        </div>
      </div>
      
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
      />
    </ErrorBoundary>
  );
}
