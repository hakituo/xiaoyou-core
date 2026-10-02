import { EmotionType } from '../../types';

export type BreathingPattern = 'sine' | 'pulse' | 'flicker' | 'heartbeat' | 'chaotic' | 'stable';

export interface BreathingState {
  colors: [string, string, string, string];
  speed: number; // Seconds per cycle
  pattern: BreathingPattern;
  intensity: number; // 0.0 to 1.0 (Opacity multiplier)
}

export interface SystemState {
  stats: {
    cpu: number;
    gpu: number;
    memory: number;
  };
  emotion: EmotionType;
  emotionMix?: Record<string, number>;
  lifeStatus?: {
    energy: number;
    health: number;
    mood: number;
    isSleeping?: boolean;
  };
  isThinking?: boolean; // For LLM processing state
  lastLLMTrigger?: number; // Timestamp of last LLM emotion tag
}

export interface BreathingRule {
  id: string;
  name: string;
  priority: number; // Higher wins
  condition: (state: SystemState) => boolean;
  apply: (state: SystemState) => Partial<BreathingState>;
}
