// 历史消息解析相关纯函数（从 Aveline.tsx 抽出，便于复用与测试）

import { smartSegmentText, isRetractionSegment } from '../utils/text';
import { stripEmotionMarkers } from '../utils/emotion';
import type { Message } from '../types';

const normalizeAudioSrc = (raw: string): string => {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('http')) return s;
  return `data:audio/wav;base64,${s}`;
};

export const resolveMessageTimestamp = (value?: any): number => {
  const num = Number(value);
  if (!Number.isFinite(num)) return Date.now();
  return num < 1e12 ? num * 1000 : num;
};

export const buildHistoryMessages = (data: any[]): Message[] => {
  const visible = data.filter((msg: any) => {
    const role = String(msg?.role || '').toLowerCase();
    const messageType = String(msg?.message_type ?? msg?.messageType ?? '').toLowerCase();
    if (role && role !== 'user' && role !== 'assistant') return false;
    if (messageType === 'system' || messageType === 'persona' || messageType === 'instruction') return false;
    const content = typeof msg?.content === 'string' ? msg.content.trim() : '';
    if (content.startsWith('Role Definition') && role !== 'user') return false;
    return true;
  });

  const output: Message[] = [];

  visible.forEach((msg: any, index: number) => {
    const isUser = msg.role === 'user';
    const messageId = msg.id ?? msg.message_id ?? msg.messageId ?? `${index}`;
    const imageUrl = msg.image_url ?? msg.imageUrl;
    const imageBase64 = msg.image_base64 ?? msg.imageBase64;
    const audioBase64 = normalizeAudioSrc(msg.audio_base64 ?? msg.audioBase64);
    const voiceId = msg.voice_id ?? msg.voiceId;
    const computedType = audioBase64 ? 'voice' : 'text';
    const rawType = String(msg.message_type ?? msg.messageType ?? computedType).toLowerCase();
    const normalizedType = ['text', 'reaction', 'voice', 'system', 'retraction'].includes(rawType)
      ? (rawType as Message['messageType'])
      : computedType;
    const content = typeof msg.content === 'string' ? msg.content : '';
    const cleanText = stripEmotionMarkers(content);
    const hasRichPayload = !!audioBase64 || !!imageUrl || !!imageBase64 || normalizedType === 'voice';
    const messageTimestamp = resolveMessageTimestamp(msg.timestamp ?? msg.id);

    if (isUser || hasRichPayload) {
      output.push({
        id: messageId,
        isUser,
        text: cleanText,
        messageType: isUser ? 'text' : normalizedType,
        voiceId,
        imageUrl,
        imageBase64,
        audioBase64,
        timestamp: messageTimestamp,
      });
      return;
    }

    const segments = smartSegmentText(cleanText, false);
    const canSplit = segments.length > 1 || (segments.length === 1 && isRetractionSegment(segments[0]));
    if (!canSplit) {
      output.push({
        id: messageId,
        isUser,
        text: cleanText,
        messageType: normalizedType,
        timestamp: messageTimestamp,
      });
      return;
    }

    const firstNormalIndex = segments.findIndex(seg => !isRetractionSegment(seg));
    const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
    segments.forEach((segment, i) => {
      const isRetract = isRetractionSegment(segment);
      output.push({
        id: i === baseIndex ? messageId : `${messageId}-${i}`,
        isUser,
        text: segment,
        messageType: isRetract ? 'retraction' : normalizedType,
        timestamp: messageTimestamp + i,
      });
    });
  });

  return output;
};
