import { useState, useEffect, useRef, useMemo } from 'react';
import { BreathingState, SystemState, BreathingPattern } from './types';
import { BREATHING_RULES } from './rules';
import { EMOTIONS, hexToRgb, rgbToHex } from '../../utils/emotion';

const lerp = (start: number, end: number, factor: number) => start + (end - start) * factor;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

const buildEffectiveState = (state: SystemState): SystemState => {
  const memory = Number(state.stats?.memory ?? 0);
  const stress = clamp01((memory - 75) / 25);
  const baseMix = state.emotionMix;

  if (!stress || stress <= 0) {
    return state;
  }

  const mixed: Record<string, number> = {};

  if (baseMix && Object.keys(baseMix).length > 0) {
    Object.entries(baseMix).forEach(([k, w]) => {
      if (w > 0) mixed[k] = (mixed[k] ?? 0) + w * (1 - 0.55 * stress);
    });
  } else {
    mixed[state.emotion] = 1 - 0.55 * stress;
  }

  mixed.angry = (mixed.angry ?? 0) + stress * 0.7;
  mixed.lost = (mixed.lost ?? 0) + stress * 0.3;

  let total = 0;
  Object.values(mixed).forEach(v => {
    total += Math.max(0, v);
  });

  if (total <= 0) {
    return state;
  }

  Object.keys(mixed).forEach(k => {
    mixed[k] = Math.max(0, mixed[k]) / total;
  });

  return {
    ...state,
    emotionMix: mixed
  };
};

const DEFAULT_STATE: BreathingState = {
  colors: EMOTIONS.neutral.colors,
  speed: 3,
  pattern: 'sine',
  intensity: 0.8
};

export function useBreathingSystem(
  systemState: SystemState
) {
  // Current visual state
  const [visualState, setVisualState] = useState<BreathingState>(DEFAULT_STATE);
  
  // Refs for animation loop
  const stateRef = useRef(systemState);
  const currentValuesRef = useRef({
    colors: DEFAULT_STATE.colors.map(hexToRgb),
    speed: DEFAULT_STATE.speed,
    intensity: DEFAULT_STATE.intensity
  });
  
  // Update ref when inputs change
  useEffect(() => {
    stateRef.current = systemState;
  }, [systemState]);

  // Rule Evaluation Engine
  const evaluateRules = (currentState: SystemState): BreathingState => {
    // 1. Find all matching rules
    const matches = BREATHING_RULES.filter(rule => {
      try {
        return rule.condition(currentState);
      } catch (e) {
        console.warn(`Breathing Rule ${rule.id} failed:`, e);
        return false;
      }
    });

    // 2. Sort by priority (descending)
    matches.sort((a, b) => b.priority - a.priority);

    // 3. Apply highest priority rule
    const winner = matches[0];
    const baseResult = winner ? winner.apply(currentState) : DEFAULT_STATE;

    // Merge with defaults to ensure completeness
    return {
      ...DEFAULT_STATE,
      ...baseResult,
      // Pattern changes are immediate, no interpolation
      pattern: baseResult.pattern || DEFAULT_STATE.pattern
    };
  };

  // Animation Loop
  useEffect(() => {
    let animationFrameId: number;
    let lastTime = 0;

    const animate = (time: number) => {
      if (lastTime === 0) lastTime = time;
      const deltaTime = (time - lastTime) / 1000;
      lastTime = time;

      // 1. Determine Target State
      const targetState = evaluateRules(buildEffectiveState(stateRef.current));

      // 2. Interpolate Values
      const lerpFactor = Math.min(1.0, deltaTime * 4.0); // 增加过渡速度 (从 2.0 提升到 4.0)

      // Speed
      const nextSpeed = lerp(currentValuesRef.current.speed, targetState.speed, lerpFactor);
      
      // Intensity
      const nextIntensity = lerp(currentValuesRef.current.intensity, targetState.intensity, lerpFactor);

      // Colors
      const currentRGBs = currentValuesRef.current.colors;
      const targetRGBs = targetState.colors.map(hexToRgb);
      
      const nextRGBs = currentRGBs.map((curr, i) => ({
        r: lerp(curr.r, targetRGBs[i].r, lerpFactor),
        g: lerp(curr.g, targetRGBs[i].g, lerpFactor),
        b: lerp(curr.b, targetRGBs[i].b, lerpFactor)
      }));

      // Update Refs
      currentValuesRef.current = {
        colors: nextRGBs,
        speed: nextSpeed,
        intensity: nextIntensity
      };

      // 3. Update React State (optimized)
      // We only update if significant change to avoid React overhead, 
      // but for pattern changes we update immediately.
      const nextColorsHex = nextRGBs.map(c => 
        rgbToHex(Math.round(c.r), Math.round(c.g), Math.round(c.b))
      ) as [string, string, string, string];

      setVisualState(prev => {
        if (
          prev.pattern !== targetState.pattern ||
          Math.abs(prev.speed - nextSpeed) > 0.05 ||
          Math.abs(prev.intensity - nextIntensity) > 0.05 ||
          Math.abs(nextRGBs[0].r - hexToRgb(prev.colors[0]).r) > 1.0
        ) {
          return {
            colors: nextColorsHex,
            speed: nextSpeed,
            pattern: targetState.pattern,
            intensity: nextIntensity
          };
        }
        return prev;
      });

      animationFrameId = requestAnimationFrame(animate);
    };

    animationFrameId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationFrameId);
  }, []);

  return visualState;
}
