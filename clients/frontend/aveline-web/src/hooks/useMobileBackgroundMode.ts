import { useEffect } from 'react';
import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';

export function useMobileBackgroundMode(onOpenChat: () => void) {
  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      document.addEventListener('deviceready', () => {
        const bgMode = (window as any).cordova?.plugins?.backgroundMode;
        if (bgMode) {
          bgMode.enable();
          bgMode.on('activate', () => {
            bgMode.disableWebViewOptimizations();
          });
          bgMode.setDefaults({
            title: 'Aveline 正在运行',
            text: '保持 Active Care 连接中...',
            icon: 'ic_launcher',
            color: 'F44336',
            resume: true,
            hidden: false,
            bigText: true
          });
        }
      }, false);

      LocalNotifications.addListener('localNotificationActionPerformed', () => {
        onOpenChat();
      });
    }
  }, [onOpenChat]);
}
