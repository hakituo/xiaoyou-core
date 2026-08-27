import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';
import { ttsParamsForEmotion } from '../utils/emotion';
import { useAvelineStore } from '../store/useStore';

type MobileTTSOptions = {
  messagesRef: React.MutableRefObject<Message[]>;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  selectedVoiceId: string;
  emotion: string;
  normalizeAudioSrc: (raw: string) => string;
};

export function useMobileTTS({
  messagesRef,
  setMessages,
  selectedVoiceId,
  emotion,
  normalizeAudioSrc,
}: MobileTTSOptions) {
  const [playingMsgId, setPlayingMsgId] = useState<number | string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  const playTTS = useCallback(async (text: string, msgId: number | string, currentEmotion: string) => {
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      setPlayingMsgId(msgId);

      const currentMessages = messagesRef.current;
      const msg = currentMessages.find(m => String(m.id) === String(msgId));
      if (msg?.audioBase64) {
        const src = normalizeAudioSrc(msg.audioBase64);
        if (src && src !== msg.audioBase64) {
          setMessages(prev => prev.map(m => String(m.id) === String(msgId) ? { ...m, audioBase64: src } : m));
        }
        const audio = new Audio(src);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          audioRef.current = null;
        };
        audio.play().catch(() => setPlayingMsgId(null));
        return;
      }

      const lastMsg = currentMessages[currentMessages.length - 1];
      if (!msg?.audioBase64 && lastMsg && !lastMsg.isUser && (lastMsg as any).audioBase64) {
        const b64 = normalizeAudioSrc((lastMsg as any).audioBase64 as string);
        setMessages(prev => prev.map(m =>
          String(m.id) === String(msgId) ? { ...m, audioBase64: b64 } : m
        ));
        const audio = new Audio(b64);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          audioRef.current = null;
        };
        audio.play().catch(() => setPlayingMsgId(null));
        return;
      }

      setLoadingAudio(true);
      const params = ttsParamsForEmotion(currentEmotion as any);

      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('TTS Timeout')), 30000)
      );

      const s = useAvelineStore.getState();
      const refAudio = s.referenceAudio || undefined;
      const res = await Promise.race([
        api.tts({
          text,
          text_language: s.ttsTextLanguage,
          prompt_language: s.ttsPromptLanguage,
          speed: typeof s.ttsSpeed === 'number' ? s.ttsSpeed : params.speed,
          pitch: typeof s.ttsPitch === 'number' ? s.ttsPitch : params.pitch,
          emotion: params.emotion,
          gpt_sovits_weights: selectedVoiceId,
          reference_audio: refAudio
        }),
        timeoutPromise
      ]) as any;

      const b64 = normalizeAudioSrc(res?.data?.audio_base64);
      if (b64) {
        setMessages(prev => prev.map(m => String(m.id) === String(msgId) ? { ...m, audioBase64: b64 } : m));
        const audio = new Audio(b64);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          audioRef.current = null;
        };
        audio.play().catch(() => setPlayingMsgId(null));
      } else {
        setPlayingMsgId(null);
        setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: '语音合成失败：未返回音频数据' }]);
      }
    } catch (e: any) {
      const msgText = String(e?.message || e || '未知错误');
      setPlayingMsgId(null);
      setMessages(prev => [...prev, { id: Date.now(), isUser: false, text: `语音合成失败：${msgText}` }]);
    } finally {
      setLoadingAudio(false);
    }
  }, [messagesRef, normalizeAudioSrc, selectedVoiceId, setMessages]);

  const toggleTTS = useCallback((msgId: number | string) => {
    if (playingMsgId === msgId) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingMsgId(null);
      setLoadingAudio(false);
    } else {
      const msg = messagesRef.current.find(m => String(m.id) === String(msgId));
      if (msg && !msg.isUser) {
        playTTS(msg.text, msgId, emotion);
      }
    }
  }, [emotion, messagesRef, playTTS, playingMsgId]);

  return {
    playingMsgId,
    loadingAudio,
    playTTS,
    toggleTTS,
  };
}
