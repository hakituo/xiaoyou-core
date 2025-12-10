import React from 'react';
import { Activity, Heart, Zap, Coffee, CloudRain, AlertCircle, Sparkles, Frown, VenetianMask } from 'lucide-react';
import { EmotionType } from '../types';
import { EMOTIONS } from '../utils/emotion';

interface EmotionWidgetProps {
  emotion: EmotionType;
  sidebarOpen: boolean;
}

const EmotionWidget = ({ emotion, sidebarOpen }: EmotionWidgetProps) => {
  const config = EMOTIONS[emotion] || EMOTIONS.neutral;
  
  // Map emotion to icon
  const getIcon = () => {
    switch (emotion) {
      case 'happy': return <Heart className="text-pink-400" size={18} />;
      case 'excited': return <Zap className="text-yellow-400" size={18} />;
      case 'angry': return <AlertCircle className="text-red-400" size={18} />;
      case 'lost': return <CloudRain className="text-blue-400" size={18} />;
      case 'neutral': return <Coffee className="text-gray-400" size={18} />;
      case 'shy': return <Sparkles className="text-pink-300" size={18} />;
      case 'wronged': return <Frown className="text-blue-300" size={18} />;
      case 'coquetry': return <Heart className="text-rose-400" size={18} />;
      case 'jealous': return <VenetianMask className="text-purple-400" size={18} />;
      default: return <Activity className="text-white/60" size={18} />;
    }
  };

  return (
    <div className={`
      flex items-center gap-3 p-3 rounded-xl bg-white/5 border border-white/5 transition-all duration-300 mb-2
      ${sidebarOpen ? 'justify-start' : 'justify-center'}
    `}>
      <div className="relative flex items-center justify-center w-8 h-8 rounded-full bg-white/5">
        {getIcon()}
        {/* Subtle glow effect based on emotion color */}
        <div 
          className="absolute inset-0 rounded-full opacity-20 animate-pulse" 
          style={{ backgroundColor: config.colors[0], filter: 'blur(8px)' }}
        ></div>
      </div>
      
      {sidebarOpen && (
        <div className="flex flex-col">
          <span className="text-[10px] text-white/40 uppercase tracking-wider font-bold">Current Mood</span>
          <span className="text-sm font-medium transition-colors duration-500" style={{ color: config.colors[1] }}>
            {config.label}
          </span>
        </div>
      )}
    </div>
  );
};

export default EmotionWidget;
