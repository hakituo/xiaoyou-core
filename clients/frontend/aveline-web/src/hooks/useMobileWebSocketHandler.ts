import { useCallback, useRef } from 'react';
import { ImpactStyle } from '@capacitor/haptics';
import { Message } from '../types';
import { smartSegmentText, isRetractionSegment, tokenizeStreamingText } from '../utils/text';
import { useAvelineStore } from '../store/useStore';

type MobileWebSocketHandlerOptions = {
  setCurrentModel: (value: string) => void;
  triggerHaptic: (style?: ImpactStyle, force?: boolean) => void;
  handleAutonomousVibration: (data: any) => void;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  setLifeStatus: (value: any) => void;
  setPersona: (value: any) => void;
  applyEmotionFromText: (text: string, meta?: any) => void;
  setIsTyping: (value: boolean) => void;
  setShowTypingIndicator: (value: boolean) => void;
  autoTtsEnabled: boolean;
  playTTS: (text: string, msgId: number | string, currentEmotion: string) => void;
  autoTtsHandledRef: React.MutableRefObject<Record<string, true>>;
  stripEmotionMarkers: (value: string) => string;
  stripSystemTags?: (value: string) => string;
  resolveMessageTimestamp: (value?: any) => number;
  studyMode?: boolean;
};

export function useMobileWebSocketHandler({
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
}: MobileWebSocketHandlerOptions) {
  const wsStreamingMessageIdRef = useRef<string | null>(null);
  const streamingTextRef = useRef<Record<string, string>>({});
  const streamingCleanRef = useRef<Record<string, string>>({});
  const streamingSeenRef = useRef<Record<string, true>>({});
  const streamTypingStateRef = useRef<Record<string, {
    buffer: string;
    queue: Array<{ kind: 'char' | 'sentence' | 'retraction'; value: string }>;
    currentMessageId: string | null;
    sentenceIndex: number;
    retractionIndex: number;
    timer: number | null;
    done: boolean;
    timestamp: number;
  }>>({});

  const resolveWsMessageId = useCallback((msg: any, fallback?: string) => {
    const raw = msg?.message_id ?? msg?.messageId ?? msg?.id ?? msg?.request_id ?? msg?.requestId ?? fallback;
    if (raw === undefined || raw === null || raw === '') {
      return String(Date.now());
    }
    return String(raw);
  }, []);

  const typingIntervalMs = 24;

  const getStreamTypingState = useCallback((messageId: string, timestamp: number) => {
    const existing = streamTypingStateRef.current[messageId];
    if (existing) {
      if (!existing.timestamp) {
        existing.timestamp = timestamp;
      }
      return existing;
    }
    const next = {
      buffer: '',
      queue: [] as Array<{ kind: 'char' | 'sentence' | 'retraction'; value: string }>,
      currentMessageId: null as string | null,
      sentenceIndex: 0,
      retractionIndex: 0,
      timer: null as number | null,
      done: false,
      timestamp
    };
    streamTypingStateRef.current[messageId] = next;
    return next;
  }, []);

  const flushStreamTypingState = useCallback((messageId: string) => {
    const state = streamTypingStateRef.current[messageId];
    if (state?.timer) {
      window.clearInterval(state.timer);
    }
    delete streamTypingStateRef.current[messageId];
    if (wsStreamingMessageIdRef.current === messageId) {
      wsStreamingMessageIdRef.current = null;
    }
    if (streamingTextRef.current[messageId]) {
      delete streamingTextRef.current[messageId];
    }
    if (streamingCleanRef.current[messageId]) {
      delete streamingCleanRef.current[messageId];
    }
    if (streamingSeenRef.current[messageId]) {
      delete streamingSeenRef.current[messageId];
    }
    setIsTyping(false);
    setShowTypingIndicator(false);
  }, [setIsTyping, setShowTypingIndicator]);

  const stripTrailingFullStop = useCallback((value: string) => {
    if (!value) return value;
    return value.endsWith('。') ? value.slice(0, -1) : value;
  }, []);

  const buildSegments = useCallback((value: string) => {
    const segments = smartSegmentText(value, false);
    const firstNormalIndex = segments.findIndex(seg => !isRetractionSegment(seg));
    const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
    return segments
      .map((segment, index) => {
        const isRetract = isRetractionSegment(segment);
        const trimmed = segment.trim();
        const text = isRetract ? trimmed : stripTrailingFullStop(trimmed);
        return { text, isRetract, index, baseIndex };
      })
      .filter(item => item.text.length > 0);
  }, [stripTrailingFullStop]);

  const processStreamQueue = useCallback((messageId: string) => {
    const state = streamTypingStateRef.current[messageId];
    if (!state) return;
    if (state.queue.length === 0) {
      if (state.timer) {
        window.clearInterval(state.timer);
        state.timer = null;
      }
      if (state.done) {
        flushStreamTypingState(messageId);
      }
      return;
    }
    const item = state.queue.shift();
    if (!item) return;
    
    if (item.kind === 'char') {
      // 检查是否是左括号 - 进入撤回样式
      if (item.value === '(') {
        // 如果当前有消息，先标记当前消息结束
        if (state.currentMessageId) {
          state.currentMessageId = null;
        }
        // 创建新的撤回样式消息
        const id = `${messageId}-r-${state.retractionIndex}`;
        state.retractionIndex += 1;
        state.currentMessageId = id;
        setMessages(prev => [
          ...prev,
          { id, isUser: false, text: '', messageType: 'retraction', timestamp: state.timestamp }
        ]);
        return;
      }
      
      // 检查是否是右括号 - 结束撤回样式
      if (item.value === ')') {
        if (state.currentMessageId) {
          state.currentMessageId = null;
        }
        return;
      }
      
      // 正常字符处理
      if (!state.currentMessageId) {
        const id = state.sentenceIndex === 0 ? messageId : `${messageId}-${state.sentenceIndex}`;
        state.currentMessageId = id;
        setMessages(prev => [
          ...prev,
          { id, isUser: false, text: item.value, messageType: 'text', timestamp: state.timestamp }
        ]);
      } else {
        const id = state.currentMessageId;
        setMessages(prev => {
          const idx = prev.findIndex(m => String(m.id) === id);
          if (idx < 0) {
            return [...prev, { id, isUser: false, text: item.value, messageType: 'text', timestamp: state.timestamp }];
          }
          const next = [...prev];
          const base = next[idx];
          next[idx] = {
            ...base,
            text: `${base.text ?? ''}${item.value}`,
            messageType: base.messageType ?? 'text',
            timestamp: base.timestamp ?? state.timestamp
          } as Message;
          return next;
        });
      }
      return;
    }
    
    if (item.kind === 'sentence') {
      // 句子结束标记 - 标记当前消息结束并增加句子索引
      if (state.currentMessageId) {
        state.currentMessageId = null;
      }
      state.sentenceIndex += 1;
      return;
    }
    
    if (item.kind === 'retraction') {
      const id = `${messageId}-r-${state.retractionIndex}`;
      state.retractionIndex += 1;
      setMessages(prev => [
        ...prev,
        { id, isUser: false, text: item.value, messageType: 'retraction', timestamp: state.timestamp }
      ]);
    }
  }, [flushStreamTypingState, setMessages]);

  const startStreamTyping = useCallback((messageId: string) => {
    const state = streamTypingStateRef.current[messageId];
    if (!state || state.timer) return;
    state.timer = window.setInterval(() => processStreamQueue(messageId), typingIntervalMs);
  }, [processStreamQueue]);

  const enqueueStreamDelta = useCallback((messageId: string, delta: string, timestamp: number) => {
    if (!delta) return;
    const state = getStreamTypingState(messageId, timestamp);
    state.buffer += delta;
    const { tokens, rest } = tokenizeStreamingText(state.buffer);
    state.buffer = rest;
    tokens.forEach(token => {
      if (token.type === 'retraction') {
        state.queue.push({ kind: 'retraction', value: token.value });
      } else {
        // 处理普通文本，检测句号并添加断句标记
        let i = 0;
        while (i < token.value.length) {
          const ch = token.value[i];
          if (ch === '。' || ch === '.') {
            // 添加断句标记，但不添加句号字符
            state.queue.push({ kind: 'sentence', value: '' });
          } else {
            state.queue.push({ kind: 'char', value: ch });
          }
          i++;
        }
      }
    });
    startStreamTyping(messageId);
  }, [getStreamTypingState, startStreamTyping]);

  const onMessage = useCallback((msg: any) => {

    if (msg.type === 'system' && msg.current_model) {
      setCurrentModel(msg.current_model);
      triggerHaptic(ImpactStyle.Light);
    }
    if (msg.type === 'spontaneous_reaction' && msg.content) {
      handleAutonomousVibration({ vibration: { duration: 500 } });
      const reactionMsg: Message = {
        id: Date.now(),
        isUser: false,
        text: msg.content,
        messageType: 'reaction',
        timestamp: Date.now()
      };
      setMessages(prev => [...prev, reactionMsg]);
    }

    if (msg.type === 'ritual_event' && msg.content) {
      const ritualMsg: Message = {
        id: Date.now(),
        isUser: false,
        text: msg.content,
        messageType: 'reaction',
        timestamp: Date.now()
      };
      setMessages(prev => [...prev, ritualMsg]);
    }

    if (msg.type === 'life_status' && msg.data) {
      setLifeStatus(msg.data);
      if (msg.data.emotion) {
        applyEmotionFromText(String(msg.data.emotion), { emotion: msg.data.emotion, emotion_internal: msg.data.emotion_internal });
      }
    }

    if (msg.type === 'emotion_update' && msg.data) {
      const emo = msg.data.primary_emotion;
      if (emo) {
        applyEmotionFromText(emo, { emotion: emo, ...msg.data });
      }
      if (msg.data.hardware) {
        handleAutonomousVibration(msg.data.hardware);
      }
    }

    if (msg.type === 'persona_update' && msg.data) {
      setPersona(msg.data);
    }

    if (msg.type === 'notification') {
      const content = msg.content || msg.data || 'New Message';
      triggerHaptic(ImpactStyle.Heavy);
      if ((window as any).aveline_native?.showNotification) {
        (window as any).aveline_native.showNotification('Aveline', content);
      } else if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Aveline', { body: content });
      }
    }

    if (msg.type === 'hardware_control') {
      if (msg.data) {
        handleAutonomousVibration(msg.data);
      }
    }

    if (msg.type === 'stream_token' && typeof msg.content === 'string' && msg.content) {
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);
      const chunk = msg.content;
      const chunkTs = resolveMessageTimestamp(msg?.timestamp);
      wsStreamingMessageIdRef.current = messageId;
      streamingSeenRef.current[messageId] = true;
      setIsTyping(true);
      setShowTypingIndicator(true);
      const nextFullText = `${streamingTextRef.current[messageId] || ''}${chunk}`;
      streamingTextRef.current[messageId] = nextFullText;
      if (studyMode) return;
      const cleanFull = stripEmotionMarkers(nextFullText);
      const prevClean = streamingCleanRef.current[messageId] || '';
      const delta = cleanFull.startsWith(prevClean) ? cleanFull.slice(prevClean.length) : cleanFull;
      streamingCleanRef.current[messageId] = cleanFull;
      enqueueStreamDelta(messageId, delta, chunkTs);
      return;
    }

    if (msg.type === 'message') {
      const subtype = msg.subtype || 'response';
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);

      if (subtype === 'acknowledged') {
        wsStreamingMessageIdRef.current = messageId;
        setIsTyping(true);
        setShowTypingIndicator(false);
        return;
      }

      if (subtype === 'response_chunk') {
        const chunk = typeof msg.content === 'string' ? msg.content : '';
        if (!chunk) return;
        const chunkTs = resolveMessageTimestamp(msg?.timestamp);
        wsStreamingMessageIdRef.current = messageId;
        streamingSeenRef.current[messageId] = true;
        setIsTyping(true);
        setShowTypingIndicator(true);
        const nextFullText = `${streamingTextRef.current[messageId] || ''}${chunk}`;
        streamingTextRef.current[messageId] = nextFullText;
        if (studyMode) return;
        const cleanFull = stripEmotionMarkers(nextFullText);
        const prevClean = streamingCleanRef.current[messageId] || '';
        const delta = cleanFull.startsWith(prevClean) ? cleanFull.slice(prevClean.length) : cleanFull;
        streamingCleanRef.current[messageId] = cleanFull;
        enqueueStreamDelta(messageId, delta, chunkTs);
        return;
      }

      if (subtype === 'response_done') {
        const baseTs = resolveMessageTimestamp(msg?.timestamp);
        
        // 标记流式输出完成
        const state = streamTypingStateRef.current[messageId];
        if (state) {
          state.done = true;
          // 不需要再添加内容，只需要标记完成让队列处理完毕
        } else {
          // 如果没有流式状态，说明没有收到任何 chunk，清理状态
          flushStreamTypingState(messageId);
        }
        
        // 处理元数据
        if (msg.metadata) {
          handleAutonomousVibration(msg.metadata);
        }

        // 处理 TTS
        const streamText = streamingTextRef.current[messageId];
        if (streamText) {
          const clean = stripEmotionMarkers(streamText).trim();
          if (autoTtsEnabled && clean && !autoTtsHandledRef.current[messageId]) {
            autoTtsHandledRef.current[messageId] = true;
            const emo = String(useAvelineStore.getState().emotion || 'neutral');
            const ttsText = stripSystemTags ? stripSystemTags(streamText) : clean;
            setTimeout(() => {
              playTTS(ttsText, messageId, emo);
            }, 0);
          }
        }
        
        // 应用情绪
        if (streamText) {
          applyEmotionFromText(streamText, msg);
        }
        
        return;
      }

      if (subtype === 'response') {
        if (msg.metadata) {
          handleAutonomousVibration(msg.metadata);
        }

        const text = typeof msg.content === 'string' ? msg.content : '';
        applyEmotionFromText(text, msg);
        const clean = stripEmotionMarkers(text).trim();
        if (clean) {
          flushStreamTypingState(messageId);
          const segments = buildSegments(clean);
          if (segments.length) {
            setMessages(prev => [
              ...prev,
              ...segments.map((segment) => ({
                id: segment.index === segment.baseIndex ? messageId : `${messageId}-${segment.index}`,
                isUser: false,
                text: segment.text,
                messageType: (segment.isRetract ? 'retraction' : 'text') as Message['messageType']
              }))
            ]);
            if (autoTtsEnabled && !autoTtsHandledRef.current[messageId]) {
              autoTtsHandledRef.current[messageId] = true;
              const emo = String(useAvelineStore.getState().emotion || 'neutral');
              // For streaming response completion, we might not have 'fullReply' with markers here easily if segments are used.
              // However, 'text' is the raw content.
              const ttsText = stripSystemTags ? stripSystemTags(text) : segments.filter(seg => !seg.isRetract).map(seg => seg.text).join('');
              if (ttsText) {
                setTimeout(() => {
                  playTTS(ttsText, messageId, emo);
                }, 0);
              }
            }
          }
        }
        return;
      }
    }

    if (msg.type === 'error') {
      const text =
        (typeof msg.message === 'string' && msg.message) ||
        (typeof msg.error === 'string' && msg.error) ||
        '系统处理消息时遇到错误';
      setMessages(prev => [
        ...prev,
        {
          id: Date.now(),
          isUser: false,
          text,
          messageType: 'system'
        }
      ]);
      setIsTyping(false);
      setShowTypingIndicator(false);
    }
  }, [
    applyEmotionFromText,
    autoTtsEnabled,
    autoTtsHandledRef,
    enqueueStreamDelta,
    flushStreamTypingState,
    handleAutonomousVibration,
    playTTS,
    resolveMessageTimestamp,
    resolveWsMessageId,
    setCurrentModel,
    setIsTyping,
    setLifeStatus,
    setMessages,
    setPersona,
    setShowTypingIndicator,
    startStreamTyping,
    stripEmotionMarkers,
    studyMode,
    triggerHaptic
  ]);

  return { onMessage };
}
