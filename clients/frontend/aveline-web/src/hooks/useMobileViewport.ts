import { useEffect, useRef, useState } from 'react';
import { Capacitor } from '@capacitor/core';

export function useMobileViewport() {
  const [viewportHeight, setViewportHeight] = useState<number | null>(null);
  const baseHeightRef = useRef<number | null>(null);
  const keyboardHeightRef = useRef<number>(0);

  useEffect(() => {
    const isNativeAndroid = Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android';
    const updateViewportHeight = () => {
      const visualHeight = window.visualViewport?.height || window.innerHeight;
      if (keyboardHeightRef.current <= 0) {
        baseHeightRef.current = visualHeight;
      }
      const baseHeight = baseHeightRef.current ?? visualHeight;
      const keyboardHeight = keyboardHeightRef.current;
      let nextHeight = visualHeight;
      if (keyboardHeight > 0 && !isNativeAndroid) {
        const expected = Math.max(0, baseHeight - keyboardHeight);
        if (Math.abs(visualHeight - expected) <= 24) {
          nextHeight = visualHeight;
        } else if (visualHeight >= baseHeight - 8) {
          nextHeight = expected;
        } else {
          nextHeight = Math.min(visualHeight, expected);
        }
      }
      setViewportHeight(nextHeight);
      document.documentElement.style.setProperty('--app-height', `${nextHeight}px`);
      document.documentElement.style.height = `${nextHeight}px`;
      document.documentElement.style.overflow = 'hidden';
      if (document.body) {
        document.body.style.height = `${nextHeight}px`;
        document.body.style.overflow = 'hidden';
      }
    };

    updateViewportHeight();
    window.visualViewport?.addEventListener('resize', updateViewportHeight);
    window.visualViewport?.addEventListener('scroll', updateViewportHeight);
    window.addEventListener('resize', updateViewportHeight);
    const handleKeyboardResize = (event: Event) => {
      const detail = (event as CustomEvent).detail as { height?: number } | undefined;
      keyboardHeightRef.current = Math.max(0, detail?.height || 0);
      updateViewportHeight();
    };
    window.addEventListener('keyboard:resize', handleKeyboardResize as EventListener);
    return () => {
      window.visualViewport?.removeEventListener('resize', updateViewportHeight);
      window.visualViewport?.removeEventListener('scroll', updateViewportHeight);
      window.removeEventListener('resize', updateViewportHeight);
      window.removeEventListener('keyboard:resize', handleKeyboardResize as EventListener);
      document.documentElement.style.removeProperty('height');
      document.documentElement.style.removeProperty('overflow');
      if (document.body) {
        document.body.style.removeProperty('height');
        document.body.style.removeProperty('overflow');
      }
    };
  }, []);

  return viewportHeight;
}
