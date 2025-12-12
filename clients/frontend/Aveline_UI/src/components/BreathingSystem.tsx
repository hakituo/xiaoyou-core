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
      // Always prioritize Emotion for colors as per user request
      const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
      
      // Calculate system load for potential modulation (optional, keeping it subtle or just purely emotion)
      // User explicitly asked for breathing light to be affected by emotion.
      // We will use the emotion colors directly.
      targetColors = emoConfig.colors;
      
      // Speed logic:
      // If locked (strong emotion trigger), use slow speed? 
      // User complained about "invariant" light. 
      // Let's make speed dynamic based on emotion "arousal" implied by the emotion type.
      // Angry/Excited -> Faster? Sad/Tired -> Slower?
      // For now, let's keep the user's preferred "slow" speed or adapt slightly.
      // The previous code had `targetSpeed = 6` for both branches.
      targetSpeed = 4; // Default to a breathing pace

      if (emotion === 'excited' || emotion === 'angry' || emotion === 'jealous') {
          targetSpeed = 2; // Faster breathing for high arousal
      } else if (emotion === 'lost' || emotion === 'wronged' || emotion === 'shy') {
          targetSpeed = 6; // Slow breathing for low arousal
      }

      /* Previous logic for reference (removed to fix "invariant" issue)
      if (Date.now() < emotionLockUntil) { ... } else { ... }
      */

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
