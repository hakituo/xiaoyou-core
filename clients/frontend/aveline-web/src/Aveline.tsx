import React, { useState, useEffect, useRef, useMemo, Suspense } from 'react';
import { Settings, Cpu, Ghost, Trash2, Check, ChevronRight, Clock, ScanFace } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from './api/apiService';
import { Message } from './types';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { SIDEBAR_ITEMS } from './utils/constants';
import { inferEmotionFromText, resolveEmotionFromLabel, stripEmotionMarkers, stripSystemTags, ttsParamsForEmotion } from './utils/emotion';
import { smartSegmentText, isRetractionSegment, tokenizeStreamingText } from './utils/text';
import { useStatus } from './hooks/useStatus';
import { useModels } from './hooks/useModels';
import { useWebSocket } from './hooks/useWebSocket';
import { useImageModels } from './hooks/useImageModels';
import { useAvelineRealtime } from './hooks/useAvelineRealtime';
import { useAvelineChat } from './hooks/useAvelineChat';
import { useAvelineVoice } from './hooks/useAvelineVoice';
import { useAvelineStore } from './store/useStore';
import { NativeService, isNative } from './utils/nativeService';
import { App } from '@capacitor/app';

import SidebarButton from './components/SidebarButton';
import DesktopPet from './components/DesktopPet';
import DeviceWidget from './components/DeviceWidget';
import ErrorBoundary from './components/ErrorBoundary';
import ChatPanel from './components/ChatPanel';
import InputArea from './components/InputArea';
import ImageModelSelector from './components/ImageModelSelector';
import { useBreathingSystem, BreathingBackground } from './systems/BreathingSystem';
import EmotionWidget from './components/EmotionWidget';
import StatusPanel from './components/StatusPanel';
import LoginModal from './components/LoginModal';
import SettingsView from './components/SettingsView';
import { ConfirmDialog } from './components/ui/ConfirmDialog';

// Lazy loaded components for better performance
const PluginsPanel = React.lazy(() => import('./components/PluginsPanel'));
const MemoryPanel = React.lazy(() => import('./components/MemoryPanel'));
const ShopPanel = React.lazy(() => import('./components/ShopPanel'));
const PersonaPanel = React.lazy(() => import('./components/PersonaPanel'));
const StudyPanel = React.lazy(() => import('./components/StudyPanel'));
const DailyDataPanel = React.lazy(() => import('./components/DailyDataPanel'));
const CirclePanel = React.lazy(() => import('./components/CirclePanel'));
const SessionList = React.lazy(() => import('./components/SessionList').then(module => ({ default: module.SessionList })));

const STORAGE_KEY = 'aveline_chat_history_v2';
const HISTORY_PAGE_SIZE = 30;

export default function Aveline() {
  // Hooks
  const { clock } = useStatus();
  
  // Zustand Store
  const { 
    messages, setMessages, addMessage,
    lifeStatus, setLifeStatus,
    persona, setPersona,
    emotion, setEmotion, 
    emotionMix, setEmotionMix,
    emotionLockUntil, setEmotionLockUntil,
    stats, updateStats,
    isTyping, setIsTyping,
    breathingRate, setBreathingRate,
    autoTtsEnabled,
    replyDisplayMode,
    ttsTextLanguage,
    ttsPromptLanguage,
    ttsSpeed,
    ttsPitch,
    referenceAudio,
    setStudyMode
  } = useAvelineStore();

  // Breathing System
  const breathingState = useBreathingSystem({ 
    stats, 
    emotion, 
    emotionMix,
    lifeStatus,
    isThinking: isTyping 
  });
  const { colors: currentColors, speed: breathingSpeed, pattern: breathingPattern } = breathingState;
  
  const { models, selectedModel, setSelectedModel } = useModels();
  const llmModels = useMemo(() => models.filter(m => m.type === 'llm' || m.type === 'dashscope' || m.type === 'openai' || m.type === 'siliconflow'), [models]);
  // App State - [MODIFIED] Single Session Mode
  // Use "default_user" as the default session ID to match backend Active Care target and Master QQ session
  const [currentSessionId, setCurrentSessionId] = useState<string | null>("default_user");

  // Allow overriding session ID via URL parameter (e.g. ?session_id=private_123456)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get('session_id');
    if (sid && sid.trim()) {
      console.log(`[Aveline] Switching to session from URL: ${sid}`);
      setCurrentSessionId(sid.trim());
    }
  }, []);

  const [showModelSwitcher, setShowModelSwitcher] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [hasNativeQuickSettings, setHasNativeQuickSettings] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    onCancel: () => void;
    confirmText?: string;
    cancelText?: string;
    type?: 'danger' | 'info' | 'warning';
    showCancel?: boolean;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {},
    onCancel: () => {},
    type: 'danger'
  });
  const nativeMetricsRef = useRef<any>(null);

  // Refs for stable access in event listeners
  const uiStateRef = useRef({
    showModelSwitcher,
    showClearConfirm,
    isSettingsOpen
  });


  useEffect(() => {
    uiStateRef.current = {
      showModelSwitcher,
      showClearConfirm,
      isSettingsOpen
    };
  }, [showModelSwitcher, showClearConfirm, isSettingsOpen]);

  useEffect(() => {
    api.getPreferences().then(res => {
      if (res?.data?.mode === 'study') {
        setStudyMode(true);
      } else {
        setStudyMode(false);
      }
    }).catch(e => console.error("Failed to load preferences", e));
  }, []);

  useEffect(() => {
    // 注册原生指标回调 (Direct Bridge)
    (window as any).onNativeMetrics = (metrics: any) => {
      console.log('Received native metrics:', metrics);
      nativeMetricsRef.current = metrics;
    };

    if (isNative) {
      NativeService.initStatusBar();
      NativeService.initKeyboard();
      NativeService.requestPermissions();
    }

    return () => {
      delete (window as any).onNativeMetrics;
    };
  }, []);

  useEffect(() => {
    if (showModelSwitcher) {
      const handleGlobalClick = () => {
        setShowModelSwitcher(false);
      };
      window.addEventListener('click', handleGlobalClick);
      return () => window.removeEventListener('click', handleGlobalClick);
    }
  }, [showModelSwitcher]);

  const imageModel = useImageModels();

  // ===== 解耦后的业务 hook（voice / realtime / chat）=====
  const voice = useAvelineVoice();
  const realtime = useAvelineRealtime({
    currentSessionId,
    playTTS: voice.playTTS,
    onAuthError: () => {
      setIsLoginModalOpen(true);
      setLoginError('鉴权失败，请输入正确的访问令牌');
    },
  });
  const chat = useAvelineChat({
    sendMessage: realtime.sendMessage,
    isConnected: realtime.isConnected,
    currentSessionId,
    setCurrentSessionId,
    setShowTypingIndicator: realtime.setShowTypingIndicator,
    selectedModel,
  });

  // 解构出 render 所需的同名变量，保持下方 JSX 不变
  const {
    voices, selectedVoiceId, setSelectedVoiceId, playingMsgId, setPlayingMsgId,
    loadingAudio, audioRef, playTTS, toggleTTS, readFileAsDataUrl,
  } = voice;
  const {
    isConnected, sendMessage, showTypingIndicator, setShowTypingIndicator,
    connectionError, lastMessage, actorLifeStates, actorRelationships,
    lingRelationshipScore, avelineThread, lingThread,
  } = realtime;
  const {
    input, setInput, responseLength, setResponseLength, groupMode, setGroupMode,
    historyLoading, historyHasMore, historyOldestTs, regeneratingMsgId,
    loadSessionHistory, handleLoadMoreHistory, handleSend, handleRegenerate,
    handleDeleteMessage, handleUpload,
  } = chat;

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
        // 如果是撤回样式，去掉首尾括号，保持与流式输出一致
        const finalText = isRetract ? segment.replace(/^[\(（]|[\)）]$/g, '') : segment;
        return {
          ...item,
          id: index === baseIndex ? baseId : `${baseId}-${index}`,
          text: finalText,
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


  // 手机端状态主动上报 (电量、网络、应用使用情况等)
  useEffect(() => {
    if (!isNative) return;

    const reportStatus = async () => {
      try {
        const battery = await NativeService.getBatteryInfo();
        const network = await NativeService.getNetworkStatus();
        const device = await NativeService.getDeviceInfo();
        const nativeMetrics = nativeMetricsRef.current || {};
        
        // 发送 device_status 用于生理/环境感知
        sendMessage({
          type: 'device_status',
          source: 'android_native',
          metrics: {
            battery_level: battery?.batteryLevel,
            is_charging: battery?.isCharging,
            network_type: network?.connectionType,
            // 使用原生采集的真实数据
            usage_stats: nativeMetrics.usage_stats || [], 
            steps_today: nativeMetrics.steps || 0,
            activity: nativeMetrics.activity || "Unknown"
          },
          data: {
            battery,
            network,
            device: {
              platform: device?.platform,
              osVersion: device?.osVersion,
              model: device?.model
            }
          }
        });
      } catch (e) {
        console.error('Failed to report device status', e);
      }
    };

    // 连接后立即上报一次
    const timer = setTimeout(reportStatus, 5000);
    
    // 每 5 分钟上报一次
    const interval = setInterval(reportStatus, 5 * 60 * 1000);

    // Sync Backend URL to Native on launch
    const savedUrl = localStorage.getItem('AVELINE_API_URL');
    if (savedUrl && (window as any).aveline_native?.setBackendUrl) {
        (window as any).aveline_native.setBackendUrl(savedUrl);
    }

    // Health Data Sync Loop (Every 10 minutes)
    const healthInterval = setInterval(() => {
        if ((window as any).aveline_native?.fetchHealthData) {
            console.log("Triggering native health data fetch...");
            (window as any).aveline_native.fetchHealthData();
        }
    }, 10 * 60 * 1000);
    // Trigger once on launch after a delay
    setTimeout(() => {
        if ((window as any).aveline_native?.fetchHealthData) {
            (window as any).aveline_native.fetchHealthData();
        }
    }, 8000);

    return () => {
      clearTimeout(timer);
      clearInterval(interval);
      clearInterval(healthInterval);
    };
  }, [isNative, sendMessage]);

  // UI State
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showPet, setShowPet] = useState(false);
  const [activeTab, setActiveTab] = useState('Chat');
  // lifeStatus moved up for dependency resolution


  const openQuickSettings = () => {
    const native = (window as any)?.aveline_native;
    if (native && typeof native.openQuickSettings === 'function') {
      native.openQuickSettings();
    }
  };
  
  // Proactive Chat State
  const lastInteractionRef = useRef(Date.now());
  const hasProactedRef = useRef(false);

  // Check if we are in Pet Mode (via URL hash)
  useEffect(() => {
    const checkPetMode = () => {
      // Use includes for looser matching
      if (window.location.hash.includes('pet-mode')) {
        setShowPet(true);
        // In Pet Mode, we might want to hide the rest of the UI visually or just rely on the DesktopPet component overlaying everything.
        // Since DesktopPet is fixed/z-50, we just need to make sure the background is transparent.
        document.body.style.backgroundColor = 'transparent';
        document.documentElement.style.backgroundColor = 'transparent';
        document.body.style.overflow = 'hidden'; // Prevent scrollbars
      }
    };

    checkPetMode();
    window.addEventListener('hashchange', checkPetMode);
    
    // Listen for IPC messages from Electron Main Process
    if (typeof window !== 'undefined' && (window as any).require) {
       const { ipcRenderer } = (window as any).require('electron');
       ipcRenderer.on('switch-to-pet', () => {
         // This might not be needed if we use separate windows, but good for sync
       });
    }

    // Expose Pet Mode API to JS for Pywebview interaction
    (window as any).togglePetMode = () => {
        const isElectron = navigator.userAgent.toLowerCase().includes('electron');
        if (isElectron && (window as any).require) {
            const { ipcRenderer } = (window as any).require('electron');
            ipcRenderer.send('open-pet-mode');
            return;
        }

        if ((window as any).pywebview?.api) {
            (window as any).pywebview.api.switch_to_pet_mode();
            return;
        }

        window.location.hash = 'pet-mode';
    };
    
    (window as any).exitPetMode = () => {
        const isElectron = navigator.userAgent.toLowerCase().includes('electron');
        if (isElectron && (window as any).require) {
            const { ipcRenderer } = (window as any).require('electron');
            ipcRenderer.send('open-main-window');
            return;
        }

        if ((window as any).pywebview?.api) {
            (window as any).pywebview.api.switch_to_main_mode();
            return;
        }

        window.location.hash = '';
        window.location.reload();
    };

    return () => window.removeEventListener('hashchange', checkPetMode);
  }, []);

  useEffect(() => {
    setHasNativeQuickSettings(typeof (window as any)?.aveline_native?.openQuickSettings === 'function');
  }, []);

  // Breathing System (Moved up)
  
  // Persona State (Moved up)


  // Effects
  // Reset idle timer on user interaction
  const resetIdleTimer = () => {
    lastInteractionRef.current = Date.now();
    hasProactedRef.current = false;
  };


  const handleLogin = (password: string) => {
    localStorage.setItem('XIAOYOU_ACCESS_TOKEN', password);
    setIsLoginModalOpen(false);
    setLoginError('');
    // 强制刷新页面或触发重新连接逻辑
    window.location.reload();
  };

  const handleCreateSession = async () => {
      // Check for empty session reuse
      const hasUserMessages = messages.some(m => m.isUser);
      if (currentSessionId && !hasUserMessages) {
          // Current session is empty, reuse it instead of creating new one
          setMessages([{ id: Date.now(), isUser: false, text: "新话题已开启" }]);
          return;
      }

      try {
          const res = await api.createSession();
          if (res.status === 'success') {
              setCurrentSessionId(res.data.id);
              setMessages([{ id: Date.now(), isUser: false, text: "新话题已开启" }]);
          }
      } catch (e) {
          console.error(e);
          throw e; // Propagate error to caller
      }
  };

  // Handlers
  const handleClearHistory = () => {
    setShowClearConfirm(true);
  };

  const confirmClearHistory = async (mode: 'all' | 'short') => {
    setShowClearConfirm(false);
    if (currentSessionId) {
      try {
        await api.clearHistory(currentSessionId, mode);
        const msgText = mode === 'all' ? "所有历史记录已清空。" : "短期记忆已清空，长期记忆保留。";
        setMessages([{ id: Date.now(), isUser: false, text: msgText, timestamp: Date.now() }]);
      } catch (e) {
        console.error("Failed to clear history", e);
        setConfirmDialog({
          isOpen: true,
          title: '错误',
          message: '清空历史记录失败，请检查后端连接。',
          type: 'danger',
          showCancel: false,
          confirmText: '确定',
          onConfirm: () => {},
          onCancel: () => {}
        });
      }
    }
  };

  useEffect(() => {
    // Disabled proactive idle check to ensure consistency with mobile and avoid "watery" messages
    /*
    const checkIdle = async () => {
      const now = Date.now();
      const IDLE_THRESHOLD = 60 * 1000; // 60s idle threshold
      
      if (now - lastInteractionRef.current > IDLE_THRESHOLD && !hasProactedRef.current && messages.length > 0 && !isTyping) {
        // Don't trigger if last message is error
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && !lastMsg.isUser && (lastMsg.text.includes("Error") || lastMsg.text.includes("..."))) return;

        hasProactedRef.current = true;
        
        try {
           const res = await api.sendMessage(`[SYSTEM: User has been idle for >1 min. Please initiate a new topic or ask a caring question naturally. Do not mention you are an AI or this is a system prompt. Be brief. CURRENT_TIME: ${Date.now()}]`, {
             modelName: selectedModel?.id
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
    */
  }, [messages, selectedModel, isTyping]);

  // Function to update settings via WebSocket
  const handleUpdateSettings = (settings: any) => {
      sendMessage({
          type: 'update_settings',
          settings
      });
  };

  const handleSwitchPersona = async (filename: string) => {
    try {
        await api.switchPersona(filename);
        window.location.reload();
    } catch (e) {
        console.error("Failed to switch persona", e);
    }
  };

  // Handle calling feature
  const handleCall = () => {
      // Send start_call message via WebSocket
      sendMessage({
          type: 'start_call',
          timestamp: Date.now()
      });
      
      // Add a system message
      setMessages(prev => [...prev, {
          id: Date.now(),
          isUser: false,
          text: "正在建立通话连接...",
          messageType: 'system'
      }]);
  };

  if (showPet && window.location.hash.includes('pet-mode')) {
    return (
      <>
          <DesktopPet 
            emotion={emotion} 
            isTyping={isTyping} 
            lastMessage={messages[messages.length - 1] || null} 
            lifeStatus={lifeStatus}
            onUpdateSettings={handleUpdateSettings}
            onCall={handleCall}
            onSendMessage={(text) => handleSend(text)}
            onPlayTTS={(text) => playTTS(text, messages[messages.length - 1]?.id || Date.now(), emotion)}
            onClose={() => {
              // If we are in web mode, just exit pet mode
              if (!window.location.hash.includes('pet-mode')) {
                  setShowPet(false);
              } else {
                  // If in Electron pet mode, close the window or switch
                  if (navigator.userAgent.toLowerCase().includes('electron')) {
                      // Switch to main window
                      const { ipcRenderer } = (window as any).require('electron');
                      ipcRenderer.send('open-main-window');
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
      className={`min-h-screen text-white font-sans selection:bg-white/20 overflow-hidden relative transition-colors duration-1000 ${showPet ? '' : 'main-app-container'}`}
      style={{ background: showPet ? 'transparent' : currentColors[2] }}
    >
      {/* Ambient Background */}
      {!showPet && <BreathingBackground state={{ ...breathingState, speed: breathingSpeed / breathingRate }} />}

      {/* Main Layout */}
      {showPet ? (
         <DesktopPet 
           emotion={emotion} 
           isTyping={isTyping} 
           lastMessage={messages[messages.length - 1]} 
           lifeStatus={lifeStatus}
           onUpdateSettings={handleUpdateSettings}
           onCall={handleCall}
           onSendMessage={(text) => handleSend(text)}
           onPlayTTS={(text) => playTTS(text, messages[messages.length - 1]?.id || Date.now(), emotion)}
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
             onClick={() => setSidebarOpen(!sidebarOpen)}
             className={`flex flex-col gap-1.5 transition-all duration-300 ease-out border-r border-white/5 bg-black/20 backdrop-blur-xl relative z-30 cursor-pointer ${sidebarOpen ? 'w-64' : 'w-20'}`}
          >
             <div className="flex-1 flex flex-col min-h-0 px-2 pt-4">
                {/* Logo Area - Aligned with Header (h-16) */}
                <div className="pointer-events-none h-16 flex items-center shrink-0 mb-20">
                  <EmotionWidget 
                    emotion={emotion} 
                    emotionMix={emotionMix}
                    sidebarOpen={sidebarOpen} 
                    lifeStatus={lifeStatus} 
                    colors={currentColors}
                    speed={breathingSpeed}
                    pattern={breathingPattern}
                  />
                </div>
                
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

                {/* [MODIFIED] Removed SessionList - Single Session Mode */}
             </div>

             <div className="mt-auto pt-4 border-t border-white/5 space-y-1 px-3 flex-shrink-0 pb-4">
                {/* Settings Button */}
                <SidebarButton 
                   item={{ id: 'Settings', icon: <Settings size={20} />, label: 'Settings', title: '设置 (Settings)' }}
                   isActive={isSettingsOpen}
                   isExpanded={sidebarOpen}
                   onClick={() => setIsSettingsOpen(true)}
                />

                {/* Pet Mode */}
                <SidebarButton 
                  item={{ id: 'PetMode', icon: <Ghost size={20} />, label: 'Pet Mode', title: 'Desktop Pet Mode' }}
                  isActive={showPet}
                  isExpanded={sidebarOpen}
                  onClick={() => {
                    if (navigator.userAgent.toLowerCase().includes('electron')) {
                      const { ipcRenderer } = (window as any).require('electron');
                      ipcRenderer.send('open-pet-mode');
                    } else {
                      setShowPet(true);
                    }
                  }} 
                />

                <div className="relative mt-2">
                  <AnimatePresence>
                    {showModelSwitcher && (
                      <motion.div
                        initial={{ opacity: 0, scale: 0.95, ...(sidebarOpen ? { y: 10 } : { x: 10 }) }}
                        animate={{ opacity: 1, scale: 1, ...(sidebarOpen ? { y: 0 } : { x: 0 }) }}
                        exit={{ opacity: 0, scale: 0.95, ...(sidebarOpen ? { y: 10 } : { x: 10 }) }}
                        className={`fixed z-[9999] bg-zinc-950 border border-white/10 rounded-xl shadow-[0_20px_50px_rgba(0,0,0,0.8)] p-2 overflow-hidden w-56 pointer-events-auto`}
                        style={{
                          left: sidebarOpen ? '16px' : '72px',
                          bottom: '60px' // ModelSwitcher 按钮大概在底部 60px 位置
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="px-2 py-1.5 border-b border-white/5 mb-1 text-left">
                          <span className="text-[10px] text-white/40 uppercase tracking-widest font-bold">Select Model</span>
                        </div>
                        <div className="max-h-64 overflow-y-auto custom-scrollbar space-y-0.5">
                          {llmModels.map(m => (
                            <button
                              key={m.id}
                              onClick={() => {
                                setSelectedModel(m);
                                setShowModelSwitcher(false);
                              }}
                              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                                selectedModel?.id === m.id 
                                  ? 'bg-emerald-500/10 text-emerald-400' 
                                  : 'text-white/60 hover:bg-white/5 hover:text-white'
                              }`}
                            >
                              <div className="flex flex-col items-start text-left">
                                <span>{m.name}</span>
                                <span className="text-[9px] opacity-40 font-mono">{m.type.toUpperCase()}</span>
                              </div>
                              {selectedModel?.id === m.id && <Check size={12} />}
                            </button>
                          ))}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <div 
                      className={`rounded-xl border transition-all duration-300 cursor-pointer flex items-center group overflow-hidden h-12 w-full px-4 ${
                        showModelSwitcher ? 'bg-white/10 border-white/20' : 'bg-transparent border-transparent hover:bg-white/5'
                      }`}
                      onClick={(e: React.MouseEvent) => { 
                        e.stopPropagation(); 
                        setShowModelSwitcher(!showModelSwitcher);
                      }}
                  >
                    <div className="flex items-center min-w-0 gap-4">
                       <div className="w-8 h-8 flex items-center justify-center shrink-0">
                         <Cpu 
                           size={18} 
                           className={`transition-all duration-300 ${
                             showModelSwitcher ? 'text-emerald-400 scale-110' : 'text-white/40 group-hover:text-emerald-400'
                           }`} 
                         />
                       </div>
                       
                       <div className={`flex flex-col transition-all duration-300 ${sidebarOpen ? 'opacity-100' : 'opacity-0 w-0'}`}>
                        <span className="text-[10px] text-white/40 uppercase tracking-widest leading-none mb-1 transition-colors duration-300 whitespace-nowrap">Active Model</span>
                        <span className="text-xs font-medium text-white truncate transition-colors duration-300 whitespace-nowrap">
                          {selectedModel?.name || 'Auto'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
           </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 flex flex-col relative overflow-hidden z-20">
           {/* Header */}
           <div className="h-16 border-b border-white/5 bg-black/10 backdrop-blur-sm flex items-center justify-between px-8 flex-shrink-0">
              <div className="group flex items-center gap-2 py-1.5 cursor-default">
                <Clock size={14} className="text-white/30 group-hover:text-amber-400 transition-colors duration-300" />
                <div className="font-mono text-xs text-white/40 group-hover:text-white/80 tracking-widest transition-colors duration-300">
                  {clock}
                </div>
              </div>
              <div className="flex items-center gap-4">
                 <DeviceWidget 
                   cpu={stats.cpu} 
                   gpu={stats.gpu} 
                   memory={stats.memory} 
                   colors={currentColors} 
                   emotion={emotion} 
                 />
                 {hasNativeQuickSettings && (
                   <button
                     onClick={openQuickSettings}
                     className="w-10 h-10 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white/10 transition-colors"
                     title="Settings"
                   >
                     <Settings size={18} className="text-white/60" />
                   </button>
                 )}
              </div>
           </div>

           {/* Tab Content */}
           {activeTab === 'Chat' && (
            <>
              <ChatPanel 
                messages={messages} 
                isTyping={isTyping} 
                showTypingIndicator={showTypingIndicator}
                playingMsgId={playingMsgId} 
                loadingAudio={loadingAudio} 
                currentColors={currentColors}
                replyDisplayMode={replyDisplayMode}
                onToggleTTS={(msgId) => toggleTTS(msgId)}
                onDelete={(msgId) => handleDeleteMessage(Number(msgId))}
                onRegenerate={handleRegenerate}
                regeneratingMsgId={regeneratingMsgId}
                onSuggestionClick={(text) => setInput(text)}
                onLoadMore={handleLoadMoreHistory}
                hasMoreHistory={historyHasMore}
                isLoadingHistory={historyLoading}
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
            <ErrorBoundary componentName="StatusPanel">
                <StatusPanel 
                stats={stats} 
                emotion={emotion} 
                lifeStatus={lifeStatus} 
                emotionMix={emotionMix}
                colors={currentColors}
                />
            </ErrorBoundary>
          )}

          {activeTab === 'Circle' && (
            <ErrorBoundary componentName="CirclePanel">
              <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                <CirclePanel
                  groupMode={groupMode}
                  onToggleGroupMode={() => {
                    setGroupMode(prev => !prev);
                    setMessages(prev => [
                      ...prev,
                      {
                        id: `${Date.now()}_group_mode`,
                        isUser: false,
                        text: !groupMode ? '群聊模式已开启：你 / Aveline / Ling' : '群聊模式已关闭：当前仅 Aveline 前台回复',
                        timestamp: Date.now(),
                        messageType: 'system'
                      }
                    ]);
                  }}
                  actorLifeStates={actorLifeStates}
                  relationships={actorRelationships}
                  avelineThread={avelineThread}
                  lingThread={lingThread}
                  colors={currentColors}
                />
              </Suspense>
            </ErrorBoundary>
          )}

          {activeTab === 'Shop' && (
            <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                <ShopPanel platform="web" />
            </Suspense>
          )}

          {activeTab === 'Persona' && (
            <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                <PersonaPanel
                  persona={persona}
                  onPersonaChange={setPersona}
                  currentModel={selectedModel}
                />
            </Suspense>
          )}

          {activeTab === 'Study' && (
            <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                <StudyPanel />
            </Suspense>
          )}

          {activeTab === 'Plugins' && (
             <ErrorBoundary componentName="PluginsPanel">
               <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
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
                       onUpdateSettings={handleUpdateSettings}
                      />
               </Suspense>
             </ErrorBoundary>
           )}

           {activeTab === 'Memory' && (
             <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                 <MemoryPanel 
                    memoryData={messages}
                    onClearHistory={handleClearHistory}
                 />
             </Suspense>
           )}

           {activeTab === 'DailyData' && (
             <Suspense fallback={<div className="flex items-center justify-center h-full"><div className="spinner"/></div>}>
                 <DailyDataPanel />
             </Suspense>
           )}
        </div>
      </div>
      )}

      {/* Clear History Confirmation Modal */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="glass-card rounded-2xl p-8 max-w-md w-full shadow-2xl transform transition-all scale-100 opacity-100">
            <h3 className="text-xl font-bold mb-2 text-white text-glow tracking-wide">清空记忆确认</h3>
            <p className="text-white/50 mb-8 text-sm">请选择要执行的清除操作。此操作不可恢复。</p>
            
            <div className="space-y-4">
              <button 
                onClick={() => confirmClearHistory('short')}
                className="w-full py-4 px-5 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 hover:border-blue-500/40 rounded-xl text-left transition-all group duration-300"
              >
                <div className="font-medium text-blue-300 group-hover:text-blue-200 text-sm uppercase tracking-wider">仅清除短期记忆 (当前会话)</div>
                <div className="text-xs text-white/40 mt-1.5 leading-relaxed">保留长期记忆和重要画像，仅重置最近的对话上下文。</div>
              </button>
              
              <button 
                onClick={() => confirmClearHistory('all')}
                className="w-full py-4 px-5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 rounded-xl text-left transition-all group duration-300"
              >
                <div className="font-medium text-red-300 group-hover:text-red-200 text-sm uppercase tracking-wider">清除所有记忆 (完全重置)</div>
                <div className="text-xs text-white/40 mt-1.5 leading-relaxed">删除所有长期记忆、权重记忆和短期上下文。</div>
              </button>
            </div>
            
            <div className="mt-8 flex justify-end">
              <button 
                onClick={() => setShowClearConfirm(false)}
                className="px-4 py-2 text-white/40 hover:text-white transition-colors text-sm"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Settings View */}
      <AnimatePresence>
        {isSettingsOpen && (
          <SettingsView 
            onClose={() => setIsSettingsOpen(false)} 
            onRequestConfirm={(opts) => setConfirmDialog({ ...opts, isOpen: true })}
          />
        )}
      </AnimatePresence>

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={() => {
          confirmDialog.onConfirm();
          setConfirmDialog(prev => ({ ...prev, isOpen: false }));
        }}
        onCancel={() => {
          confirmDialog.onCancel();
          setConfirmDialog(prev => ({ ...prev, isOpen: false }));
        }}
        confirmText={confirmDialog.confirmText}
        cancelText={confirmDialog.cancelText}
        type={confirmDialog.type}
        showCancel={confirmDialog.showCancel}
      />

      {/* Login Modal */}
      <LoginModal 
        isOpen={isLoginModalOpen} 
        onLogin={handleLogin} 
        error={loginError} 
      />
    </div>
  );
}
