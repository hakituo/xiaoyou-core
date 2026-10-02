// TTS 语音播放逻辑（从 Aveline.tsx 抽出，原样保留行为）
import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '../api/apiService';
import { useAvelineStore } from '../store/useStore';
import { ttsParamsForEmotion } from '../utils/emotion';

const normalizeAudioSrc = (raw: string): string => {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('http')) return s;
  return `data:audio/wav;base64,${s}`;
};

export function useAvelineVoice() {
  const [voices, setVoices] = useState<any[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>('');
  const [playingMsgId, setPlayingMsgId] = useState<number | string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const setMessages = useAvelineStore((s) => s.setMessages);
  const emotion = useAvelineStore((s) => s.emotion);

  useEffect(() => {
    api.listVoices({ silent: true }).then((res: any) => {
      const list = res?.data?.voices || [];
      setVoices(list);
      if (list.length > 0) setSelectedVoiceId(String(list[0].id));
    }).catch(() => {});
  }, []);

  const playTTS = async (text: string, msgId: number | string, currentEmotion?: string | null) => {
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      setPlayingMsgId(msgId);

      // 优先使用后端已经生成好的音频（audioBase64）
      const msg = useAvelineStore.getState().messages.find((m) => String(m.id) === String(msgId));
      if (msg?.audioBase64) {
        const src = normalizeAudioSrc(msg.audioBase64);
        if (src && src !== msg.audioBase64) {
          setMessages((prev) => prev.map((m) => (String(m.id) === String(msgId) ? { ...m, audioBase64: src } : m)));
        }
        const audio = new Audio(src);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          audioRef.current = null;
        };
        audio.play().catch(() => {
          setPlayingMsgId(null);
        });
        return;
      }

      // 如果当前消息是语音消息但没有本地缓存，尝试从最近一次回复里回填后端返回的 audio_base64
      const currentMessages = useAvelineStore.getState().messages;
      const lastMsg = currentMessages[currentMessages.length - 1];
      if (!msg?.audioBase64 && lastMsg && !lastMsg.isUser && (lastMsg as any).audioBase64) {
        const b64 = normalizeAudioSrc((lastMsg as any).audioBase64 as string);
        setMessages((prev) => prev.map((m) =>
          String(m.id) === String(msgId) ? { ...m, audioBase64: b64 } : m,
        ));
        const audio = new Audio(b64);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          audioRef.current = null;
        };
        audio.play().catch(() => {
          setPlayingMsgId(null);
        });
        return;
      }

      // 若仍然没有可用音频，再回退到调用 /api/v1/tts 重新合成
      setLoadingAudio(true);

      const params = ttsParamsForEmotion(currentEmotion as any);

      // Create a timeout promise to prevent infinite spinning
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('TTS Timeout')), 30000),
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
          gpt_sovits_weights: (msg?.voiceId || selectedVoiceId) || undefined,
          reference_audio: refAudio,
        }),
        timeoutPromise,
      ]) as any;

      const b64 = normalizeAudioSrc(res?.data?.audio_base64);
      if (b64) {
        // Cache the audio
        setMessages((prev) => prev.map((m) =>
          String(m.id) === String(msgId) ? { ...m, audioBase64: b64 } : m,
        ));

        const audio = new Audio(b64);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingMsgId(null);
          setLoadingAudio(false);
          audioRef.current = null;
        };
        audio.play().catch((e) => {
          console.error('Audio play error:', e);
          setPlayingMsgId(null);
          setLoadingAudio(false);
        });
      } else {
        setPlayingMsgId(null);
        setLoadingAudio(false);
        setMessages((prev) => [...prev, { id: Date.now(), isUser: false, text: '语音合成失败：未返回音频数据' }]);
      }
    } catch (e: any) {
      console.error('TTS Error:', e);
      setPlayingMsgId(null);
      setLoadingAudio(false);
      const msgText = String(e?.message || e || '未知错误');
      setMessages((prev) => [...prev, { id: Date.now(), isUser: false, text: `语音合成失败：${msgText}`, timestamp: Date.now() }]);
    }
  };

  const toggleTTS = (msgId: number | string) => {
    if (playingMsgId === msgId) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingMsgId(null);
      setLoadingAudio(false);
    } else {
      const msg = useAvelineStore.getState().messages.find((m) => String(m.id) === String(msgId));
      if (msg && !msg.isUser) {
        playTTS(msg.text, msgId, emotion);
      }
    }
  };

  const readFileAsDataUrl = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.onload = () => resolve(String(reader.result || ''));
      reader.readAsDataURL(file);
    });
  };

  return {
    voices,
    selectedVoiceId,
    setSelectedVoiceId,
    playingMsgId,
    setPlayingMsgId,
    loadingAudio,
    audioRef,
    playTTS,
    toggleTTS,
    readFileAsDataUrl,
  };
}
