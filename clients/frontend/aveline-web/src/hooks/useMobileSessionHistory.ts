import { useCallback, useEffect } from 'react';
import { api } from '../api/apiService';
import { EmotionType, Message } from '../types';

type MobileSessionHistoryOptions = {
  currentSessionId: string | null;
  setCurrentSessionId: (value: string | null) => void;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  setEmotion: (value: EmotionType) => void;
  normalizeAudioSrc: (raw: string) => string;
  resolveMessageTimestamp: (value?: any) => number;
  stripEmotionMarkers: (value: string) => string;
  smartSegmentText: (value: string, trimTail?: boolean) => string[];
  isRetractionSegment: (value: string) => boolean;
  segmentByRetractionOnly: (value: string) => string[];
  resolveEmotionFromLabel: (value: string) => EmotionType;
};

export function useMobileSessionHistory({
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
}: MobileSessionHistoryOptions) {
  const loadSessionHistory = useCallback(async (sessionId: string) => {
    if (!sessionId || sessionId === 'null') return;
    try {
      const res = await api.getSessionHistory(sessionId);
      if (res.status === 'success' && Array.isArray(res.data)) {
        const visible = res.data.filter((msg: any) => {
          const role = String(msg?.role || '').toLowerCase();
          const messageType = String(msg?.message_type ?? msg?.messageType ?? '').toLowerCase();
          if (role && role !== 'user' && role !== 'assistant') return false;
          if (messageType === 'system' || messageType === 'persona' || messageType === 'instruction') return false;
          const content = typeof msg?.content === 'string' ? msg.content.trim() : '';
          if (content.startsWith('Role Definition') && role !== 'user') return false;
          return true;
        });

        const newMessages = visible.flatMap((msg: any, index: number) => {
          const isUser = msg.role === 'user';
          const messageId = msg.id ?? msg.message_id ?? msg.messageId ?? `${index}`;
          const imageUrl = msg.image_url ?? msg.imageUrl;
          const imageBase64 = msg.image_base64 ?? msg.imageBase64;
          const audioBase64 = normalizeAudioSrc(msg.audio_base64 ?? msg.audioBase64);
          const voiceId = msg.voice_id ?? msg.voiceId;
          const messageTimestamp = resolveMessageTimestamp(
            msg.timestamp ?? msg.created_at ?? msg.createdAt ?? msg.time ?? msg.ts
          );
          const computedType = audioBase64 ? 'voice' : 'text';
          const rawType = String(msg.message_type ?? msg.messageType ?? computedType).toLowerCase();
          const normalizedType = ['text', 'reaction', 'voice', 'system', 'retraction'].includes(rawType)
            ? (rawType as Message['messageType'])
            : computedType;
          const content = typeof msg.content === 'string' ? msg.content : '';
          const cleanText = stripEmotionMarkers(content);
          const hasRichPayload = !!audioBase64 || !!imageUrl || !!imageBase64 || normalizedType === 'voice';

          if (isUser) {
            return [{
              id: messageId,
              isUser,
              text: cleanText,
              messageType: isUser ? 'text' : normalizedType,
              voiceId,
              imageUrl,
              imageBase64,
              audioBase64,
              timestamp: messageTimestamp,
            }];
          }

          let segments: string[] = [];
          if (hasRichPayload) {
            segments = segmentByRetractionOnly(cleanText);
          } else {
            segments = smartSegmentText(cleanText, false);
          }
          const canSplit = segments.length > 1 || (segments.length === 1 && isRetractionSegment(segments[0]));
          if (!canSplit) {
            return [{
              id: messageId,
              isUser,
              text: cleanText,
              messageType: normalizedType,
              voiceId,
              imageUrl,
              imageBase64,
              audioBase64,
              timestamp: messageTimestamp,
            }];
          }

          const firstNormalIndex = segments.findIndex(seg => !isRetractionSegment(seg));
          const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
          return segments.map((segment, i) => {
            const isRetract = isRetractionSegment(segment);
            const payloadProps = isRetract ? { audioBase64: undefined, imageUrl: undefined, imageBase64: undefined } : {
              voiceId,
              imageUrl,
              imageBase64,
              audioBase64
            };
            return {
              id: i === baseIndex ? messageId : `${messageId}-${i}`,
              isUser,
              text: segment,
              messageType: isRetract ? 'retraction' : normalizedType,
              ...payloadProps,
              timestamp: messageTimestamp + i,
            };
          });
        });

        if (newMessages.length > 0) {
          setMessages(newMessages);

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
    } catch {
    }
  }, [normalizeAudioSrc, resolveMessageTimestamp, stripEmotionMarkers, smartSegmentText, isRetractionSegment, segmentByRetractionOnly, resolveEmotionFromLabel, setMessages, setEmotion]);

  useEffect(() => {
    const last = localStorage.getItem('aveline_last_session_id');
    if (last) setCurrentSessionId(last);
  }, [setCurrentSessionId]);

  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem('aveline_last_session_id', currentSessionId);
      loadSessionHistory(currentSessionId);
    }
  }, [currentSessionId, loadSessionHistory]);

  return { loadSessionHistory };
}
