import { create } from 'zustand';
import { Message, EmotionType } from '../types';
import { smartSegmentText, isRetractionSegment } from '../utils/text';

interface Stats {
  fps: number;
  memory: number;
  cpu: number;
  gpu: number;
  temperature: number;
  scheduler?: {
    enabled: boolean;
    worker_count: number;
    tasks: {
      total: number;
      running: number;
      pending: number;
      completed: number;
      failed: number;
    };
    resources: {
      gpu_mem_used: number;
      gpu_mem_total: number;
      cpu_load: number;
    };
    biology?: {
      neurotransmitters: Record<string, number>;
      energy: number;
      sleep_debt: number;
    };
  };
}

interface AvelineState {
  // Messages
  messages: Message[];
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void;
  
  // Status
  lifeStatus: any;
  setLifeStatus: (status: any) => void;
  
  // Persona
  persona: any;
  setPersona: (persona: any) => void;
  
  // Emotion
  emotion: EmotionType;
  setEmotion: (emotion: EmotionType) => void;
  emotionMix: Record<string, number>;
  setEmotionMix: (mix: Record<string, number>) => void;
  emotionLockUntil: number;
  setEmotionLockUntil: (time: number) => void;
  
  // System Stats
  stats: Stats;
  updateStats: (stats: Partial<Stats>) => void;
  
  // UI State
  isTyping: boolean;
  setIsTyping: (isTyping: boolean) => void;
  studyMode: boolean;
  setStudyMode: (enabled: boolean) => void;
  
  // Settings
  breathingRate: number;
  setBreathingRate: (rate: number) => void;

  autoTtsEnabled: boolean;
  setAutoTtsEnabled: (enabled: boolean) => void;
  replyDisplayMode: 'text_and_tts' | 'tts_only';
  setReplyDisplayMode: (mode: 'text_and_tts' | 'tts_only') => void;

  ttsTextLanguage: string;
  setTtsTextLanguage: (lang: string) => void;
  ttsPromptLanguage: string;
  setTtsPromptLanguage: (lang: string) => void;
  ttsSpeed: number;
  setTtsSpeed: (speed: number) => void;
  ttsPitch: number;
  setTtsPitch: (pitch: number) => void;
  ttsProvider: string;
  setTtsProvider: (provider: string) => void;
  ttsModel: string;
  setTtsModel: (model: string) => void;
  referenceAudio: string | null;
  setReferenceAudio: (path: string | null) => void;
}

const STORAGE_KEY = 'aveline_chat_history_v2';
const SETTINGS_KEY = 'aveline_settings_v1';

const shouldPersistMessage = (message: Message): boolean => {
  if (!message) return false;
  if (!message.isUser && message.messageType === 'system') return false;
  if (!message.text && !message.audioBase64 && !message.imageUrl && !message.imageBase64 && !message.file && !message.studyData) {
    return false;
  }
  return true;
};

const toPersistedMessages = (messages: Message[]): Message[] =>
  messages.filter(shouldPersistMessage).slice(-100);

// Helper to load initial messages
const loadInitialMessages = (): Message[] => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        return parsed.filter(shouldPersistMessage).flatMap((m: Message) => {
             if (m.isUser) return [m];
             if (m.messageType === 'retraction') return [m];
             if (m.audioBase64 || m.imageUrl || m.imageBase64 || (m.messageType && m.messageType !== 'text')) return [m];
             if (!m.text) return [m];
             
             const segments = smartSegmentText(m.text, false);
             if (segments.length <= 1 && !isRetractionSegment(m.text)) return [m];
             
             return segments.map((seg, i) => ({
                 ...m,
                 id: i === 0 ? m.id : `${m.id}-${i}`,
                 text: seg,
                 messageType: isRetractionSegment(seg) ? 'retraction' : (m.messageType || 'text')
             }));
        });
      }
    }
    return [{ id: 1, isUser: false, text: "系统就绪。Aveline 核心已加载。" }];
  } catch {
    return [{ id: 1, isUser: false, text: "系统就绪。Aveline 核心已加载。" }];
  }
};

const loadInitialSettings = (): {
  autoTtsEnabled: boolean;
  replyDisplayMode: 'text_and_tts' | 'tts_only';
  ttsTextLanguage: string;
  ttsPromptLanguage: string;
  ttsSpeed: number;
  ttsPitch: number;
  ttsProvider: string;
  ttsModel: string;
  referenceAudio: string | null;
} => {
  try {
    const saved = localStorage.getItem(SETTINGS_KEY);
    const parsed = saved ? JSON.parse(saved) : null;
    if (parsed && typeof parsed === 'object') {
      const replyDisplayMode = parsed.replyDisplayMode === 'tts_only' ? 'tts_only' : 'text_and_tts';
      return {
        autoTtsEnabled: typeof parsed.autoTtsEnabled === 'boolean' ? parsed.autoTtsEnabled : false,
        replyDisplayMode,
        ttsTextLanguage: typeof parsed.ttsTextLanguage === 'string' ? parsed.ttsTextLanguage : '中英混合',
        ttsPromptLanguage: typeof parsed.ttsPromptLanguage === 'string' ? parsed.ttsPromptLanguage : '中英混合',
        ttsSpeed: typeof parsed.ttsSpeed === 'number' ? parsed.ttsSpeed : 1.0,
        ttsPitch: typeof parsed.ttsPitch === 'number' ? parsed.ttsPitch : 1.0,
        ttsProvider: typeof parsed.ttsProvider === 'string' ? parsed.ttsProvider : 'local',
        ttsModel: typeof parsed.ttsModel === 'string' ? parsed.ttsModel : 'gpt_sovits',
        referenceAudio: typeof parsed.referenceAudio === 'string' ? parsed.referenceAudio : null,
      };
    }
  } catch {
  }

  let fallbackRef: string | null = null;
  try {
    fallbackRef = sessionStorage.getItem('selected_ref_audio');
  } catch {
  }
  return {
    autoTtsEnabled: true,
    replyDisplayMode: 'text_and_tts',
    ttsTextLanguage: '中英混合',
    ttsPromptLanguage: '中英混合',
    ttsSpeed: 1.0,
    ttsPitch: 1.0,
    ttsProvider: 'local',
    ttsModel: 'gpt_sovits',
    referenceAudio: fallbackRef,
  };
};

const persistSettings = (settings: {
  autoTtsEnabled: boolean;
  replyDisplayMode: 'text_and_tts' | 'tts_only';
  ttsTextLanguage: string;
  ttsPromptLanguage: string;
  ttsSpeed: number;
  ttsPitch: number;
  ttsProvider: string;
  ttsModel: string;
  referenceAudio: string | null;
}) => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
  }
  try {
    if (settings.referenceAudio) {
      sessionStorage.setItem('selected_ref_audio', settings.referenceAudio);
    }
  } catch {
  }
};

export const useAvelineStore = create<AvelineState>((set) => ({
  ...loadInitialSettings(),
  messages: loadInitialMessages(),
  addMessage: (message) => set((state) => {
    const newMessages = [...state.messages, message];
    // Persist to localStorage
    // 简单优化：仅在消息更新时保存，实际应用中可以使用 persist middleware
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(toPersistedMessages(newMessages)));
    } catch (e) {
        console.error('Failed to save messages', e);
    }
    return { messages: newMessages };
  }),
  setMessages: (messagesOrUpdater) => set((state) => {
    const newMessages = typeof messagesOrUpdater === 'function' 
      ? messagesOrUpdater(state.messages) 
      : messagesOrUpdater;
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(toPersistedMessages(newMessages)));
    } catch (e) {
        console.error('Failed to save messages', e);
    }
    return { messages: newMessages };
  }),
  
  lifeStatus: null,
  setLifeStatus: (lifeStatus) => set({ lifeStatus }),
  
  persona: null,
  setPersona: (persona) => set({ persona }),
  
  emotion: 'neutral',
  setEmotion: (emotion) => set({ emotion }),
  
  emotionMix: { neutral: 1.0 },
  setEmotionMix: (emotionMix) => set({ emotionMix }),
  
  emotionLockUntil: 0,
  setEmotionLockUntil: (emotionLockUntil) => set({ emotionLockUntil }),
  
  stats: { fps: 60, memory: 0, cpu: 0, gpu: 0, temperature: 0 },
  updateStats: (newStats) => set((state) => ({ 
    stats: { ...state.stats, ...newStats } 
  })),
  
  isTyping: false,
  setIsTyping: (isTyping) => set({ isTyping }),
  
  studyMode: false,
  setStudyMode: (studyMode) => set({ studyMode }),
  
  breathingRate: 1.0,
  setBreathingRate: (breathingRate) => set({ breathingRate }),

  setAutoTtsEnabled: (autoTtsEnabled) => set((state) => {
    const next = { ...state, autoTtsEnabled };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { autoTtsEnabled };
  }),
  setReplyDisplayMode: (replyDisplayMode) => set((state) => {
    const next = { ...state, replyDisplayMode };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { replyDisplayMode };
  }),

  setTtsTextLanguage: (ttsTextLanguage) => set((state) => {
    const next = { ...state, ttsTextLanguage };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsTextLanguage };
  }),
  setTtsPromptLanguage: (ttsPromptLanguage) => set((state) => {
    const next = { ...state, ttsPromptLanguage };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsPromptLanguage };
  }),
  setTtsSpeed: (ttsSpeed) => set((state) => {
    const next = { ...state, ttsSpeed };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsSpeed };
  }),
  setTtsPitch: (ttsPitch) => set((state) => {
    const next = { ...state, ttsPitch };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsPitch };
  }),
  setTtsProvider: (ttsProvider) => set((state) => {
    const next = { ...state, ttsProvider };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsProvider };
  }),
  setTtsModel: (ttsModel) => set((state) => {
    const next = { ...state, ttsModel };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { ttsModel };
  }),
  setReferenceAudio: (referenceAudio) => set((state) => {
    const next = { ...state, referenceAudio };
    persistSettings({
      autoTtsEnabled: next.autoTtsEnabled,
      replyDisplayMode: next.replyDisplayMode,
      ttsTextLanguage: next.ttsTextLanguage,
      ttsPromptLanguage: next.ttsPromptLanguage,
      ttsSpeed: next.ttsSpeed,
      ttsPitch: next.ttsPitch,
      ttsProvider: next.ttsProvider,
      ttsModel: next.ttsModel,
      referenceAudio: next.referenceAudio,
    });
    return { referenceAudio };
  }),
}));
