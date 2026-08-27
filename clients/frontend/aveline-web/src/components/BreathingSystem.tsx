import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
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
  emotionLockUntil: number,
  emotionMix?: Record<string, number>
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
    emotionLockUntil,
    emotionMix
  });
  
  useEffect(() => {
    stateRef.current = { stats, emotion, emotionLockUntil, emotionMix };
  }, [stats, emotion, emotionLockUntil, emotionMix]);

  // Animation Loop for Color Transition
  useEffect(() => {
    let animationFrameId: number;
    let lastTime = 0;

    const animate = (time: number) => {
      if (lastTime === 0) lastTime = time;
      const deltaTime = (time - lastTime) / 1000; // seconds
      lastTime = time;

      const { emotion, emotionMix } = stateRef.current;
      let targetColors: [string, string, string, string];
      let targetSpeed: number;

      // 1. Determine Target Colors & Speed
      if (emotionMix && Object.keys(emotionMix).length > 0) {
          // Use Mixed Emotion System
          targetColors = calculateMixedColors(emotionMix);
          
          // Calculate Weighted Speed
          let totalSpeed = 0;
          let totalWeight = 0;
          Object.entries(emotionMix).forEach(([k, w]) => {
             const key = k as EmotionType;
             if (EMOTIONS[key]) {
                 totalSpeed += EMOTIONS[key].speed * w;
                 totalWeight += w;
             }
          });
          targetSpeed = totalWeight > 0 ? totalSpeed / totalWeight : 4;

      } else {
          // Fallback to Single Emotion
          const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
          targetColors = emoConfig.colors;
          
          targetSpeed = 4; // Default
          if (emotion === 'excited' || emotion === 'angry' || emotion === 'jealous') {
              targetSpeed = 2; // Fast
          } else if (emotion === 'lost' || emotion === 'wronged' || emotion === 'shy') {
              targetSpeed = 6; // Slow
          }
      }

      // 2. Smoothly Interpolate Current -> Target
      // Use deltaTime to make transition framerate-independent
      // We want to reach target in ~1-2 seconds
      const lerpFactor = Math.min(1.0, deltaTime * 2.0); 

      // Interpolate Speed
      const nextSpeed = lerp(speedRef.current, targetSpeed, lerpFactor);
      speedRef.current = nextSpeed;

      // Interpolate Colors
      const currentRGBs = colorValuesRef.current;
      const targetRGBs = targetColors.map(hexToRgb);
      
      const nextRGBs = currentRGBs.map((curr, i) => ({
        r: lerp(curr.r, targetRGBs[i].r, lerpFactor),
        g: lerp(curr.g, targetRGBs[i].g, lerpFactor),
        b: lerp(curr.b, targetRGBs[i].b, lerpFactor)
      }));
      
      // Update ref with new float values
      colorValuesRef.current = nextRGBs;

      // Convert to Hex for UI
      const nextColorsHex = nextRGBs.map(c => rgbToHex(Math.round(c.r), Math.round(c.g), Math.round(c.b))) as [string, string, string, string];
      
      // Only trigger re-render if colors changed significantly (optimization)
      // Check first color's R value difference
      if (Math.abs(nextRGBs[0].r - currentRGBs[0].r) > 0.5 || Math.abs(nextSpeed - currentSpeed) > 0.1) {
          setCurrentColors(nextColorsHex);
          setCurrentSpeed(nextSpeed);
      } else {
          // If stabilized, we still set it to ensure final value is accurate
          setCurrentColors(nextColorsHex);
          setCurrentSpeed(nextSpeed);
      }
      
      animationFrameId = requestAnimationFrame(animate);
    };

    animationFrameId = requestAnimationFrame(animate);

    return () => cancelAnimationFrame(animationFrameId);
  }, []); // Run once, depend on stateRef

  return { colors: currentColors, speed: currentSpeed };
}

/**
 * Component for the background breathing blobs.
 * Now supports dynamic speed and subtle drift animation.
 */
export const BreathingBackground = ({ colors, speed }: { colors: [string, string, string, string], speed: number }) => {
  const baseTransition = {
    duration: Math.max(0.8, speed),
    repeat: Infinity,
    repeatType: 'mirror',
    ease: 'easeInOut'
  } as const;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
       {/* Blob 1: Top Left */}
       <motion.div
         className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full blur-[100px] opacity-50"
         style={{ background: colors[0] }}
         animate={{ opacity: [0.4, 0.6], scale: [1, 1.06] }}
         transition={baseTransition}
       />
       
       {/* Blob 2: Bottom Right - Delayed */}
       <motion.div
         className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full blur-[100px] opacity-40"
         style={{ background: colors[1] }}
         animate={{ opacity: [0.3, 0.5], scale: [1.02, 1.1] }}
         transition={{ ...baseTransition, delay: Math.max(0, speed * 0.25) }}
       />
       
       {/* Blob 3: Center - More subtle */}
       <motion.div
         className="absolute top-[40%] left-[40%] w-[40%] h-[40%] rounded-full blur-[80px] opacity-30"
         style={{ background: colors[3] }}
         animate={{ opacity: [0.2, 0.4], scale: [1, 1.05] }}
         transition={{ ...baseTransition, delay: Math.max(0, speed * 0.45) }}
       />
    </div>
  );
};
