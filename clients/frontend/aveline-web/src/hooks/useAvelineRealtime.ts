// 实时通信层：WebSocket 连接 + 消息处理器 + 流式打字渲染 + 问候
// 从 Aveline.tsx 抽出，集中管理所有 WS 消息副作用与其本地状态。
import { useEffect, useRef, useState } from 'react';
import { useAvelineStore } from '../store/useStore';
import { useWebSocket } from './useWebSocket';
import { NativeService } from '../utils/nativeService';
import {
  smartSegmentText,
  isRetractionSegment,
} from '../utils/text';
import {
  inferEmotionFromText,
  resolveEmotionFromLabel,
  stripEmotionMarkers,
} from '../utils/emotion';
import type { Message } from '../types';
import { createWsMessageHandler } from './wsMessageHandler';
import { createStreamTypingController } from './streamTyping';

interface RealtimeParams {
  currentSessionId: string | null;
  playTTS: (text: string, msgId?: any, emo?: string | null) => void;
  onAuthError: () => void;
}

export function useAvelineRealtime({ currentSessionId, playTTS, onAuthError }: RealtimeParams) {
  // ===== 本地状态（仅本层消费的 WS 副作用状态）=====
  const [showTypingIndicator, setShowTypingIndicator] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const [actorLifeStates, setActorLifeStates] = useState<Record<string, any>>({});
  const [actorRelationships, setActorRelationships] = useState<Record<string, number>>({});
  const [lingRelationshipScore, setLingRelationshipScore] = useState(0);
  const [avelineThread, setAvelineThread] = useState<Array<{ id: string; text: string; timestamp: number }>>([]);
  const [lingThread, setLingThread] = useState<Array<{ id: string; text: string; timestamp: number }>>([]);

  // ===== Store 中的状态 setter =====
  const setMessages = useAvelineStore((s) => s.setMessages);
  const setEmotion = useAvelineStore((s) => s.setEmotion);
  const setEmotionMix = useAvelineStore((s) => s.setEmotionMix);
  const setEmotionLockUntil = useAvelineStore((s) => s.setEmotionLockUntil);
  const setIsTyping = useAvelineStore((s) => s.setIsTyping);
  const setLifeStatus = useAvelineStore((s) => s.setLifeStatus);
  const setPersona = useAvelineStore((s) => s.setPersona);
  const setStudyMode = useAvelineStore((s) => s.setStudyMode);
  const updateStats = useAvelineStore((s) => s.updateStats);

  // ===== 流式打字控制器（从 streamTyping.ts 抽取）=====
  const streamTyping = createStreamTypingController({
    setMessages,
    setIsTyping,
    setShowTypingIndicator,
    useAvelineStore,
  });

  // ===== 流式消息相关的本地 refs（供消息处理器与 greeting 共享）=====
  const wsStreamingMessageIdRef = useRef<string | null>(null);
  const autoTtsHandledRef = useRef<Record<string, true>>({});
  const responseDoneHandledRef = useRef<Record<string, true>>({});
  const streamingTextRef = useRef<Record<string, string>>({});
  const streamingCleanRef = useRef<Record<string, string>>({});
  const greetingCalledRef = useRef(false);

  // ===== WebSocket 消息处理器（从 wsMessageHandler.ts 抽取）=====
  const handleWsMessage = createWsMessageHandler({
    setMessages,
    setEmotion,
    setEmotionMix,
    setEmotionLockUntil,
    setIsTyping,
    setLifeStatus,
    setPersona,
    setStudyMode,
    setActorLifeStates,
    setActorRelationships,
    setLingRelationshipScore,
    setAvelineThread,
    setLingThread,
    setShowTypingIndicator,
    updateStats,
    streamTyping,
    playTTS,
    useAvelineStore,
    refs: {
      wsStreamingMessageIdRef,
      autoTtsHandledRef,
      responseDoneHandledRef,
      streamingTextRef,
      streamingCleanRef,
    },
  });

  const { isConnected, sendMessage } = useWebSocket({
    onAuthError,
    onMessage: handleWsMessage,
  });

  // 首次连接后发送 greeting
  useEffect(() => {
    if (greetingCalledRef.current) return;
    const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
    if (!hasGreeted && currentSessionId && isConnected) {
      greetingCalledRef.current = true;
      sessionStorage.setItem('aveline_has_greeted', 'pending');
      const greetingMessageId = `greeting_${Date.now()}`;
      wsStreamingMessageIdRef.current = greetingMessageId;
      sendMessage({
        type: 'greeting',
        conversation_id: currentSessionId,
        message_id: greetingMessageId,
        timestamp: Date.now(),
      });
      sessionStorage.setItem('aveline_has_greeted', 'true');
    }
  }, [currentSessionId, isConnected, sendMessage]);

  return {
    isConnected,
    sendMessage,
    showTypingIndicator,
    setShowTypingIndicator,
    connectionError,
    lastMessage,
    actorLifeStates,
    actorRelationships,
    lingRelationshipScore,
    avelineThread,
    lingThread,
  };
}
