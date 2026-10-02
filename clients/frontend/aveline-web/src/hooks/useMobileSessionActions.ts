import { useCallback } from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';

type ConfirmDialogState = {
  isOpen: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
};

type MobileSessionActionsOptions = {
  storageKey: string;
  messages: Message[];
  currentSessionId: string | null;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  setCurrentSessionId: (value: string | null) => void;
  setShowSidebar: (value: boolean) => void;
  setConfirmDialog: (value: ConfirmDialogState | ((prev: ConfirmDialogState) => ConfirmDialogState)) => void;
};

export function useMobileSessionActions({
  storageKey,
  messages,
  currentSessionId,
  setMessages,
  setCurrentSessionId,
  setShowSidebar,
  setConfirmDialog,
}: MobileSessionActionsOptions) {
  const handleCreateSession = useCallback(async () => {
    const hasUserMessages = messages.some(m => m.isUser);
    if (currentSessionId && !hasUserMessages) {
      setMessages([]);
      const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
      if (!hasGreeted) {
        setMessages([{ id: Date.now(), isUser: false, text: '新话题已开启' }]);
      }
      setShowSidebar(false);
      return;
    }

    try {
      const res = await api.createSession();
      if (res.status === 'success') {
        setCurrentSessionId(res.data.id);
        setMessages([]);
        const hasGreeted = sessionStorage.getItem('aveline_has_greeted');
        if (!hasGreeted) {
          setMessages([{ id: Date.now(), isUser: false, text: '新话题已开启' }]);
        }
        setShowSidebar(false);
      }
    } catch (e) {
      throw e;
    }
  }, [currentSessionId, messages, setCurrentSessionId, setMessages, setShowSidebar]);

  const handleClearHistory = useCallback(async () => {
    setConfirmDialog({
      isOpen: true,
      title: 'Clear History',
      message: 'Are you sure you want to delete all memories and topics? This action cannot be undone.',
      onConfirm: async () => {
        setMessages([{ id: Date.now(), isUser: false, text: 'History cleared.' }]);
        localStorage.removeItem(storageKey);

        try {
          const res = await api.getSessions();
          if (res?.status === 'success' && Array.isArray(res.data)) {
            await Promise.all(res.data.map((s: any) => api.deleteSession(s.id)));
          }
        } catch {
        }

        await handleCreateSession();
        setConfirmDialog(prev => ({ ...prev, isOpen: false }));
      }
    });
  }, [handleCreateSession, setConfirmDialog, setMessages, storageKey]);

  const handleDeleteMessage = useCallback(async (id: number | string) => {
    setMessages(prev => prev.filter(m => m.id !== id));

    if (currentSessionId && currentSessionId !== 'null') {
      try {
        await api.deleteMessage(currentSessionId, String(id));
      } catch {
      }
    }
  }, [currentSessionId, setMessages]);

  return {
    handleCreateSession,
    handleClearHistory,
    handleDeleteMessage,
  };
}
