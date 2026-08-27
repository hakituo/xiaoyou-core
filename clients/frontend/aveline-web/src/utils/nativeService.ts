import { Capacitor } from '@capacitor/core';
import { StatusBar, Style } from '@capacitor/status-bar';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import { Keyboard, KeyboardResize } from '@capacitor/keyboard';
import { App } from '@capacitor/app';
import { LocalNotifications } from '@capacitor/local-notifications';
import { VoiceRecorder } from 'capacitor-voice-recorder';
import { Device, DeviceInfo, BatteryInfo } from '@capacitor/device';
import { Network, ConnectionStatus } from '@capacitor/network';

export const isNative = Capacitor.isNativePlatform();

export const NativeService = {
  // --- Status Bar ---
  async initStatusBar() {
    if (!isNative) return;
    try {
      await StatusBar.setOverlaysWebView({ overlay: true });
      await StatusBar.setStyle({ style: Style.Dark });
    } catch (e) {
      console.warn('Status Bar setup failed', e);
    }
  },

  // --- Device Info ---
  async getDeviceInfo(): Promise<DeviceInfo | null> {
    if (!isNative) return null;
    try {
      return await Device.getInfo();
    } catch (e) {
      return null;
    }
  },

  async getDeviceId(): Promise<string | null> {
    if (!isNative) return null;
    try {
      const id = await Device.getId();
      return (id as any).uuid || (id as any).identifier || null;
    } catch (e) {
      return null;
    }
  },

  async getBatteryInfo(): Promise<BatteryInfo | null> {
    if (!isNative) return null;
    try {
      return await Device.getBatteryInfo();
    } catch (e) {
      return null;
    }
  },

  async getNetworkStatus(): Promise<ConnectionStatus | null> {
    if (!isNative) return null;
    try {
      return await Network.getStatus();
    } catch (e) {
      return null;
    }
  },

  // --- Haptics ---
  async hapticImpact(style: ImpactStyle = ImpactStyle.Light) {
    if (!isNative) return;
    try {
      await Haptics.impact({ style });
    } catch (e) {
      // Ignore
    }
  },

  async hapticNotification(type: NotificationType = NotificationType.Success) {
    if (!isNative) return;
    try {
      await Haptics.notification({ type });
    } catch (e) {
      // Ignore
    }
  },

  async hapticVibrate() {
     if (!isNative) return;
     try {
       await Haptics.vibrate();
     } catch (e) {
       // Ignore
     }
  },

  // --- Keyboard ---
  async initKeyboard() {
    if (!isNative) return;
    try {
      await Keyboard.setResizeMode({ mode: KeyboardResize.Native });
    } catch (e) {
      console.warn('Keyboard setup failed', e);
    }
  },

  // --- Permissions ---
  async requestPermissions() {
    if (!isNative) return;
    try {
       await LocalNotifications.requestPermissions();
       await VoiceRecorder.requestAudioRecordingPermission();
       
       // 请求忽略电池优化 (仅 Android)
       if (Capacitor.getPlatform() === 'android') {
         // 检测应用使用情况权限
         this.checkUsageStatsPermission();
         
         // 请求身体活动识别权限 (Android 10+)
         const permissions = (window as any).Capacitor.Plugins.Permissions;
         if (permissions) {
            // 注意：某些插件可能没有直接暴露，这里可以用通用方式或特定插件
         }
       }
    } catch (e) {
      console.warn('Permission request failed', e);
    }
  },

  async checkUsageStatsPermission() {
    // 这是一个特殊权限，需要引导用户去设置页
    // 我们可以通过自定义的原生方法来检测
    const native = (window as any).aveline_native;
    if (native && native.checkUsageStatsPermission) {
      const hasPermission = await native.checkUsageStatsPermission();
      if (!hasPermission) {
        // 提示用户或自动跳转
        console.log('Usage stats permission not granted');
      }
    }
  },

  async openUsageAccessSettings() {
    if (Capacitor.getPlatform() !== 'android') return;
    const native = (window as any).aveline_native;
    if (native && native.openUsageAccessSettings) {
      native.openUsageAccessSettings();
    }
  },

  // --- Notifications ---
  async sendNotification(title: string, body: string, id: number = Math.floor(Math.random() * 10000)) {
    if (!isNative) {
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body });
        }
        return;
    }
    
    try {
      await LocalNotifications.schedule({
        notifications: [
          {
            title,
            body,
            id,
            schedule: { at: new Date(Date.now() + 100) },
            sound: undefined,
            attachments: undefined,
            actionTypeId: '',
            extra: { deepLink: 'aveline://chat', title, body }
          }
        ]
      });
    } catch (e) {
      console.error('Notification failed', e);
    }
  },

  // --- Voice Recording ---
  async canRecordAudio(): Promise<boolean> {
     if (!isNative) return true; // Web assumes true or browser prompt
     const result = await VoiceRecorder.hasAudioRecordingPermission();
     return result.value;
  },

  async startRecording() {
     if (!isNative) throw new Error('Not native');
     return VoiceRecorder.startRecording();
  },

  async stopRecording() {
     if (!isNative) throw new Error('Not native');
     return VoiceRecorder.stopRecording();
  }
};
