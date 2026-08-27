import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Users, 
  Heart, 
  Sparkles,
  ChevronDown,
  ChevronRight,
  Clock,
  TrendingUp,
  MessageCircle,
  Zap,
  Utensils,
  Smile
} from 'lucide-react';
import { ActorLifeState } from '../types';
import { InfoCard } from './InfoCard';

interface CirclePanelProps {
  groupMode: boolean;
  onToggleGroupMode: () => void;
  actorLifeStates: Record<string, ActorLifeState>;
  relationships: Record<string, number>;
  avelineThread: Array<{ id: string; text: string; timestamp: number }>;
  lingThread: Array<{ id: string; text: string; timestamp: number }>;
  colors: [string, string, string, string];
}

const Tag = ({ text, color = "emerald" }: { text: string, color?: "emerald" | "blue" | "purple" | "rose" | "cyan" | "pink" }) => {
  const colors = {
    emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300",
    blue: "bg-blue-500/10 border-blue-500/20 text-blue-300",
    purple: "bg-purple-500/10 border-purple-500/20 text-purple-300",
    rose: "bg-rose-500/10 border-rose-500/20 text-rose-300",
    cyan: "bg-cyan-500/10 border-cyan-500/20 text-cyan-300",
    pink: "bg-pink-500/10 border-pink-500/20 text-pink-300"
  };

  return (
    <span className={`px-2 py-1 text-[10px] rounded border ${colors[color]} font-mono`}>
      {text}
    </span>
  );
};

const CollapsibleSection = ({
  title,
  icon,
  isOpen,
  onToggle,
  children,
  className = "",
}: {
  title: string;
  icon?: React.ReactNode;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  className?: string;
}) => (
  <div className={`glass-card rounded-2xl overflow-hidden ${className}`}>
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center justify-between px-5 py-4 hover:bg-white/5 transition-colors"
    >
      <div className="flex items-center gap-2">
        {icon}
        <div className="text-xs font-bold text-white/40 uppercase tracking-widest">{title}</div>
      </div>
      <div className="text-white/40">
        {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </div>
    </button>
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.25 }}
          className="px-5 pb-5"
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  </div>
);

const MetricBar = ({ label, value, color = "emerald" }: { label: string; value: number; color?: string }) => {
  const percent = Math.min(100, Math.max(0, value));
  const colorClasses: Record<string, string> = {
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    cyan: "bg-cyan-500",
    pink: "bg-pink-500",
    purple: "bg-purple-500",
  };

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-white/40">{label}</span>
        <span className="text-white/70">{Math.round(value)}</span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className={`h-full rounded-full ${colorClasses[color] || colorClasses.emerald}`}
        />
      </div>
    </div>
  );
};

const MemberStatusCard = ({ 
  name, 
  role,
  color,
  stats,
  messageCount,
  isExpanded,
  onToggle
}: { 
  name: string;
  role: string;
  color: "cyan" | "pink";
  stats?: ActorLifeState;
  messageCount: number;
  isExpanded: boolean;
  onToggle: () => void;
}) => {
  const defaultStats: ActorLifeState = { hunger: 100, energy: 100, mood_score: 80 };
  const s: ActorLifeState = stats || defaultStats;
  const colorMap = {
    cyan: { bg: 'bg-cyan-500/5', border: 'border-cyan-500/10', text: 'text-cyan-400', gradient: 'from-cyan-500/30 to-cyan-500/10' },
    pink: { bg: 'bg-pink-500/5', border: 'border-pink-500/10', text: 'text-pink-400', gradient: 'from-pink-500/30 to-pink-500/10' },
  };
  const c = colorMap[color];

  return (
    <div className={`${c.bg} ${c.border} border rounded-xl overflow-hidden`}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full p-4 flex items-center gap-4 text-left"
      >
        <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${c.gradient} flex items-center justify-center font-bold border ${c.border}`}>
          <span className={c.text}>{name.charAt(0)}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{name}</span>
            <Tag text={role} color={color} />
          </div>
          <div className="flex items-center gap-4 mt-1 text-[10px] text-white/40 font-mono">
            <span className="flex items-center gap-1">
              <MessageCircle size={10} />
              {messageCount} msgs
            </span>
            <span className="flex items-center gap-1">
              <Smile size={10} />
              {Math.round(s.mood_score)}% mood
            </span>
          </div>
        </div>
        <div className="text-white/30">
          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-0 border-t border-white/5">
              <div className="pt-4 grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-1 text-[10px] text-white/40">
                    <Utensils size={10} />
                    <span>SATIETY</span>
                  </div>
                  <div className={`text-lg font-mono ${c.text}`}>{Math.round(s.hunger)}</div>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-1 text-[10px] text-white/40">
                    <Zap size={10} />
                    <span>ENERGY</span>
                  </div>
                  <div className={`text-lg font-mono ${c.text}`}>{Math.round(s.energy)}</div>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-1 text-[10px] text-white/40">
                    <Smile size={10} />
                    <span>MOOD</span>
                  </div>
                  <div className={`text-lg font-mono ${c.text}`}>{Math.round(s.mood_score)}</div>
                </div>
              </div>
              <div className="mt-3 space-y-2">
                <MetricBar label="SATIETY" value={s.hunger} color={color} />
                <MetricBar label="ENERGY" value={s.energy} color={color} />
                <MetricBar label="MOOD" value={s.mood_score} color={color} />
              </div>
              {s.happiness !== undefined && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <MetricBar label="HAPPINESS" value={s.happiness} color="amber" />
                  {s.social_desire !== undefined && (
                    <MetricBar label="SOCIAL_DESIRE" value={s.social_desire} color="purple" />
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const RelationshipMeter = ({ score }: { score: number }) => {
  const getRelationshipLabel = (s: number) => {
    if (s >= 80) return { label: 'SOULMATE', emoji: '💕' };
    if (s >= 60) return { label: 'CLOSE', emoji: '💖' };
    if (s >= 40) return { label: 'FRIEND', emoji: '💗' };
    if (s >= 20) return { label: 'ACQUAINTED', emoji: '💙' };
    return { label: 'STRANGER', emoji: '🤍' };
  };

  const { label, emoji } = getRelationshipLabel(score);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Heart size={14} className="text-pink-400/60" />
          <span className="text-xs font-mono text-white/50">Aveline ↔ Ling</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm">{emoji}</span>
          <Tag text={label} color="pink" />
        </div>
      </div>

      <div className="relative">
        <div className="h-2 bg-white/5 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, Math.max(0, score))}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className="h-full rounded-full"
            style={{
              background: `linear-gradient(90deg, #ec4899, #8b5cf6)`,
            }}
          />
        </div>
        <div className="flex justify-between mt-1.5 text-[9px] text-white/30 font-mono">
          <span>0</span>
          <span className="text-pink-300 font-medium">{Math.round(score)}</span>
          <span>100</span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-[10px] text-white/40 font-mono">
        <TrendingUp size={10} className="text-emerald-400" />
        <span>持续互动可提升亲密度</span>
      </div>
    </div>
  );
};

const GroupModeToggle = ({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) => (
  <div className={`glass-card rounded-2xl p-5 transition-all duration-300 ${enabled ? 'border-emerald-500/30 bg-emerald-500/5' : ''}`}>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${enabled ? 'bg-emerald-500/20' : 'bg-white/5'}`}>
          <Users size={18} className={enabled ? 'text-emerald-400' : 'text-white/40'} />
        </div>
        <div>
          <div className="text-sm font-semibold text-white">群聊模式</div>
          <div className="text-[10px] text-white/40 font-mono mt-0.5">
            {enabled ? 'ENABLED · 多成员可见' : 'DISABLED · 单成员模式'}
          </div>
        </div>
      </div>

      <button
        onClick={onToggle}
        className={`relative w-12 h-7 rounded-full transition-all duration-300 ${enabled ? 'bg-emerald-500' : 'bg-white/10'}`}
      >
        <motion.div
          animate={{ x: enabled ? 20 : 2 }}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
          className="absolute top-0.5 w-6 h-6 rounded-full bg-white shadow-lg"
        />
      </button>
    </div>

    <AnimatePresence>
      {enabled && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="mt-4 pt-4 border-t border-white/10"
        >
          <div className="flex flex-wrap gap-2">
            <Tag text="你" color="blue" />
            <Tag text="Aveline" color="cyan" />
            <Tag text="Ling" color="pink" />
          </div>
          <div className="mt-3 text-[10px] text-white/30 font-mono">
            QQ 端仍仅显示 Aveline 回复
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  </div>
);

const MessageStats = ({ avelineCount, lingCount }: { avelineCount: number; lingCount: number }) => (
  <div className="grid grid-cols-2 gap-3">
    <div className="bg-cyan-500/5 border border-cyan-500/10 rounded-xl p-4 text-center">
      <div className="text-2xl font-bold text-cyan-400 font-mono">{avelineCount}</div>
      <div className="text-[10px] text-cyan-300/50 font-mono mt-1 uppercase tracking-wider">Aveline</div>
    </div>
    <div className="bg-pink-500/5 border border-pink-500/10 rounded-xl p-4 text-center">
      <div className="text-2xl font-bold text-pink-400 font-mono">{lingCount}</div>
      <div className="text-[10px] text-pink-300/50 font-mono mt-1 uppercase tracking-wider">Ling</div>
    </div>
  </div>
);

const CirclePanel: React.FC<CirclePanelProps> = ({
  groupMode,
  onToggleGroupMode,
  actorLifeStates,
  relationships,
  avelineThread,
  lingThread,
  colors,
}) => {
  const [expandedMember, setExpandedMember] = useState<string | null>('aveline');
  const [sections, setSections] = useState({
    members: true,
    relationship: true,
    stats: true,
  });

  const resolveRelationshipScore = (rels: Record<string, number>): number => {
    const pairKeys = ['aveline|ling', 'ling|aveline'];
    for (const key of pairKeys) {
      const v = rels[key];
      if (typeof v === 'number' && Number.isFinite(v)) return v;
    }
    const first = Object.values(rels).find(v => typeof v === 'number' && Number.isFinite(v));
    return typeof first === 'number' ? first : 0;
  };

  const relationshipScore = resolveRelationshipScore(relationships);

  return (
    <div className="flex-1 p-4 sm:p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-4xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-center justify-between border-b border-white/10 pb-6">
          <div className="flex items-center gap-3">
            <div 
              className="p-2.5 rounded-xl border"
              style={{ 
                background: `linear-gradient(135deg, ${colors[0]}20, ${colors[1]}20)`,
                borderColor: `${colors[0]}30`
              }}
            >
              <Users className="text-white/80" size={20} />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white font-display">
                CIRCLE <span style={{ color: colors[0] }}>MATRIX</span>
              </h1>
              <div className="text-[10px] text-white/40 font-mono tracking-wider uppercase">Social Interaction System</div>
            </div>
          </div>
        </div>

        {/* Group Mode Toggle */}
        <GroupModeToggle enabled={groupMode} onToggle={onToggleGroupMode} />

        {/* Members Section */}
        <CollapsibleSection
          title="MEMBER STATUS"
          icon={<Users size={14} className="text-cyan-400/60" />}
          isOpen={sections.members}
          onToggle={() => setSections(prev => ({ ...prev, members: !prev.members }))}
        >
          <div className="space-y-3">
            <MemberStatusCard
              name="Aveline"
              role="ACTIVE"
              color="cyan"
              stats={actorLifeStates?.aveline}
              messageCount={avelineThread.length}
              isExpanded={expandedMember === 'aveline'}
              onToggle={() => setExpandedMember(prev => prev === 'aveline' ? null : 'aveline')}
            />
            <MemberStatusCard
              name="Ling"
              role="BACKGROUND"
              color="pink"
              stats={actorLifeStates?.ling}
              messageCount={lingThread.length}
              isExpanded={expandedMember === 'ling'}
              onToggle={() => setExpandedMember(prev => prev === 'ling' ? null : 'ling')}
            />
          </div>
        </CollapsibleSection>

        {/* Relationship Section */}
        <CollapsibleSection
          title="RELATIONSHIP BOND"
          icon={<Heart size={14} className="text-pink-400/60" />}
          isOpen={sections.relationship}
          onToggle={() => setSections(prev => ({ ...prev, relationship: !prev.relationship }))}
        >
          <RelationshipMeter score={relationshipScore} />
        </CollapsibleSection>

        {/* Stats Section */}
        <CollapsibleSection
          title="SESSION STATISTICS"
          icon={<Clock size={14} className="text-amber-400/60" />}
          isOpen={sections.stats}
          onToggle={() => setSections(prev => ({ ...prev, stats: !prev.stats }))}
        >
          <MessageStats 
            avelineCount={avelineThread.length} 
            lingCount={lingThread.length} 
          />
        </CollapsibleSection>

        {/* Tips Card */}
        <InfoCard title="INTERACTION GUIDE" className="bg-amber-900/5 border-amber-500/10">
          <div className="space-y-3 text-xs text-white/50 leading-relaxed">
            <div className="flex items-start gap-2">
              <MessageCircle size={12} className="text-cyan-400/60 mt-0.5 shrink-0" />
              <span>开启群聊模式后，你可以在网页端看到Ling的后台消息。</span>
            </div>
            <div className="flex items-start gap-2">
              <Heart size={12} className="text-pink-400/60 mt-0.5 shrink-0" />
              <span>与成员互动可以提升亲密度，解锁更多互动内容。</span>
            </div>
            <div className="flex items-start gap-2">
              <Sparkles size={12} className="text-amber-400/60 mt-0.5 shrink-0" />
              <span>系统整体状态请查看 Status 面板。</span>
            </div>
          </div>
        </InfoCard>
      </div>
    </div>
  );
};

export default CirclePanel;
