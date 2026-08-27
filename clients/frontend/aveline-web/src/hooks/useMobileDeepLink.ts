import { useCallback, useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { LocalNotifications } from '@capacitor/local-notifications';

type MobileDeepLinkOptions = {
  setActiveTab: (value: string) => void;
  setInput: (value: string) => void;
  handleSendWithText: (text: string) => void;
};

export function useMobileDeepLink({ setActiveTab, setInput, handleSendWithText }: MobileDeepLinkOptions) {
  const [pendingAutoSend, setPendingAutoSend] = useState<string | null>(null);

  const scheduleAutoSend = useCallback((text: string) => {
    if (!text) return;
    setPendingAutoSend(text);
  }, []);

  const normalizeTabId = (value: string | null): string | null => {
    if (!value) return null;
    const key = value.toLowerCase();
    const map: Record<string, string> = {
      chat: 'Chat',
      status: 'Status',
      daily: 'DailyData',
      dailydata: 'DailyData',
      memory: 'Memory',
      study: 'Study',
      persona: 'Persona',
      plugins: 'Plugins',
      apps: 'Plugins',
      shop: 'Shop',
      food: 'Shop'
    };
    return map[key] || null;
  };

  const handleDeepLink = useCallback((url: string, fallback?: { text?: string }) => {
    let parsed: URL | null = null;
    try {
      parsed = new URL(url);
    } catch {
      return;
    }
    const host = parsed.host || '';
    const path = parsed.pathname.replace(/^\//, '');
    const tabCandidate = parsed.searchParams.get('tab') || parsed.searchParams.get('page') || path || host;
    const resolvedTab = normalizeTabId(tabCandidate);
    if (resolvedTab) setActiveTab(resolvedTab);
    const text = parsed.searchParams.get('text') || parsed.searchParams.get('message') || fallback?.text;
    if (text) setPendingAutoSend(text);
  }, [setActiveTab]);

  useEffect(() => {
    if (pendingAutoSend) {
      setInput(pendingAutoSend);
      const timer = setTimeout(() => {
        handleSendWithText(pendingAutoSend);
        setPendingAutoSend(null);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [pendingAutoSend, setInput, handleSendWithText]);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let urlListener: { remove: () => Promise<void> } | null = null;
    let notifListener: { remove: () => Promise<void> } | null = null;
    App.addListener('appUrlOpen', (event) => {
      const url = event?.url;
      if (url) handleDeepLink(String(url));
    }).then((handle) => {
      urlListener = handle;
    });
    LocalNotifications.addListener('localNotificationActionPerformed', (event) => {
      const extra = event?.notification?.extra as any;
      const link = extra?.deepLink || extra?.url;
      if (link) {
        handleDeepLink(String(link), { text: extra?.text || extra?.body });
        return;
      }
      setActiveTab('Chat');
    }).then((handle) => {
      notifListener = handle;
    });
    return () => {
      if (urlListener) urlListener.remove();
      if (notifListener) notifListener.remove();
    };
  }, [handleDeepLink, setActiveTab]);

  return { scheduleAutoSend };
}
