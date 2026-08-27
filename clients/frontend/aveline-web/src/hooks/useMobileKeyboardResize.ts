import { useEffect } from 'react';
import { Capacitor, PluginListenerHandle } from '@capacitor/core';
import { Keyboard, KeyboardResize } from '@capacitor/keyboard';

export function useMobileKeyboardResize() {
  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      Keyboard.setResizeMode({ mode: KeyboardResize.Native }).catch(() => {});
      const emitKeyboardHeight = (height: number) => {
        const next = Math.max(0, height || 0);
        window.dispatchEvent(new CustomEvent('keyboard:resize', { detail: { height: next } }));
      };
      let showHandle: PluginListenerHandle | null = null;
      let showHandle2: PluginListenerHandle | null = null;
      let hideHandle: PluginListenerHandle | null = null;
      let hideHandle2: PluginListenerHandle | null = null;

      Keyboard.addListener('keyboardWillShow', (info) => {
        emitKeyboardHeight(info.keyboardHeight);
      }).then(h => { showHandle = h; });
      Keyboard.addListener('keyboardDidShow', (info) => {
        emitKeyboardHeight(info.keyboardHeight);
      }).then(h => { showHandle2 = h; });
      Keyboard.addListener('keyboardWillHide', () => {
        emitKeyboardHeight(0);
      }).then(h => { hideHandle = h; });
      Keyboard.addListener('keyboardDidHide', () => {
        emitKeyboardHeight(0);
      }).then(h => { hideHandle2 = h; });
      return () => {
        showHandle?.remove();
        showHandle2?.remove();
        hideHandle?.remove();
        hideHandle2?.remove();
      };
    }
  }, []);
}
