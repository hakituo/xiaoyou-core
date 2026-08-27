import { useEffect, useState } from 'react';
import { Device } from '@capacitor/device';
import { BatteryInfo, DeviceInfo } from '@capacitor/device';
import { Network } from '@capacitor/network';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { LocalNotifications } from '@capacitor/local-notifications';
import { Capacitor } from '@capacitor/core';

export const useNativeCapabilities = () => {
  const [deviceInfo, setDeviceInfo] = useState<DeviceInfo | null>(null);
  const [batteryInfo, setBatteryInfo] = useState<BatteryInfo | null>(null);
  const [networkStatus, setNetworkStatus] = useState<any>(null);
  const isNative = Capacitor.isNativePlatform();

  useEffect(() => {
    if (!isNative) return;

    const initInfo = async () => {
      const info = await Device.getInfo();
      setDeviceInfo(info);

      const battery = await Device.getBatteryInfo();
      setBatteryInfo(battery);

      const network = await Network.getStatus();
      setNetworkStatus(network);
    };

    initInfo();

    // 监听网络变化
    const networkListener = Network.addListener('networkStatusChange', status => {
      setNetworkStatus(status);
    });

    return () => {
      networkListener.then(handle => handle.remove());
    };
  }, [isNative]);

  // 触发震动反馈
  const triggerHaptic = async (style: ImpactStyle = ImpactStyle.Light) => {
    if (!isNative) return;
    await Haptics.impact({ style });
  };

  // 发送本地通知
  const sendNotification = async (title: string, body: string, id: number = Math.floor(Math.random() * 1000)) => {
    if (!isNative) return;

    const perm = await LocalNotifications.checkPermissions();
    if (perm.display !== 'granted') {
      await LocalNotifications.requestPermissions();
    }

    await LocalNotifications.schedule({
      notifications: [
        {
          title,
          body,
          id,
          schedule: { at: new Date(Date.now() + 1000) },
          sound: 'default',
          attachments: [],
          actionTypeId: '',
          extra: null
        }
      ]
    });
  };

  return {
    isNative,
    deviceInfo,
    batteryInfo,
    networkStatus,
    triggerHaptic,
    sendNotification
  };
};
