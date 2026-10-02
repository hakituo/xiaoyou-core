import React from 'react';
import { motion } from 'framer-motion';
import { Zap, Utensils, Droplet, Heart, Activity } from 'lucide-react';
import { EmotionType } from '../types';

interface PetStatsPanelProps {
  stats: any; // Flexible to handle both old and new structures
  emotion: EmotionType;
  onClose?: () => void;
}

const StatBar = ({ label, value, icon: Icon, color, max = 100 }: { label: string, value: number, icon: any, color: string, max?: number }) => {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  
  return (
    <div className="mb-3">
      <div className="flex justify-between items-center mb-1">
        <div className="flex items-center gap-2 text-white/80">
          <Icon size={14} className={color} />
          <span className="text-[10px] font-medium uppercase tracking-wider">{label}</span>
        </div>
        <span className="text-[10px] font-mono text-white/50">{Math.round(value)}/{max}</span>
      </div>
      <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden border border-white/10">
        <motion.div 
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 1, ease: "easeOut" }}
          className={`h-full ${color.replace('text-', 'bg-')} shadow-[0_0_10px_currentColor]`}
        />
      </div>
    </div>
  );
};

const PetStatsPanel: React.FC<PetStatsPanelProps> = ({ stats, emotion, onClose }) => {
  // Extract stats supporting both flat and nested structures
  const life = stats.life || stats;
  const bio = stats.bio || {};

  const energy = life.energy ?? 100;
  const hunger = life.hunger ?? 100;
  const thirst = life.thirst ?? 100;

  // Map emotion to color
  const getEmotionColor = (emo: string) => {
    const colors: Record<string, string> = {
      neutral: 'text-blue-400',
      happy: 'text-green-400',
      shy: 'text-pink-400',
      angry: 'text-red-500',
      jealous: 'text-yellow-400',
      wronged: 'text-indigo-400',
      coquetry: 'text-purple-400',
      lost: 'text-gray-400',
      excited: 'text-orange-400',
    };
    return colors[emo] || 'text-blue-400';
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center z-[80] p-4 pointer-events-auto">
       <div 
        className="absolute inset-0 bg-black/20 backdrop-blur-sm" 
        onClick={onClose}
      />
      <motion.div
        initial={{ scale: 0.9, opacity: 0, y: 20 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.9, opacity: 0, y: 20 }}
        className="glass-card rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden"
      >
        {/* Header */}
        <div className="p-3 border-b border-white/10 flex justify-between items-center glass-panel">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-emerald-400" />
            <span className="font-bold text-white text-sm text-glow">Life & Bio System</span>
          </div>
          <div className="text-[10px] px-2 py-0.5 rounded glass-panel text-emerald-300 font-mono shadow-[0_0_10px_rgba(16,185,129,0.2)]">
            STATUS: {emotion.toUpperCase()}
          </div>
        </div>

        {/* Body */}
        <div className="p-4 grid grid-cols-1 gap-4">
          {/* Basic Needs */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 mb-2 uppercase tracking-widest">Physiological Needs</h3>
            <StatBar label="Energy" value={energy} icon={Zap} color="text-yellow-400" />
            <StatBar label="Hunger" value={hunger} icon={Utensils} color="text-orange-400" />
            <StatBar label="Thirst" value={thirst} icon={Droplet} color="text-cyan-400" />
          </div>

          {/* Bio System (if available) */}
          {Object.keys(bio).length > 0 && (
            <div className="border-t border-white/5 pt-3">
              <h3 className="text-xs font-semibold text-white/40 mb-2 uppercase tracking-widest">Neurotransmitters</h3>
              <div className="grid grid-cols-2 gap-x-4">
                <StatBar label="Dopamine" value={(bio.dopamine || 0) * 100} icon={Activity} color="text-pink-400" max={100} />
                <StatBar label="Serotonin" value={(bio.serotonin || 0) * 100} icon={Activity} color="text-blue-400" max={100} />
                <StatBar label="Norepinephrine" value={(bio.norepinephrine || 0) * 100} icon={Activity} color="text-purple-400" max={100} />
                <StatBar label="Oxytocin" value={(bio.oxytocin || 0) * 100} icon={Activity} color="text-rose-400" max={100} />
              </div>
            </div>
          )}

          {/* Mood */}
          <div>
             <h3 className="text-xs font-semibold text-white/40 mb-2 uppercase tracking-widest">Emotional State</h3>
             <StatBar 
               label="Mood" 
               value={life.mood_score ?? 80} 
               icon={Heart} 
               color={getEmotionColor(emotion)} 
             />
          </div>

          <div className="pt-2 border-t border-white/5 text-center">
            <p className="text-[10px] text-white/30 italic">
              "Keep my stats high to unlock special interactions!"
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default PetStatsPanel;
