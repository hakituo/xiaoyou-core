import { useCallback, useEffect, useRef } from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';

type MobileMessageActionsOptions = {
  input: string;
  setInput: (value: string) => void;
  isTyping: boolean;
  setIsTyping: (value: boolean) => void;
  setShowTypingIndicator: (value: boolean) => void;
  currentSessionId: string | null;
  setCurrentSessionId: (value: string) => void;
  selectedModel: any;
  loadSessionHistory: (id: string) => Promise<void>;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  setEmotionMix: (value: any) => void;
  setEmotion: (value: any) => void;
  setEmotionLockUntil: (value: number) => void;
  autoTtsEnabled: boolean;
  normalizeAudioSrc: (src: string) => string;
  playTTS: (text: string, msgId: number | string, currentEmotion: string) => void;
  stripEmotionMarkers: (text: string) => string;
  inferEmotionFromText: (text: string) => string;
  resolveEmotionFromLabel: (label: string) => any;
  autoTtsHandledRef: React.MutableRefObject<Record<string, true>>;
  stripSystemTags?: (text: string) => string;
};

export function useMobileMessageActions({
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
}: MobileMessageActionsOptions) {
  const sendWithTextRef = useRef<((text: string) => void) | null>(null);

  const processResponse = useCallback(async (res: any) => {
    const fullReply = res?.response || res?.reply || 'Connection Error';

    if (res?.conversation_id && res.conversation_id !== currentSessionId) {
      setCurrentSessionId(res.conversation_id);
    }

    let emoLabel = null;
    if (res?.emotion) {
      emoLabel = res.emotion;
    } else {
      const emoMatch = fullReply.match(/\[EMO:\s*\{?\s*([a-zA-Z0-9_]+)\s*\}?\]/)
        || fullReply.match(/\{([a-zA-Z]+)\}/)
        || fullReply.match(/\[([a-zA-Z]+)\]/);
      emoLabel = emoMatch ? emoMatch[1] : null;
    }

    if (res?.emotion_internal && typeof res.emotion_internal === 'object') {
      setEmotionMix(res.emotion_internal);
    } else if (emoLabel) {
      setEmotionMix({ [emoLabel]: 1.0 });
    }

    const cleanText = stripEmotionMarkers(fullReply);

    if (!emoLabel || emoLabel === 'neutral') {
      const inferred = inferEmotionFromText(cleanText);
      if (inferred !== 'neutral') {
        emoLabel = inferred;
      }
    }

    const parsedEmotion = emoLabel ? resolveEmotionFromLabel(emoLabel) : 'neutral';
    if (emoLabel) {
      setEmotion(parsedEmotion);
      setEmotionLockUntil(Date.now() + 5000);
    }

    const shouldAutoTts = !!autoTtsEnabled && !!cleanText && !cleanText.includes('```');
    if (shouldAutoTts) {
      const replyId = Date.now() + 1;
      const normalizedAudio = res?.audio_base64 ? normalizeAudioSrc(String(res.audio_base64)) : undefined;
      setMessages(prev => [...prev, {
        id: replyId,
        isUser: false,
        text: cleanText,
        messageType: normalizedAudio ? 'voice' : 'text',
        voiceId: res?.voice_id,
        ...(normalizedAudio ? { audioBase64: normalizedAudio } : {})
      }]);
      setIsTyping(false);
      setShowTypingIndicator(false);
      const key = String(replyId);
      if (!autoTtsHandledRef.current[key]) {
        autoTtsHandledRef.current[key] = true;
        const ttsText = stripSystemTags ? stripSystemTags(fullReply) : cleanText;
        setTimeout(() => {
          playTTS(ttsText, replyId, String(parsedEmotion));
        }, 0);
      }
      return;
    }

    if (!cleanText.trim()) {
      setIsTyping(false);
      setShowTypingIndicator(false);
      return;
    }
    const trimmed = cleanText.trim();
    const msgType = /^(（.*）|\(.*\))$/.test(trimmed) ? 'retraction' : 'text';
    setMessages(prev => [...prev, { id: Date.now() + 1, isUser: false, text: cleanText, messageType: msgType }]);
    setIsTyping(false);
    setShowTypingIndicator(false);
  }, [
    autoTtsEnabled,
    autoTtsHandledRef,
    currentSessionId,
    inferEmotionFromText,
    normalizeAudioSrc,
    playTTS,
    resolveEmotionFromLabel,
    setCurrentSessionId,
    setEmotion,
    setEmotionLockUntil,
    setEmotionMix,
    setIsTyping,
    setMessages,
    setShowTypingIndicator,
    stripEmotionMarkers,
    stripSystemTags
  ]);

  const handleSendWithText = useCallback(async (text: string) => {
    if (!text.trim() || isTyping) return;

    const userMsg: Message = { id: Date.now(), isUser: true, text: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);
    setShowTypingIndicator(false);

    try {
      if (currentSessionId) {
        const res = await api.sendMessage(
          text,
          {
            conversationId: currentSessionId,
            modelName: selectedModel?.id
          }
        );

        if (res && res.status === 'success') {
          await processResponse(res);
        } else {
          loadSessionHistory(currentSessionId);
        }
      }
    } catch (e: any) {
      const errorMsg = e?.message || '发送消息失败';
      setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: errorMsg, messageType: 'system' }]);
    } finally {
      setIsTyping(false);
      setShowTypingIndicator(false);
    }
  }, [
    currentSessionId,
    isTyping,
    loadSessionHistory,
    processResponse,
    selectedModel,
    setInput,
    setIsTyping,
    setMessages,
    setShowTypingIndicator
  ]);

  useEffect(() => {
    sendWithTextRef.current = handleSendWithText;
  }, [handleSendWithText]);

  const sendWithText = useCallback((text: string) => {
    sendWithTextRef.current?.(text);
  }, []);

  const handleSend = useCallback(async (textOverride?: string) => {
    const textToSend = typeof textOverride === 'string' ? textOverride : input;
    if (!textToSend.trim()) return;
    await handleSendWithText(textToSend.trim());
  }, [handleSendWithText, input]);

  return {
    handleSend,
    handleSendWithText,
    sendWithText,
  };
}
