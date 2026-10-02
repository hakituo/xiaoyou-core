import { useCallback } from 'react';
import { Haptics, ImpactStyle } from '@capacitor/haptics';

export function useMobileHaptics() {
  const triggerHaptic = useCallback((style: ImpactStyle = ImpactStyle.Light, force: boolean = false) => {
    if (force) {
      Haptics.impact({ style }).catch(() => {});
    }
  }, []);

  const handleAutonomousVibration = useCallback((data: any) => {
    const vib = data?.vibration || data?.vibration_pattern || data?.hardware?.vibration;
    if (!vib || vib === 'none') return;

    if (typeof vib === 'object') {
      const { duration, intensity, pattern } = vib;

      if (pattern === 'heartbeat') {
        Haptics.impact({ style: ImpactStyle.Medium });
        setTimeout(() => Haptics.impact({ style: ImpactStyle.Heavy }), 150);
        return;
      }

      if (duration) {
        Haptics.vibrate({ duration: Number(duration) });
        return;
      }

      if (intensity) {
        let style = ImpactStyle.Medium;
        if (intensity === 'light' || Number(intensity) <= 0.3) style = ImpactStyle.Light;
        if (intensity === 'heavy' || Number(intensity) >= 0.7) style = ImpactStyle.Heavy;
        Haptics.impact({ style });
        return;
      }
    }

    const mode = typeof vib === 'string' ? vib : vib.mode;
    switch (mode) {
      case 'heavy':
      case 'strong':
        Haptics.impact({ style: ImpactStyle.Heavy });
        break;
      case 'medium':
        Haptics.impact({ style: ImpactStyle.Medium });
        break;
      case 'light':
      case 'soft':
        Haptics.impact({ style: ImpactStyle.Light });
        break;
      case 'long':
        Haptics.vibrate({ duration: 500 });
        break;
      case 'short':
        Haptics.impact({ style: ImpactStyle.Light });
        break;
      case 'double_short':
        Haptics.impact({ style: ImpactStyle.Light });
        setTimeout(() => Haptics.impact({ style: ImpactStyle.Light }), 150);
        break;
      default:
        Haptics.impact({ style: ImpactStyle.Light });
    }
  }, []);

  return { triggerHaptic, handleAutonomousVibration };
}
