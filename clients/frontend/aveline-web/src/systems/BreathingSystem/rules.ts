import { BreathingRule, SystemState } from './types';
import { EMOTIONS, calculateMixedColors } from '../../utils/emotion';

// Priority Levels
const PRIORITY = {
  CRITICAL: 100,
  HIGH: 80,
  MEDIUM: 50,
  BASE: 10
};

const isRealEmotionMix = (mix?: Record<string, number>) => {
  if (!mix) return false;
  const active = Object.entries(mix).filter(([, w]) => w > 0);
  const nonNeutral = active.filter(([k]) => k !== 'neutral');
  return active.length >= 2 && nonNeutral.length >= 1;
};

// Helper: Get target colors based on state
const getTargetColors = (state: SystemState): [string, string, string, string] => {
  if (isRealEmotionMix(state.emotionMix)) {
    return calculateMixedColors(state.emotionMix!);
  }
  
  const config = EMOTIONS[state.emotion] || EMOTIONS.neutral;
  return config.colors;
};

const getTargetSpeed = (state: SystemState): number => {
  if (isRealEmotionMix(state.emotionMix)) {
    let totalSpeed = 0;
    let totalWeight = 0;
    Object.entries(state.emotionMix!).forEach(([k, w]) => {
      // @ts-ignore
      const speed = EMOTIONS[k]?.speed;
      if (speed && w > 0) {
        totalSpeed += speed * w;
        totalWeight += w;
      }
    });
    if (totalWeight > 0) return totalSpeed / totalWeight;
  }

  const config = EMOTIONS[state.emotion] || EMOTIONS.neutral;
  return config.speed;
};

export const BREATHING_RULES: BreathingRule[] = [
  // ----------------------------------------------------------------
  // 1. Critical Hardware Rules (Highest Priority)
  // ----------------------------------------------------------------
  {
    id: 'cpu_heavy_load',
    name: 'CPU Heavy Load Indicator',
    priority: PRIORITY.CRITICAL,
    condition: (state) => state.stats.cpu > 85,
    apply: (state) => {
      const baseSpeed = getTargetSpeed(state);
      return {
        colors: getTargetColors(state),
        speed: Math.max(0.5, baseSpeed * 0.6),
        pattern: 'pulse',
        intensity: 1.0
      };
    }
  },
  {
    id: 'memory_warning',
    name: 'High Memory Usage',
    priority: PRIORITY.HIGH,
    condition: (state) => state.stats.memory > 90,
    apply: (state) => ({
      colors: getTargetColors(state),
      speed: Math.max(0.6, getTargetSpeed(state) * 0.55),
      pattern: 'pulse',
      intensity: 1.0
    })
  },

  // ----------------------------------------------------------------
  // 2. Biological/Life Rules (High Priority)
  // ----------------------------------------------------------------
  {
    id: 'sleeping',
    name: 'Deep Sleep',
    priority: PRIORITY.HIGH + 1, // Override memory warning if sleeping
    condition: (state) => !!state.lifeStatus?.isSleeping,
    apply: () => ({
      colors: ['#1A1A2E', '#16213E', '#0F3460', '#000000'],
      speed: 8.0, // Very slow breathing
      pattern: 'sine',
      intensity: 0.3 // Dimmed
    })
  },
  {
    id: 'low_energy',
    name: 'Low Energy (Exhausted)',
    priority: PRIORITY.HIGH,
    condition: (state) => (state.lifeStatus?.energy ?? 100) < 20,
    apply: () => ({
      colors: ['#4A4A4A', '#6B7280', '#1F2937', '#111827'],
      speed: 6.0,
      pattern: 'stable',
      intensity: 0.5
    })
  },

  // ----------------------------------------------------------------
  // 3. Interaction Rules (Medium Priority)
  // ----------------------------------------------------------------
  {
    id: 'thinking',
    name: 'LLM Processing',
    priority: PRIORITY.MEDIUM,
    condition: (state) => !!state.isThinking,
    apply: (state) => ({
      colors: getTargetColors(state),
      speed: 1.5,
      pattern: 'sine',
      intensity: 0.9
    })
  },

  // ----------------------------------------------------------------
  // 4. Emotional Rules (Base Priority)
  // ----------------------------------------------------------------
  // Single Emotion Rules (Specific Patterns)
  {
    id: 'emotion_excited',
    name: 'Excited State',
    priority: PRIORITY.BASE,
    condition: (state) => state.emotion === 'excited',
    apply: (state) => ({
      colors: getTargetColors(state),
      speed: Math.max(0.7, getTargetSpeed(state) * 0.5),
      pattern: 'heartbeat',
      intensity: 1.0
    })
  },
  {
    id: 'emotion_angry',
    name: 'Angry State',
    priority: PRIORITY.BASE,
    condition: (state) => state.emotion === 'angry',
    apply: (state) => ({
      colors: getTargetColors(state),
      speed: Math.max(0.6, getTargetSpeed(state) * 0.32),
      pattern: 'chaotic',
      intensity: 1.0
    })
  },
  {
    id: 'emotion_shy',
    name: 'Shy State',
    priority: PRIORITY.BASE,
    condition: (state) => state.emotion === 'shy',
    apply: (state) => ({
      colors: getTargetColors(state),
      speed: Math.max(3.2, getTargetSpeed(state)),
      pattern: 'pulse', // Soft pulse
      intensity: 0.7
    })
  },
  // Default/Fallback Rule
  {
    id: 'default',
    name: 'Default State',
    priority: 0,
    condition: () => true,
    apply: (state) => {
      return {
        colors: getTargetColors(state),
        speed: getTargetSpeed(state),
        pattern: 'sine',
        intensity: 0.8
      };
    }
  }
];
