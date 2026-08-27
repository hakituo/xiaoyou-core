// WebSocket 消息处理器：集中处理所有实时 WS 消息副作用（流式、情绪、图片、群组、TTS 等）。
// 从 useAvelineRealtime 的 700 行内联 onMessage 抽取为可测试的纯工厂函数。
import { useAvelineStore } from '../store/useStore';
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
import type { StreamTypingController } from './streamTyping';

interface HandlerRefs {
  wsStreamingMessageIdRef: React.MutableRefObject<string | null>;
  autoTtsHandledRef: React.MutableRefObject<Record<string, true>>;
  responseDoneHandledRef: React.MutableRefObject<Record<string, true>>;
  streamingTextRef: React.MutableRefObject<Record<string, string>>;
  streamingCleanRef: React.MutableRefObject<Record<string, string>>;
}

interface HandlerDeps {
  setMessages: (updater: (prev: any[]) => any[]) => void;
  setEmotion: (v: any) => void;
  setEmotionMix: (v: any) => void;
  setEmotionLockUntil: (v: number) => void;
  setIsTyping: (v: boolean) => void;
  setLifeStatus: (v: any) => void;
  setPersona: (v: any) => void;
  setStudyMode: (v: boolean) => void;
  setActorLifeStates: (v: any) => void;
  setActorRelationships: (v: any) => void;
  setLingRelationshipScore: (v: number) => void;
  setAvelineThread: (updater: (prev: any[]) => any[]) => void;
  setLingThread: (updater: (prev: any[]) => any[]) => void;
  setShowTypingIndicator: (v: boolean) => void;
  updateStats: (v: any) => void;
  streamTyping: StreamTypingController;
  playTTS: (text: string, msgId?: any, emo?: string | null) => void;
  useAvelineStore: typeof useAvelineStore;
  refs: HandlerRefs;
}

// 本地纯函数
const normalizeAudioSrc = (raw: string): string => {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('http')) return s;
  return `data:audio/wav;base64,${s}`;
};

const resolveWsMessageId = (msg: any, fallback?: string): string => {
  const raw = msg?.message_id ?? msg?.messageId ?? msg?.id ?? msg?.request_id ?? msg?.requestId ?? fallback;
  if (raw === undefined || raw === null || raw === '') return String(Date.now());
  return String(raw);
};

const resolveLingRelationshipFromMap = (rels: Record<string, number> | undefined | null): number => {
  if (!rels || typeof rels !== 'object') return 0;
  const pairKeys = ['aveline|ling', 'ling|aveline'];
  for (const key of pairKeys) {
    const v = (rels as any)[key];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
  }
  const first = Object.values(rels).find((v) => typeof v === 'number' && Number.isFinite(v));
  return typeof first === 'number' ? first : 0;
};

export function createWsMessageHandler(deps: HandlerDeps) {
  const {
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
    refs,
  } = deps;

  const {
    wsStreamingMessageIdRef,
    autoTtsHandledRef,
    responseDoneHandledRef,
    streamingTextRef,
    streamingCleanRef,
  } = refs;

  // 流式打字状态：按 messageId 管理气泡序列（挂在 streamTyping 实例上，避免每次重建）。
  const getStreamTypingState = (messageId: string) => {
    const map = (streamTyping as any)._map as Record<string, any> || ((streamTyping as any)._map = {});
    const existing = map[messageId];
    if (existing) return existing;
    const next = { currentMessageId: null as string | null, sentenceIndex: 0, retractionIndex: 0 };
    map[messageId] = next;
    return next;
  };
  const clearStreamTypingState = (messageId: string) => {
    const map = (streamTyping as any)._map as Record<string, any> | undefined;
    if (map) delete map[messageId];
    if (wsStreamingMessageIdRef.current === messageId) wsStreamingMessageIdRef.current = null;
    if (streamingTextRef.current[messageId]) delete streamingTextRef.current[messageId];
    if (streamingCleanRef.current[messageId]) delete streamingCleanRef.current[messageId];
  };

  const enqueue = (messageId: string, delta: string) => {
    streamTyping.enqueueStreamDelta(
      messageId,
      delta,
      () => getStreamTypingState(messageId),
      (s) => { (streamTyping as any)._map[messageId] = s; },
      () => clearStreamTypingState(messageId),
    );
  };

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
      if (inferred !== 'neutral') emoLabel = inferred;
    }

    const internal = meta?.emotion_internal;
    if (internal && typeof internal === 'object') {
      setEmotionMix(internal);
    } else if (emoLabel) {
      setEmotionMix({ [String(emoLabel)]: 1.0 });
    }

    if (emoLabel) {
      const lockUntil = useAvelineStore.getState().emotionLockUntil;
      if (Date.now() > lockUntil) {
        const parsed = resolveEmotionFromLabel(String(emoLabel));
        setEmotion(parsed);
        setEmotionLockUntil(Date.now() + 45000);
      }
    }
  };

  return (msg: any) => {
    if (msg.type === 'spontaneous_reaction' && msg.content) {
      const reactionMsg: Message = {
        id: Date.now(),
        isUser: false,
        text: msg.content,
        messageType: 'reaction',
      };
      setMessages((prev) => [...prev, reactionMsg]);
    }

    if (msg.type === 'life_status' && msg.data) {
      setLifeStatus(msg.data);
      if (msg.data?.actor_life_states && typeof msg.data.actor_life_states === 'object') {
        setActorLifeStates(msg.data.actor_life_states as Record<string, any>);
      }
      if (msg.data?.actor_relationships && typeof msg.data.actor_relationships === 'object') {
        const rels = msg.data.actor_relationships as Record<string, number>;
        setActorRelationships(rels);
        setLingRelationshipScore(resolveLingRelationshipFromMap(rels));
      }
      if (msg.data?.emotion) {
        applyEmotionFromText(String(msg.data.emotion), {
          emotion: msg.data.emotion,
          emotion_internal: msg.data.emotion_internal,
        });
      }
    }

    if (msg.type === 'system_status' && msg.data) {
      const newStats = {
        cpu: Math.round(msg.data.cpu?.usage || msg.data.cpu_usage || 0),
        gpu: Math.round(msg.data.gpu?.usage || msg.data.gpu_usage || 0),
        memory: Math.round(msg.data.memory?.usage || msg.data.memory_usage || 0),
        temperature: msg.data.temperature || 0,
        fps: 0,
        scheduler: msg.data.scheduler,
      };
      updateStats(newStats);
    }

    if (msg.type === 'preference_update' && msg.data) {
      setStudyMode(msg.data.mode === 'study');
    }

    if (msg.type === 'persona_update' && msg.data) {
      setPersona(msg.data);
    }

    if (msg.type === 'notification') {
      const content = msg.content || msg.data?.full_text || 'New Message';
      NativeService.sendNotification('Aveline', content);
    }

    if (msg.type === 'image_trigger') {
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);
      if (messageId) wsStreamingMessageIdRef.current = messageId;
      setMessages((prev) => {
        const idx = prev.findIndex((m) => String(m.id) === messageId);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], imageStatus: 'generating', imageError: undefined };
          return next;
        }
        return [...prev, { id: messageId, isUser: false, text: '', imageStatus: 'generating' }];
      });
      return;
    }

    if (msg.type === 'image_status' && msg.data) {
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);
      const status = typeof msg.data?.status === 'string' ? msg.data.status : '';
      if (status === 'started') {
        setMessages((prev) => {
          const idx = prev.findIndex((m) => String(m.id) === messageId);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], imageStatus: 'generating', imageError: undefined };
            return next;
          }
          return [...prev, { id: messageId, isUser: false, text: '', imageStatus: 'generating' }];
        });
      }
      return;
    }

    if (msg.type === 'image_result' && msg.data) {
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);
      const ok = !!msg.data?.success;
      const imageUrl = (msg.data?.image_url || msg.data?.imageUrl || msg.data?.url) as string | undefined;
      const imageBase64 = (msg.data?.image_base64 || msg.data?.imageBase64) as string | undefined;
      const errorText =
        (typeof msg.data?.error === 'string' && msg.data.error ? msg.data.error : '图片生成失败');
      setMessages((prev) => {
        const idx = prev.findIndex((m) => String(m.id) === messageId);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = {
            ...next[idx],
            imageStatus: ok ? 'done' : 'error',
            imageError: ok ? undefined : errorText,
            imageUrl: ok ? (imageUrl || next[idx].imageUrl) : next[idx].imageUrl,
            imageBase64: ok ? (imageBase64 || next[idx].imageBase64) : next[idx].imageBase64,
          };
          return next;
        }
        return [
          ...prev,
          {
            id: messageId,
            isUser: false,
            text: '',
            imageStatus: ok ? 'done' : 'error',
            imageError: ok ? undefined : errorText,
            imageUrl: ok ? imageUrl : undefined,
            imageBase64: ok ? imageBase64 : undefined,
          },
        ];
      });
      return;
    }

    if (msg.type === 'stream_token' && typeof msg.content === 'string' && msg.content) {
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);
      wsStreamingMessageIdRef.current = messageId;
      setIsTyping(true);
      setShowTypingIndicator(true);
      const chunk = msg.content;
      const nextFullText = `${streamingTextRef.current[messageId] || ''}${chunk}`;
      streamingTextRef.current[messageId] = nextFullText;
      const cleanFull = stripEmotionMarkers(nextFullText);
      const prevClean = streamingCleanRef.current[messageId] || '';
      const delta = cleanFull.slice(prevClean.length);
      streamingCleanRef.current[messageId] = cleanFull;
      if (delta && delta.trim()) enqueue(messageId, delta);
    }

    if (msg.type === 'group_member_message' && msg.data) {
      const speaker = typeof msg.data.speaker === 'string' ? msg.data.speaker : '成员';
      const content = typeof msg.data.content === 'string' ? msg.data.content : '';
      if (!content.trim()) return;
      const id = `${Date.now()}_group_${Math.random().toString(36).slice(2, 7)}`;
      setMessages((prev) => [
        ...prev,
        {
          id,
          isUser: false,
          text: `【${speaker}·后台】${content}`,
          timestamp: Date.now(),
          messageType: 'system',
        },
      ]);
      if (speaker.includes('玲') || speaker.includes('Ling')) {
        setLingThread((prev) => [...prev, { id, text: content, timestamp: Date.now() }]);
      }
      if (msg.data?.social_state && typeof msg.data.social_state === 'object') {
        const ss = msg.data.social_state as any;
        if (typeof ss.relationship_score === 'number') {
          setLingRelationshipScore(ss.relationship_score);
          setActorRelationships((prev: Record<string, number>) => ({ ...prev, 'aveline|ling': ss.relationship_score }));
        }
        setActorLifeStates((prev: Record<string, any>) => ({
          ...prev,
          ...(ss.bionic_aveline ? { aveline: ss.bionic_aveline } : {}),
          ...(ss.bionic_ling ? { bionic_ling: ss.bionic_ling } : {}),
        }));
      }
      return;
    }

    if (msg.type === 'message') {
      const subtype = msg.subtype || 'response';
      const messageId = resolveWsMessageId(msg, wsStreamingMessageIdRef.current || undefined);

      const wsMessageType = String(msg.message_type ?? msg.messageType ?? '').trim();
      const wsVoiceId = typeof msg.voice_id === 'string'
        ? msg.voice_id
        : (typeof msg.voiceId === 'string' ? msg.voiceId : undefined);
      const wsAudioBase64Raw = typeof msg.audio_base64 === 'string'
        ? msg.audio_base64
        : (typeof msg.audioBase64 === 'string' ? msg.audioBase64 : undefined);
      const wsAudioBase64 = wsAudioBase64Raw ? normalizeAudioSrc(wsAudioBase64Raw) : undefined;
      const wsImageUrl = typeof msg.image_url === 'string'
        ? msg.image_url
        : (typeof msg.imageUrl === 'string' ? msg.imageUrl : undefined);
      const wsImageBase64 = typeof msg.image_base64 === 'string'
        ? msg.image_base64
        : (typeof msg.imageBase64 === 'string' ? msg.imageBase64 : undefined);

      if (subtype === 'acknowledged') {
        wsStreamingMessageIdRef.current = messageId;
        setIsTyping(true);
        setShowTypingIndicator(false);
        return;
      }

      if (subtype === 'response_chunk') {
        const chunk = typeof msg.content === 'string' ? msg.content : '';
        if (!chunk) return;
        wsStreamingMessageIdRef.current = messageId;
        setIsTyping(true);
        setShowTypingIndicator(true);
        const nextFullText = `${streamingTextRef.current[messageId] || ''}${chunk}`;
        streamingTextRef.current[messageId] = nextFullText;
        const cleanFull = stripEmotionMarkers(nextFullText);
        const normalizedWsType = ['text', 'reaction', 'voice', 'system', 'retraction'].includes(wsMessageType as any)
          ? (wsMessageType as Message['messageType'])
          : undefined;
        const baseType: Message['messageType'] = normalizedWsType && normalizedWsType !== 'retraction'
          ? normalizedWsType
          : 'text';
        const hasRichPayload =
          !!(wsAudioBase64 || wsImageUrl || wsImageBase64) || normalizedWsType === 'voice';
        if (hasRichPayload) {
          setMessages((prev) => {
            const idx = prev.findIndex((m) => String(m.id) === messageId);
            if (idx >= 0) {
              const next = [...prev];
              const base = next[idx];
              next[idx] = {
                ...base,
                text: cleanFull || base.text || '',
                ...(baseType ? { messageType: baseType } : {}),
                ...(wsVoiceId ? { voiceId: wsVoiceId } : {}),
                ...(wsImageUrl ? { imageUrl: wsImageUrl } : {}),
                ...(wsImageBase64 ? { imageBase64: wsImageBase64 } : {}),
                ...(wsAudioBase64 ? { audioBase64: wsAudioBase64 } : {}),
              };
              return next;
            }
            return [
              ...prev,
              {
                id: messageId,
                isUser: false,
                text: cleanFull || chunk,
                timestamp: Date.now(),
                ...(baseType ? { messageType: baseType } : {}),
                ...(wsVoiceId ? { voiceId: wsVoiceId } : {}),
                ...(wsImageUrl ? { imageUrl: wsImageUrl } : {}),
                ...(wsImageBase64 ? { imageBase64: wsImageBase64 } : {}),
                ...(wsAudioBase64 ? { audioBase64: wsAudioBase64 } : {}),
              },
            ];
          });
          return;
        }
        const prevClean = streamingCleanRef.current[messageId] || '';
        const delta = cleanFull.slice(prevClean.length);
        streamingCleanRef.current[messageId] = cleanFull;
        if (delta && delta.trim()) enqueue(messageId, delta);
        return;
      }

      if (subtype === 'response_done') {
        if (responseDoneHandledRef.current[messageId]) return;
        responseDoneHandledRef.current[messageId] = true;

        try {
          const current = useAvelineStore.getState().messages;
          const idx = current.findIndex((x) => String(x.id) === messageId);
          const m = current[idx];
          const streamText = streamingTextRef.current[messageId];
          const rawText = typeof streamText === 'string'
            ? streamText
            : (m && typeof m.text === 'string' ? m.text : '');
          if (rawText) {
            applyEmotionFromText(rawText, msg);
            const clean = stripEmotionMarkers(rawText);
            if (clean.trim()) {
              setAvelineThread((prev) => [...prev, { id: messageId, text: clean.trim(), timestamp: Date.now() }]);
            }
            const prevClean = streamingCleanRef.current[messageId] || '';
            const delta = clean.slice(prevClean.length);
            streamingCleanRef.current[messageId] = clean;
            const shouldUpdatePayload =
              wsMessageType || wsVoiceId || wsImageUrl || wsImageBase64 || wsAudioBase64;
            if (shouldUpdatePayload) {
              setMessages((prev) => {
                const targetIndex = prev.findIndex((x) => String(x.id) === messageId);
                if (targetIndex < 0) return prev;
                const next = [...prev];
                next[targetIndex] = {
                  ...next[targetIndex],
                  ...(wsMessageType ? { messageType: wsMessageType as any } : {}),
                  ...(wsVoiceId ? { voiceId: wsVoiceId } : {}),
                  ...(wsImageUrl ? { imageUrl: wsImageUrl } : {}),
                  ...(wsImageBase64 ? { imageBase64: wsImageBase64 } : {}),
                  ...(wsAudioBase64 ? { audioBase64: wsAudioBase64 } : {}),
                };
                return next;
              });
            }
            const s = useAvelineStore.getState();
            const cleanTrimmed = clean.trim();
            if (s.autoTtsEnabled && cleanTrimmed && !autoTtsHandledRef.current[messageId]) {
              autoTtsHandledRef.current[messageId] = true;
              const emo = String(useAvelineStore.getState().emotion || 'neutral');
              setTimeout(() => playTTS(cleanTrimmed, messageId, emo), 0);
            }
            void delta;
          }
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error(`[Aveline] response_done error:`, e);
        }

        setMessages((prev) => {
          const result: Message[] = [];
          const particleWords = ['能', '和', '哎', '啊', '呢', '吧', '哦', '嗯', '唔', '呀', '嘛', '咯', '喽', '哩', '啦'];

          for (let i = 0; i < prev.length; i++) {
            const msgItem = prev[i];
            const msgIdStr = String(msgItem.id);

            if (msgIdStr.startsWith(messageId) && !msgItem.isUser && msgItem.messageType !== 'retraction') {
              const text = (msgItem.text || '').trim();
              if (text.length === 0) continue;
              if (text.length === 1 && particleWords.includes(text)) continue;
              if (text.length === 2 && result.length > 0) {
                const lastMsg = result[result.length - 1];
                const lastMsgIdStr = String(lastMsg.id);
                if (lastMsgIdStr.startsWith(messageId) && !lastMsg.isUser && lastMsg.messageType !== 'retraction') {
                  result[result.length - 1] = { ...lastMsg, text: `${lastMsg.text || ''}${text}` };
                  continue;
                }
              }
            } else {
              if (
                !msgItem.isUser &&
                !msgItem.text?.trim() &&
                msgItem.messageType !== 'retraction' &&
                !msgItem.imageUrl &&
                !msgItem.imageBase64 &&
                !msgItem.audioBase64
              ) {
                continue;
              }
            }
            result.push(msgItem);
          }
          return result;
        });

        streamTyping.flushStreamTypingState(messageId, () => clearStreamTypingState(messageId));
        return;
      }

      if (subtype === 'response') {
        const text = typeof msg.content === 'string' ? msg.content : '';
        applyEmotionFromText(text, msg);
        const clean = stripEmotionMarkers(text);
        if (clean) {
          streamTyping.flushStreamTypingState(messageId, () => clearStreamTypingState(messageId));
          const segments = smartSegmentText(clean, false);
          const firstNormalIndex = segments.findIndex((seg) => !isRetractionSegment(seg));
          const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
          const nextMessages = segments.map((segment, i) => {
            const isRetract = isRetractionSegment(segment);
            const finalText = isRetract ? segment.replace(/^[\(（]|[\)）]$/g, '') : segment;
            return {
              id: i === baseIndex ? messageId : `${messageId}-${i}`,
              isUser: false,
              text: finalText,
              ...(isRetract
                ? { messageType: 'retraction' }
                : (wsMessageType ? { messageType: wsMessageType as any } : { messageType: 'text' })),
              ...(isRetract ? {} : (wsVoiceId ? { voiceId: wsVoiceId } : {})),
              ...(isRetract ? {} : (wsImageUrl ? { imageUrl: wsImageUrl } : {})),
              ...(isRetract ? {} : (wsImageBase64 ? { imageBase64: wsImageBase64 } : {})),
              ...(isRetract ? {} : (wsAudioBase64 ? { audioBase64: wsAudioBase64 } : {})),
            };
          });
          setMessages((prev) => [...prev, ...nextMessages]);

          const s = useAvelineStore.getState();
          if (s.autoTtsEnabled && !autoTtsHandledRef.current[messageId]) {
            autoTtsHandledRef.current[messageId] = true;
            const emo = String(useAvelineStore.getState().emotion || 'neutral');
            setTimeout(() => playTTS(clean, messageId, emo), 0);
          }
        }
        return;
      }
    }

    if (msg.type === 'tts_audio') {
      const messageId = String(msg.message_id ?? msg.messageId ?? msg.id ?? '');
      const audioBase64 = typeof msg.audio_base64 === 'string'
        ? msg.audio_base64
        : (typeof msg.audio === 'string' ? msg.audio : '');
      if (!messageId || !audioBase64) return;
      const normalized = normalizeAudioSrc(audioBase64);
      setMessages((prev) => prev.map((m) => {
        if (String(m.id) !== messageId) return m;
        return { ...m, audioBase64: normalized };
      }));
      return;
    }

    if (msg.type === 'vibrate' || msg.type === 'haptic') {
      NativeService.hapticVibrate();
      return;
    }

    if (msg.type === 'error') {
      let text =
        (typeof msg.message === 'string' && msg.message) ||
        (typeof msg.error === 'string' && msg.error) ||
        '系统处理消息时遇到错误';
      if (
        /argument of type\s+['"]?NoneType['"]?\s+is not iterable/i.test(text) ||
        /NoneType\s+is not iterable/i.test(text)
      ) {
        text = '系统刚刚遇到一次数据格式异常，我已自动降级处理。请再发一次，我会继续。';
      }
      setMessages((prev) => [...prev, { id: Date.now(), isUser: false, text }]);
      setIsTyping(false);
      setShowTypingIndicator(false);
    }
  };
}
