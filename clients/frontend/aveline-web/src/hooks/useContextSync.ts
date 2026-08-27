import { useEffect, useRef } from 'react';
import { NativeService, isNative } from '../utils/nativeService';
import { api } from '../api/apiService';
import logger from '../utils/logger';

interface NativeMetrics {
  steps?: number;
  usage_stats?: string[];
  ambient_light_lux?: number;
  is_sleeping?: boolean;
  recent_notifications?: any[];
}

export const useContextSync = (intervalMs: number = 300000) => { // Default 5 minutes
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const nativeMetricsRef = useRef<NativeMetrics>({});

  useEffect(() => {
    if (!isNative) return;

    // Listen for native metrics push (from Android MainActivity)
    (window as any).onNativeMetrics = (metrics: NativeMetrics) => {
      // logger.debug('Received native metrics', metrics);
      nativeMetricsRef.current = metrics;
    };

    const syncContext = async () => {
      try {
        const [deviceInfo, batteryInfo, networkStatus, deviceId] = await Promise.all([
          NativeService.getDeviceInfo(),
          NativeService.getBatteryInfo(),
          NativeService.getNetworkStatus(),
          NativeService.getDeviceId()
        ]);

        if (!deviceInfo) return;

        // Combine basic Capacitor info with Android Native Metrics
        const context = {
          device_id: deviceId || 'unknown',
          timestamp: Date.now() / 1000,
          battery_level: batteryInfo?.batteryLevel, // 0.0 - 1.0
          is_charging: batteryInfo?.isCharging,
          network_type: networkStatus?.connectionType,
          app_state: 'active',
          current_app: 'com.xiaoyou.core', 
          location: null,
          
          // Inject Native Metrics
          step_count: nativeMetricsRef.current.steps || 0,
          usage_stats: nativeMetricsRef.current.usage_stats || [],
          ambient_light_lux: nativeMetricsRef.current.ambient_light_lux,
          is_sleeping: nativeMetricsRef.current.is_sleeping,
          recent_notifications: nativeMetricsRef.current.recent_notifications,

          extra: {
            platform: deviceInfo.platform,
            model: deviceInfo.model,
            manufacturer: deviceInfo.manufacturer,
            os_version: deviceInfo.osVersion
          }
        };

        await api.uploadDeviceContext(context);
        // logger.debug('Device context synced', context);
      } catch (error) {
        logger.warn('Failed to sync device context', error);
      }
    };

    // Initial sync
    syncContext();

    // Periodic sync
    timerRef.current = setInterval(syncContext, intervalMs);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      // Cleanup global listener
      delete (window as any).onNativeMetrics;
    };
  }, [intervalMs]);
};
