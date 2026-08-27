import React from 'react';
import { motion } from 'framer-motion';
import { BreathingState, BreathingPattern } from './types';

interface BreathingBackgroundProps {
  state: BreathingState;
}

const getTransition = (pattern: BreathingPattern, speed: number) => {
  switch (pattern) {
    case 'pulse':
      return {
        duration: speed,
        ease: [0.4, 0.0, 0.2, 1], // Sharp attack
        repeat: Infinity,
        repeatType: 'reverse' as const
      };
    case 'heartbeat':
      return {
        duration: speed, // Total cycle
        times: [0, 0.15, 0.3, 0.45, 1], // Keyframes
        repeat: Infinity,
        ease: "easeInOut"
      };
    case 'flicker':
      return {
        duration: 0.1,
        repeat: Infinity,
        repeatType: 'reverse' as const,
        ease: "linear"
      };
    case 'chaotic':
      return {
        duration: speed * 0.5,
        repeat: Infinity,
        repeatType: 'mirror' as const,
        ease: "anticipate"
      };
    case 'stable':
    case 'sine':
    default:
      return {
        duration: speed,
        repeat: Infinity,
        repeatType: 'mirror' as const,
        ease: 'easeInOut'
      };
  }
};

const getAnimate = (pattern: BreathingPattern, intensity: number) => {
  const baseOpacity = [0.3 * intensity, 0.6 * intensity];
  const baseScale = [1, 1.1];

  switch (pattern) {
    case 'heartbeat':
      return {
        scale: [1, 1.2, 1, 1.1, 1],
        opacity: [0.3 * intensity, 0.8 * intensity, 0.3 * intensity, 0.6 * intensity, 0.3 * intensity]
      };
    case 'flicker':
      return {
        opacity: [0.2 * intensity, 0.8 * intensity, 0.1 * intensity, 0.9 * intensity]
      };
    default:
      return {
        opacity: baseOpacity,
        scale: baseScale
      };
  }
};

export const BreathingBackground = ({ state }: BreathingBackgroundProps) => {
  const { colors, speed, pattern, intensity } = state;
  
  // We use key to force re-render of animation when pattern changes
  // Otherwise Framer Motion might try to interpolate between incompatible variant types
  const animKey = `${pattern}`;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
       {/* Blob 1: Top Left */}
       <motion.div
         key={`b1-${animKey}`}
         className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full blur-[100px]"
         style={{ background: colors[0] }}
         animate={getAnimate(pattern, intensity)}
         transition={getTransition(pattern, speed)}
       />
       
       {/* Blob 2: Bottom Right - Delayed */}
       <motion.div
         key={`b2-${animKey}`}
         className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full blur-[100px]"
         style={{ background: colors[1] }}
         animate={getAnimate(pattern, intensity)}
         transition={{ 
           ...getTransition(pattern, speed), 
           // @ts-ignore
           delay: speed * 0.25 
         }}
       />
       
       {/* Blob 3: Center - More subtle */}
       <motion.div
         key={`b3-${animKey}`}
         className="absolute top-[40%] left-[40%] w-[40%] h-[40%] rounded-full blur-[80px]"
         style={{ background: colors[3] }}
         animate={getAnimate(pattern, intensity * 0.7)}
         transition={{ 
           ...getTransition(pattern, speed), 
           // @ts-ignore
           delay: speed * 0.45 
         }}
       />
    </div>
  );
};
