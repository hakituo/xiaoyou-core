// 聊天控制器：输入态、历史加载、发送/上传/重新生成/删除
// 从 Aveline.tsx 抽出，依赖实时层的 sendMessage 与 Aveline 提供的会话状态。
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/apiService';
import { useAvelineStore } from '../store/useStore';
import { buildHistoryMessages } from '../utils/avelineChatUtils';
import { stripEmotionMarkers, resolveEmotionFromLabel } from '../utils/emotion';
import type { Message } from '../types';

const HISTORY_PAGE_SIZE = 30;

interface ChatParams {
  sendMessage: (payload: any) => any;
  isConnected: boolean;
  currentSessionId: string | null;
  setCurrentSessionId: (id: string) => void;
  setShowTypingIndicator: (v: boolean) => void;
  selectedModel?: { id: string; name?: string } | null;
}

export function useAvelineChat({
  sendMessage,
  isConnected,
  currentSessionId,
  setCurrentSessionId,
  setShowTypingIndicator,
  selectedModel,
}: ChatParams) {
  const [input, setInput] = useState('');
  const [responseLength, setResponseLength] = useState<string>('normal');
  const [groupMode, setGroupMode] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyOldestTs, setHistoryOldestTs] = useState<number | null>(null);
  const [regeneratingMsgId, setRegeneratingMsgId] = useState<number | string | null>(null);

  const setMessages = useAvelineStore((s) => s.setMessages);
  const setIsTyping = useAvelineStore((s) => s.setIsTyping);
  const setEmotion = useAvelineStore((s) => s.setEmotion);

  const loadSessionHistory = useCallback(
    async (sessionId: string, options?: { reset?: boolean; before?: number | null }) => {
      if (!sessionId || sessionId === 'null') return;
      if (historyLoading) return;
      const isReset = options?.reset ?? false;
      if (isReset) {
        setHistoryHasMore(true);
        setHistoryOldestTs(null);
      }
      setHistoryLoading(true);
      try {
        const res = await api.getSessionHistory(sessionId, {
          limit: HISTORY_PAGE_SIZE,
          before: options?.before ?? undefined,
        });
        if (res.status === 'success' && Array.isArray(res.data)) {
          const newMessages = buildHistoryMessages(res.data);
          const hasMore = typeof res?.meta?.has_more === 'boolean'
            ? res.meta.has_more
            : newMessages.length >= HISTORY_PAGE_SIZE;
          setHistoryHasMore(hasMore);

          if (newMessages.length === 0 && isReset) {
            setMessages([{ id: 1, isUser: false, text: '新话题已开启' }]);
            return;
          }

          const batchOldest = newMessages.reduce((min, msg) => {
            if (typeof msg.timestamp !== 'number') return min;
            return Math.min(min, msg.timestamp);
          }, Number.POSITIVE_INFINITY);
          if (Number.isFinite(batchOldest)) {
            setHistoryOldestTs((prev) => (isReset || prev === null ? batchOldest : Math.min(prev, batchOldest)));
          }

          if (isReset) {
            setMessages(newMessages);
          } else {
            setMessages((prev) => {
              const existingIds = new Set(prev.map((m) => String(m.id)));
              const deduped = newMessages.filter((m) => !existingIds.has(String(m.id)));
              return deduped.length ? [...deduped, ...prev] : prev;
            });
          }

          if (isReset) {
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
          }
        }
      } catch (e) {
        console.error('Failed to load history', e);
        if (isReset) {
          setMessages([{ id: Date.now(), isUser: false, text: 'Failed to load history.' }]);
        }
      } finally {
        setHistoryLoading(false);
      }
    },
    [api, setMessages, setHistoryHasMore, setHistoryOldestTs, setEmotion],
  );

  const handleLoadMoreHistory = useCallback(async () => {
    if (!currentSessionId || historyLoading || !historyHasMore) return;
    await loadSessionHistory(currentSessionId, { before: historyOldestTs ?? undefined });
  }, [currentSessionId, historyLoading, historyHasMore, historyOldestTs, loadSessionHistory]);

  useEffect(() => {
    if (currentSessionId) {
      loadSessionHistory(currentSessionId, { reset: true });
    }
  }, [currentSessionId, loadSessionHistory]);

  const handleSend = useCallback(
    async (textOverride?: string) => {
      const textToSend = textOverride ?? input;
      const text = textToSend.trim();
      if (!text) return;

      const userMsg: Message = { id: Date.now(), isUser: true, text, timestamp: Date.now() };
      setMessages((prev) => [...prev, userMsg]);
      if (typeof textOverride !== 'string') {
        setInput('');
      }
      setIsTyping(true);
      setShowTypingIndicator(false);

      try {
        // Ensure session exists
        let sessionId = currentSessionId;
        if (!sessionId) {
          const res = await api.createSession();
          if (res.status === 'success') {
            const newId = res.data.id as string;
            sessionId = newId;
            setCurrentSessionId(newId);
          }
        }

        const wsRequestId = Date.now().toString(36) + Math.random().toString(36).substring(2, 9);
        console.log('[DEBUG] isConnected:', isConnected);
        console.log('[DEBUG] Attempting to send via WebSocket...');

        if (isConnected) {
          const ok = sendMessage({
            type: 'message',
            content: text,
            request_id: wsRequestId,
            message_id: wsRequestId,
            conversation_id: sessionId || undefined,
            length: responseLength,
            group_mode: groupMode,
          });
          console.log('[DEBUG] WebSocket send result:', ok);
          if (ok) {
            console.log('[DEBUG] Message sent via WebSocket successfully');
            return;
          } else {
            console.error('[DEBUG] WebSocket send returned false');
          }
        } else {
          console.error('[DEBUG] WebSocket is not connected, isConnected =', isConnected);
        }

        // WebSocket 未连接或发送失败
        console.error('WebSocket not connected or send failed');
        setMessages((prev) => [...prev, {
          id: Date.now(),
          isUser: false,
          text: 'WebSocket 未连接，请检查网络或刷新页面。请查看浏览器控制台了解详情。',
          messageType: 'system',
        }]);
        setIsTyping(false);
        setShowTypingIndicator(false);
        return;
      } catch (e: any) {
        const errorMsg = e?.message || '与 AI 核心连接出错';
        setMessages((prev) => [...prev, { id: Date.now(), isUser: false, text: errorMsg }]);
        setIsTyping(false);
        setShowTypingIndicator(false);
      }
    },
    [
      api,
      input,
      responseLength,
      groupMode,
      currentSessionId,
      setCurrentSessionId,
      isConnected,
      sendMessage,
      setIsTyping,
      setShowTypingIndicator,
      setInput,
      setMessages,
    ],
  );

  const handleRegenerate = useCallback(
    async (msgId: number | string) => {
      const messages = useAvelineStore.getState().messages;
      const msgIndex = messages.findIndex((m) => m.id === msgId);
      if (msgIndex === -1) return;

      const msgToRegenerate = messages[msgIndex];
      if (msgToRegenerate.isUser) return; // 只能重新生成AI消息

      setRegeneratingMsgId(msgId);
      setIsTyping(true);

      try {
        const res = await api.regenerateMessage({
          conversationId: currentSessionId || undefined,
          modelName: selectedModel?.id,
        });

        if (res?.reply) {
          setMessages((prev) => {
            const newMessages = prev.filter((m) => m.id !== msgId);
            const cleanText = stripEmotionMarkers(res.reply);
            if (cleanText) {
              newMessages.push({
                id: res.message_id || Date.now(),
                isUser: false,
                text: cleanText,
              });
            }
            return newMessages;
          });
        }
      } catch (error) {
        console.error('重新生成失败:', error);
      } finally {
        setRegeneratingMsgId(null);
        setIsTyping(false);
      }
    },
    [api, currentSessionId, selectedModel, setIsTyping, setRegeneratingMsgId, setMessages],
  );

  const handleDeleteMessage = useCallback(
    (id: number | string) => {
      setMessages((prev) => prev.filter((m) => m.id !== id));
    },
    [setMessages],
  );

  const handleUpload = useCallback(
    async (file: File) => {
      const isImage = String(file.type || '').toLowerCase().startsWith('image/');
      const msgId = Date.now();
      let preview = '';
      if (isImage) {
        try {
          preview = await readFileAsDataUrlLocal(file);
        } catch {
          preview = '';
        }
      }

      setMessages((prev) => [...prev, {
        id: msgId,
        isUser: true,
        text: isImage ? `[已选择图片: ${file.name}，上传中...]` : `[正在上传文件: ${file.name}...]`,
        ...(isImage && preview ? { imageBase64: preview } : {}),
      }]);

      let res: any;
      try {
        res = await api.upload(file);
      } catch (e: any) {
        setMessages((prev) => [...prev, {
          id: Date.now() + 1,
          isUser: false,
          text: `上传失败: ${e?.message || e}`,
        }]);
        return;
      }

      const filePath = String(res?.data?.file_path || '');
      if (!(res && res.status === 'success' && filePath)) {
        setMessages((prev) => [...prev, {
          id: Date.now() + 1,
          isUser: false,
          text: `上传失败: ${res?.detail || res?.message || 'Upload failed'}`,
        }]);
        return;
      }

      setMessages((prev) => {
        const idx = prev.findIndex((m) => String(m.id) === String(msgId));
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          text: isImage ? `[图片已上传: ${file.name}]` : `文件上传成功: ${file.name}`,
          ...(isImage ? { imageUrl: filePath.startsWith('/') ? filePath : `/${filePath}` } : {}),
        };
        return next;
      });

      if (!isImage) return;

      setMessages((prev) => [...prev, {
        id: msgId + 1,
        isUser: false,
        text: '正在识别图片内容...',
      }]);

      let vr: any;
      try {
        vr = await api.visionDescribe({
          model_name: 'default',
          image_path: filePath,
          prompt: '请详细描述这张图片的内容，包括场景、人物、动作、文字以及任何值得注意的细节。',
        });
      } catch (e: any) {
        setMessages((prev) => [...prev, {
          id: msgId + 2,
          isUser: false,
          text: `图片识别失败: ${e?.message || e}`,
        }]);
        return;
      }

      if (vr && vr.status === 'success' && vr.description) {
        const description = String(vr.description);
        setMessages((prev) => {
          const next = prev.filter((m) => m.text !== '正在识别图片内容...');
          return next;
        });

        handleSend(`[图像识别结果：${description}] 请根据这张图片的内容和我聊聊。`);
        return;
      }

      const errText = (vr && (vr.message || vr.error)) ? String(vr.message || vr.error) : '图片识别失败';
      setMessages((prev) => [...prev, {
        id: msgId + 2,
        isUser: false,
        text: `图片识别失败：${errText}`,
      }]);
    },
    [api, handleSend, setMessages],
  );

  return {
    input,
    setInput,
    responseLength,
    setResponseLength,
    groupMode,
    setGroupMode,
    historyLoading,
    historyHasMore,
    historyOldestTs,
    regeneratingMsgId,
    loadSessionHistory,
    handleLoadMoreHistory,
    handleSend,
    handleRegenerate,
    handleDeleteMessage,
    handleUpload,
  };
}

const readFileAsDataUrlLocal = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(file);
  });
