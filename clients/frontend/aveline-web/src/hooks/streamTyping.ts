// 流式打字渲染：把增量文本逐字/逐句渲染进消息列表，并支持「撤回」气泡样式。
// 从 useAvelineRealtime 的 enqueueStreamDelta / flush 逻辑抽取。
import { useAvelineStore } from '../store/useStore';

interface StreamTypingState {
  currentMessageId: string | null;
  sentenceIndex: number;
  retractionIndex: number;
}

export interface StreamTypingController {
  enqueueStreamDelta: (messageId: string, delta: string, getState: () => StreamTypingState, saveState: (s: StreamTypingState) => void, resetState: () => void) => void;
  flushStreamTypingState: (messageId: string, clearState: () => void) => void;
}

interface StreamTypingDeps {
  setMessages: (updater: (prev: any[]) => any[]) => void;
  setIsTyping: (v: boolean) => void;
  setShowTypingIndicator: (v: boolean) => void;
  useAvelineStore: typeof useAvelineStore;
}

export function createStreamTypingController(deps: StreamTypingDeps): StreamTypingController {
  const { setMessages, setIsTyping, setShowTypingIndicator, useAvelineStore } = deps;

  // 逐字渲染增量；通过 getState/saveState/resetState 与外层按 messageId 管理的状态交互。
  const enqueueStreamDelta = (
    messageId: string,
    delta: string,
    getState: () => StreamTypingState,
    saveState: (s: StreamTypingState) => void,
    resetState: () => void,
  ) => {
    if (!delta) return;
    const state = getState();

    for (let i = 0; i < delta.length; i++) {
      const ch = delta[i];

      // 句号：断句，结束当前气泡
      if (ch === '。' || ch === '.') {
        if (state.currentMessageId) state.currentMessageId = null;
        continue;
      }

      // 问号/感叹号：保留并断句
      if (ch === '！' || ch === '？' || ch === '!' || ch === '?') {
        if (state.currentMessageId) {
          const id = state.currentMessageId;
          setMessages((prev) => {
            const idx = prev.findIndex((m) => String(m.id) === id);
            if (idx < 0) return prev;
            const next = [...prev];
            const base = next[idx];
            next[idx] = { ...base, text: `${base.text ?? ''}${ch}` };
            return next;
          });
          state.currentMessageId = null;
          state.sentenceIndex += 1;
        }
        continue;
      }

      // 左括号：进入撤回样式
      if (ch === '(' || ch === '（') {
        if (state.currentMessageId) {
          state.currentMessageId = null;
          state.sentenceIndex += 1;
        }
        state.retractionIndex += 1;
        continue;
      }

      // 右括号：结束撤回样式
      if (ch === ')' || ch === '）') {
        if (state.currentMessageId) {
          state.currentMessageId = null;
          state.sentenceIndex += 1;
        }
        continue;
      }

      // 空白字符：追加到当前气泡
      if (/\s/.test(ch)) {
        if (state.currentMessageId) {
          const id = state.currentMessageId;
          setMessages((prev) => {
            const idx = prev.findIndex((m) => String(m.id) === id);
            if (idx < 0) return prev;
            const next = [...prev];
            const base = next[idx];
            next[idx] = { ...base, text: `${base.text ?? ''}${ch}` };
            return next;
          });
        }
        continue;
      }

      // 正常字符：追加或新建气泡
      if (!state.currentMessageId) {
        state.sentenceIndex += 1;
        const id = state.sentenceIndex === 1 ? messageId : `${messageId}-${state.sentenceIndex - 1}`;
        state.currentMessageId = id;

        const existingMessages = useAvelineStore.getState().messages;
        const duplicate = existingMessages.find((m) => String(m.id) === id);
        if (duplicate) {
          // eslint-disable-next-line no-console
          console.error(`[enqueueStreamDelta] DUPLICATE ID DETECTED! id=${id}`);
        }

        const isRetraction = state.retractionIndex > 0;
        if (isRetraction) state.retractionIndex = 0;

        setMessages((prev) => [
          ...prev,
          { id, isUser: false, text: ch, messageType: isRetraction ? 'retraction' : 'text' },
        ]);
      } else {
        const id = state.currentMessageId;
        setMessages((prev) => {
          const idx = prev.findIndex((m) => String(m.id) === id);
          if (idx < 0) {
            return [...prev, { id, isUser: false, text: ch, messageType: 'text' }];
          }
          const next = [...prev];
          const base = next[idx];
          next[idx] = { ...base, text: `${base.text ?? ''}${ch}` };
          return next;
        });
      }
    }

    saveState(state);
  };

  const flushStreamTypingState = (messageId: string, clearState: () => void) => {
    clearState();
    setIsTyping(false);
    setShowTypingIndicator(false);
  };

  return { enqueueStreamDelta, flushStreamTypingState };
}
