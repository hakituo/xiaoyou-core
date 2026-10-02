import React from 'react';
import { motion } from 'framer-motion';
import { EmotionType } from '../types';
import { EMOTIONS } from '../utils/emotion';
import { BreathingPattern } from '../systems/BreathingSystem';
import { formatDisplayLabel } from '../utils/text';

interface EmotionWidgetProps {
  emotion: EmotionType;
  sidebarOpen: boolean;
  lifeStatus?: any;
  colors: [string, string, string, string];
  speed: number;
  pattern?: BreathingPattern;
  emotionMix?: Record<string, number>;
}

const getWidgetAnimation = (pattern: BreathingPattern = 'sine', speed: number) => {
  switch (pattern) {
    case 'heartbeat':
      return {
        scale: [1, 1.3, 1, 1.15, 1],
        opacity: [0.8, 1, 0.8, 0.9, 0.8],
        transition: { duration: speed, repeat: Infinity, ease: "easeInOut" }
      };
    case 'pulse':
      return {
        scale: [1, 1.4, 1],
        opacity: [0.7, 1, 0.7],
        transition: { duration: speed, repeat: Infinity, ease: [0.4, 0.0, 0.2, 1], repeatType: "reverse" as const }
      };
    case 'flicker':
      return {
        opacity: [0.5, 1, 0.3, 0.8],
        transition: { duration: 0.2, repeat: Infinity, repeatType: "reverse" as const }
      };
    case 'chaotic':
      return {
        scale: [1, 1.2, 0.9, 1.1, 1],
        opacity: [0.6, 1, 0.5, 0.9, 0.6],
        transition: { duration: speed * 0.8, repeat: Infinity, repeatType: "mirror" as const }
      };
    default: // sine/stable
      return {
        scale: [1, 1.25, 1],
        opacity: [0.8, 1, 0.8],
        transition: { duration: speed, repeat: Infinity, ease: "easeInOut" }
      };
  }
};

const EmotionWidget = ({ emotion, sidebarOpen, lifeStatus, colors, speed, pattern = 'sine', emotionMix }: EmotionWidgetProps) => {
  // 计算主导情绪
  const dominantEmotion = React.useMemo(() => {
    if (!emotionMix || Object.keys(emotionMix).length === 0) return emotion;
    
    let maxWeight = -1;
    let dominant = emotion;
    
    Object.entries(emotionMix).forEach(([emo, weight]) => {
      if (weight > maxWeight) {
        maxWeight = weight;
        dominant = emo as EmotionType;
      }
    });
    return dominant;
  }, [emotion, emotionMix]);

  const config = EMOTIONS[dominantEmotion] || EMOTIONS[emotion] || EMOTIONS.neutral;
  const energy = lifeStatus?.energy ?? 100;
  const anim = getWidgetAnimation(pattern, speed);
  
  const content = (
    <>
      <div className="relative flex items-center justify-center w-12 h-12 shrink-0">
          {/* 1. 底层氛围光 (Steady Aura) */}
          <motion.div 
            className="absolute w-8 h-8 rounded-full blur-2xl opacity-30"
            style={{ backgroundColor: colors[1] }}
            animate={{
              scale: [1, 1.3, 1],
              opacity: [0.2, 0.4, 0.2]
            }}
            transition={{
              duration: speed * 4,
              repeat: Infinity,
              ease: "easeInOut"
            }}
          />

          {/* 2. 核心棱镜 (The Prism) */}
          <div className="relative w-6 h-6 flex items-center justify-center transition-all duration-300 group-hover:scale-110">
            <motion.div 
              className="absolute inset-0 rotate-45 border transition-all duration-500 group-hover:border-amber-400/80 group-hover:shadow-[0_0_20px_rgba(251,191,36,0.6)]"
              style={{ 
                borderColor: `${colors[0]}77`,
                backgroundColor: `${colors[1]}22`,
                boxShadow: `0 0 20px ${colors[1]}22`
              }}
              animate={{
                scale: [1, 1.1, 1],
                opacity: [0.7, 1, 0.7]
              }}
              transition={{
                duration: speed * 4,
                repeat: Infinity,
                ease: "easeInOut"
              }}
            />

            {/* 3. 内部折射层 (Refraction Layer) */}
            <motion.div 
              className="absolute inset-[1px] rotate-45 overflow-hidden transition-all duration-500"
              style={{ 
                background: `linear-gradient(135deg, ${colors[0]}33, transparent, ${colors[1]}33)`
              }}
            >
              <motion.div 
                className="absolute inset-[-150%] bg-gradient-to-tr from-transparent via-white/40 to-transparent"
                animate={{
                  transform: ["translateX(-30%) translateY(-30%)", "translateX(30%) translateY(30%)"]
                }}
                transition={{
                  duration: speed * 8,
                  repeat: Infinity,
                  ease: "easeInOut"
                }}
              />
            </motion.div>

          {/* 4. 核心光点 (Crystal Core) */}
          <motion.div 
            className="w-2.5 h-2.5 rotate-45 z-10"
            style={{ 
              backgroundColor: '#fff',
              boxShadow: `0 0 15px #fff, 0 0 30px ${colors[0]}`,
            }}
            animate={{
               scale: [0.8, 1.3, 0.8],
               opacity: [0.9, 1, 0.9]
            }}
            transition={{
              duration: speed * 2,
              repeat: Infinity,
              ease: "easeInOut"
            }}
          />
          </div>
        </div>
      
      {sidebarOpen && (
        <div className="flex-1 min-w-0 flex flex-col justify-center ml-1">
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="font-cinzel font-bold text-xl tracking-[0.2em] text-white group-hover:text-amber-400 transition-all duration-300 drop-shadow-[0_0_10px_rgba(255,255,255,0.3)]" style={{ fontFamily: "'Cinzel', serif" }}>
              {formatDisplayLabel('AVELINE')}
            </span>
            <span className="text-xs font-mono font-medium text-white/50 group-hover:text-amber-400/80 transition-colors duration-300">100%</span>
          </div>
          <div className="space-y-1.5">
            <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden relative border border-white/5">
              <motion.div 
                className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent"
                animate={{ x: ['-100%', '100%'] }}
                transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
              />
              <div className="absolute inset-y-0 left-0 bg-white/40 shadow-[0_0_8px_rgba(255,255,255,0.2)] transition-all duration-500 group-hover:bg-amber-400/50 group-hover:shadow-[0_0_10px_rgba(251,191,36,0.3)]" style={{ width: '100%' }} />
            </div>
            <div className="flex justify-end">
              <span className="text-[11px] font-mono font-semibold text-white/40 uppercase tracking-widest transition-colors duration-300 group-hover:text-white/80">
                {config.label}
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );

  return (
    <div className="group flex items-center w-full transition-all duration-300 relative">
      <div className="relative flex items-center gap-4 min-w-0 w-full z-10 transition-transform duration-300 group-active:scale-[0.98]">
        {content}
      </div>
    </div>
  );
};

export default EmotionWidget;
