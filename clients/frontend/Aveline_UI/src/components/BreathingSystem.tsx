import React, { useEffect, useRef, useState } from 'react';
import { EmotionType } from '../types';
import { EMOTIONS, calculateMixedColors, hexToRgb, rgbToHex } from '../utils/emotion';

// Helper for linear interpolation
const lerp = (start: number, end: number, factor: number) => start + (end - start) * factor;

/**
 * Hook to calculate breathing light colors and animation speed based on system stats and emotion.
 * Replaces the color logic previously in useStatus.
 */
export function useBreathingColors(
  stats: { cpu: number; gpu: number; memory: number },
  emotion: EmotionType,
  emotionLockUntil: number
) {
  const [currentColors, setCurrentColors] = useState<[string, string, string, string]>(EMOTIONS.neutral.colors);
  const [currentSpeed, setCurrentSpeed] = useState<number>(3); // Default speed in seconds
  
  // Store high-precision RGB values to avoid rounding errors causing "stuck" colors
  const colorValuesRef = useRef(EMOTIONS.neutral.colors.map(hexToRgb));
  const speedRef = useRef(3);

  // Refs for animation loop to access latest state without dependencies
  const stateRef = useRef({
    stats,
    emotion,
    emotionLockUntil
  });
  
  useEffect(() => {
    stateRef.current = { stats, emotion, emotionLockUntil };
  }, [stats, emotion, emotionLockUntil]);

  // Animation Loop for Color Transition
  useEffect(() => {
    let animationFrameId: number;

    const animate = () => {
      const { stats, emotion, emotionLockUntil } = stateRef.current;
      let targetColors: [string, string, string, string];
      let targetSpeed: number;

      // 1. Determine Target Colors & Speed
      // Check if we are in a "Locked Emotion" state (triggered by LLM output like {happy})
      if (Date.now() < emotionLockUntil) {
        // Locked: Use current emotion's colors
        const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
        targetColors = emoConfig.colors;
        // User requested constant slow speed, ignoring emotion-specific speed
        targetSpeed = 6; 
      } else {
        // Unlocked: Calculate based on system stats (Ambient Mode)
        const c = Math.max(0, Math.min(100, stats.cpu));
        const g = Math.max(0, Math.min(100, stats.gpu));
        const m = Math.max(0, Math.min(100, stats.memory));
        const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
        
        // Adjust weights for more dynamic response
        const w_excited = clamp01((g - 30) / 70) * 0.6 + clamp01((c - 40) / 60) * 0.4;
        const w_angry = clamp01((m - 70) / 30) * 0.8 + clamp01((c - 85) / 15) * 0.2;
        const w_lost = clamp01((m - 85) / 15) * 0.8;
        
        // Happy if balanced load
        const load = (c + g + m) / 3;
        const w_happy = (load > 20 && load < 60) ? 0.5 : 0;
        
        const base = 0.3; // Always some neutral base
        
        const weights: Record<string, number> = {
          neutral: base,
          excited: w_excited,
          angry: w_angry,
          lost: w_lost,
          happy: w_happy,
          shy: 0,
          jealous: 0,
          wronged: 0,
          coquetry: 0
        };
        
        targetColors = calculateMixedColors(weights);
        // User requested constant slow speed
        targetSpeed = 6;
      }

      // 2. Smoothly Interpolate Current -> Target
      const colorFactor = 0.05; 
      const speedFactor = 0.05; // Even slower transition for speed (though it's constant now)

      // Interpolate Speed
      const nextSpeed = lerp(speedRef.current, targetSpeed, speedFactor);
      speedRef.current = nextSpeed;

      // Interpolate Colors
      const currentRGBs = colorValuesRef.current;
      const targetRGBs = targetColors.map(hexToRgb);
      
      const nextRGBs = currentRGBs.map((curr, i) => ({
        r: lerp(curr.r, targetRGBs[i].r, colorFactor),
        g: lerp(curr.g, targetRGBs[i].g, colorFactor),
        b: lerp(curr.b, targetRGBs[i].b, colorFactor)
      }));
      
      // Update ref with new float values
      colorValuesRef.current = nextRGBs;

      // Convert to Hex for UI
      const nextColorsHex = nextRGBs.map(c => rgbToHex(Math.round(c.r), Math.round(c.g), Math.round(c.b))) as [string, string, string, string];
      
      setCurrentColors(nextColorsHex);
      setCurrentSpeed(nextSpeed);
      
      animationFrameId = requestAnimationFrame(animate);
    };

    animationFrameId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationFrameId);
  }, []); // Run once

  return { colors: currentColors, speed: currentSpeed };
}

/**
 * Component for the background breathing blobs.
 * Now supports dynamic speed and subtle drift animation.
 */
export const BreathingBackground = ({ colors, speed }: { colors: [string, string, string, string], speed: number }) => {
  // Use inline styles for dynamic animation duration
  const pulseStyle = {
    animationDuration: `${speed}s`,
  };

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
       {/* Blob 1: Top Left */}
       <div 
         className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full blur-[150px] opacity-70 mix-blend-screen animate-pulse transition-all duration-1000"
         style={{ ...pulseStyle, background: colors[0] }} 
       />
       
       {/* Blob 2: Bottom Right - Delayed */}
       <div 
         className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full blur-[150px] opacity-60 mix-blend-screen animate-pulse transition-all duration-1000"
         style={{ ...pulseStyle, background: colors[1], animationDelay: `${speed * 0.5}s` }} 
       />
       
       {/* Blob 3: Center - More subtle */}
       <div 
         className="absolute top-[40%] left-[40%] w-[40%] h-[40%] rounded-full blur-[120px] opacity-40 mix-blend-screen animate-pulse transition-all duration-1000"
         style={{ ...pulseStyle, background: colors[3], animationDelay: `${speed * 0.75}s` }} 
       />
    </div>
  );
};
