import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';

type MobileStudyModeOptions = {
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
};

export function useMobileStudyMode({ setMessages }: MobileStudyModeOptions) {
  const [studyMode, setStudyMode] = useState(false);

  useEffect(() => {
    api.getPreferences().then((res: any) => {
      if (res?.data?.mode === 'study') {
        setStudyMode(true);
      }
    }).catch(() => {});
  }, []);

  const toggleStudyMode = useCallback(async () => {
    const newMode = !studyMode;
    setStudyMode(newMode);

    try {
      await api.updatePreferences({ mode: newMode ? 'study' : 'normal' });
      const sysMsg: Message = {
        id: Date.now(),
        isUser: false,
        text: newMode
          ? '已切换至【深度学习模式】。我是您的专业导师，将为您提供结构化、高亮核心概念的教学内容。'
          : '已切换回【普通模式】。',
        messageType: 'system'
      };
      setMessages(prev => [...prev, sysMsg]);
    } catch {
      setStudyMode(!newMode);
    }
  }, [setMessages, studyMode]);

  return {
    studyMode,
    toggleStudyMode,
  };
}
