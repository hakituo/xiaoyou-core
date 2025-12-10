import React from 'react';
import { motion } from 'framer-motion';
import { User, Fingerprint, Brain, Heart, Shield, Activity, Lock, Hash, GitCommit, List, Eye } from 'lucide-react';
import { InfoCard } from './InfoCard';

interface PersonaPanelProps {
  persona: any;
}

const Tag = ({ text, color = "emerald" }: { text: string, color?: "emerald" | "blue" | "purple" | "rose" }) => {
    const colors = {
        emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300",
        blue: "bg-blue-500/10 border-blue-500/20 text-blue-300",
        purple: "bg-purple-500/10 border-purple-500/20 text-purple-300",
        rose: "bg-rose-500/10 border-rose-500/20 text-rose-300"
    };

    return (
        <span className={`px-2 py-1 text-xs rounded border ${colors[color]} font-mono`}>
            {text}
        </span>
    );
};

const PersonaPanel = ({ persona }: PersonaPanelProps) => {
  if (!persona) {
    return (
        <div className="flex-1 flex items-center justify-center text-white/30 font-mono animate-pulse">
            LOADING CORE IDENTITY MATRIX...
        </div>
    );
  }

  const { identity, user_profile, backstory, personality } = persona;

  return (
    <div className="flex-1 p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-end justify-between border-b border-white/10 pb-6">
            <div>
                <h1 className="text-4xl font-bold tracking-tight text-white mb-2 font-display">
                    IDENTITY <span className="text-emerald-500">MATRIX</span>
                </h1>
                <div className="flex items-center gap-4 text-xs font-mono text-white/40">
                    <span className="flex items-center gap-1"><Hash size={12}/> ID: {identity?.name || "AVELINE"}</span>
                    <span className="flex items-center gap-1"><GitCommit size={12}/> VER: {identity?.version || "3.0.0"}</span>
                    <span className="flex items-center gap-1"><Lock size={12}/> ACCESS: LEVEL 5</span>
                </div>
            </div>
            <div className="text-right hidden md:block">
                 <div className="text-[10px] uppercase tracking-widest text-white/30 mb-1">System Status</div>
                 <div className="text-emerald-400 font-mono text-sm">OPERATIONAL // SYNCED</div>
            </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* Left Column: System Identity */}
            <div className="space-y-6">
                <InfoCard title="CORE SYSTEM IDENTITY" className="h-full">
                    <div className="space-y-6">
                        <div>
                            <div className="text-white/30 text-xs mb-2">DESIGNATION</div>
                            <div className="text-2xl font-bold text-white mb-1">{identity?.name} <span className="text-lg font-normal text-white/40">({identity?.cn_name})</span></div>
                            <p className="text-white/60 text-sm leading-relaxed">{identity?.core_identity?.status}</p>
                        </div>

                        <div>
                            <div className="text-white/30 text-xs mb-2">PRIMARY OBJECTIVE</div>
                            <div className="p-3 bg-emerald-500/5 border border-emerald-500/10 rounded-lg text-emerald-100 text-sm italic">
                                "{identity?.core_identity?.primary_objective}"
                            </div>
                        </div>

                        <div>
                            <div className="text-white/30 text-xs mb-2">PERSONALITY MODEL</div>
                            <div className="grid grid-cols-2 gap-4 mb-3">
                                <div className="p-2 bg-white/5 rounded border border-white/5">
                                    <div className="text-[10px] text-white/30">MBTI</div>
                                    <div className="text-lg font-mono text-white/80">{personality?.model?.MBTI}</div>
                                </div>
                                <div className="p-2 bg-white/5 rounded border border-white/5">
                                    <div className="text-[10px] text-white/30">ALIGNMENT</div>
                                    <div className="text-lg font-mono text-white/80">CHAOTIC GOOD</div>
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {personality?.traits?.map((t: any, i: number) => (
                                    <Tag key={i} text={t.name} color="purple" />
                                ))}
                            </div>
                        </div>

                        <div>
                             <div className="text-white/30 text-xs mb-2">CORE FEAR</div>
                             <div className="flex items-center gap-2 text-rose-400/80 text-sm">
                                <Shield size={14} />
                                {identity?.core_identity?.core_fear}
                             </div>
                        </div>
                    </div>
                </InfoCard>

                <InfoCard title="ORIGIN & BACKSTORY">
                     <div className="space-y-4">
                        <div className="flex items-start gap-4 pb-4 border-b border-white/5">
                            <div className="w-12 text-[10px] text-white/30 font-mono pt-1">ORIGIN</div>
                            <div className="flex-1 text-sm text-white/70">{backstory?.birthplace}</div>
                        </div>
                        <div className="flex items-start gap-4">
                             <div className="w-12 text-[10px] text-white/30 font-mono pt-1">EVENTS</div>
                             <div className="flex-1 space-y-3">
                                 {backstory?.turning_points?.map((tp: any, i: number) => (
                                     <div key={i} className="relative pl-4 border-l border-white/10">
                                         <div className="absolute -left-[3px] top-1.5 w-1.5 h-1.5 rounded-full bg-white/20"></div>
                                         <div className="text-xs font-bold text-white/80 mb-0.5">{tp.title}</div>
                                         <div className="text-[10px] text-white/50">{tp.summary}</div>
                                     </div>
                                 ))}
                             </div>
                        </div>
                     </div>
                </InfoCard>
            </div>

            {/* Right Column: User Perception (The Mirror) */}
            <div className="space-y-6">
                <InfoCard title="USER PERCEPTION MODEL" className="bg-blue-900/5 border-blue-500/10">
                     <div className="flex flex-col sm:flex-row items-start justify-between mb-6 gap-4">
                        <div className="flex flex-col">
                            <div className="text-xs text-blue-400/50 mb-1">CURRENT SUBJECT</div>
                            <div className="text-3xl font-bold text-white font-display tracking-tight">{user_profile?.name}</div>
                            <div className="flex items-center gap-2 mt-2">
                                <span className="text-[10px] px-1.5 py-0.5 bg-blue-500/10 rounded text-blue-400/60 border border-blue-500/10 font-mono">UID: 89757</span>
                                <span className="text-[10px] px-1.5 py-0.5 bg-blue-500/10 rounded text-blue-400/60 border border-blue-500/10 font-mono">CONFIDENCE: 98.2%</span>
                            </div>
                        </div>
                        <div className="text-left sm:text-right">
                            <div className="text-xs text-blue-400/50 mb-1">ALIAS</div>
                            <div className="text-lg font-mono text-white/60">{user_profile?.alias}</div>
                        </div>
                     </div>

                     <div className="space-y-6">
                        <div>
                            <div className="text-blue-400/40 text-xs mb-2 flex items-center gap-2">
                                <Brain size={12} /> PSYCHOLOGICAL PROFILE
                            </div>
                            <div className="bg-black/20 rounded-lg p-4 border border-blue-500/10">
                                <div className="flex flex-wrap gap-2 mb-3">
                                    {user_profile?.traits?.map((trait: string, i: number) => (
                                        <Tag key={i} text={trait} color="blue" />
                                    ))}
                                </div>
                                <p className="text-sm text-blue-100/70 leading-relaxed">
                                    {user_profile?.summary}
                                </p>
                            </div>
                        </div>

                        <div>
                            <div className="text-blue-400/40 text-xs mb-2 flex items-center gap-2">
                                <Heart size={12} /> RELATIONAL DYNAMICS
                            </div>
                            <div className="bg-black/20 rounded-lg p-4 border border-blue-500/10 italic text-white/60 text-sm">
                                "{user_profile?.attitude_to_aveline}"
                            </div>
                        </div>

                        <div className="grid grid-cols-1 gap-4">
                             <div>
                                 <div className="text-blue-400/40 text-xs mb-2">ABILITIES & INTERESTS</div>
                                 <ul className="space-y-1">
                                     {user_profile?.abilities_interests?.slice(0, 4).map((item: string, i: number) => (
                                         <li key={i} className="text-xs text-white/60 flex items-center gap-2">
                                             <span className="w-1 h-1 rounded-full bg-blue-500/40"></span>
                                             {item}
                                         </li>
                                     ))}
                                 </ul>
                             </div>
                             <div>
                                 <div className="text-blue-400/40 text-xs mb-2">VULNERABILITIES</div>
                                 <ul className="space-y-1">
                                     {user_profile?.weaknesses?.slice(0, 3).map((item: string, i: number) => (
                                         <li key={i} className="text-xs text-white/60 flex items-center gap-2">
                                             <span className="w-1 h-1 rounded-full bg-rose-500/40"></span>
                                             {item}
                                         </li>
                                     ))}
                                 </ul>
                             </div>
                        </div>
                     </div>
                </InfoCard>

                <InfoCard title="INTERACTION LOGIC">
                    <div className="space-y-4">
                        <div>
                             <div className="text-white/30 text-xs mb-2">TOPIC PRIORITY</div>
                             <div className="space-y-2">
                                 {persona?.interaction_logic?.topic_priority?.map((item: any, i: number) => (
                                     <div key={i} className="flex items-center gap-3 text-xs">
                                         <span className="font-mono text-white/30 w-8 text-right">{(item.weight * 100).toFixed(0)}%</span>
                                         <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                             <div className="h-full bg-white/20 rounded-full" style={{ width: `${item.weight * 100}%` }}></div>
                                         </div>
                                         <span className="text-white/60">{item.topic}</span>
                                     </div>
                                 ))}
                             </div>
                        </div>
                        
                        <div className="pt-4 border-t border-white/5">
                             <div className="text-white/30 text-xs mb-2">SENSORY TRIGGERS</div>
                             <div className="grid grid-cols-2 gap-2">
                                 {persona?.sensory_triggers?.rules?.map((rule: any, i: number) => (
                                     <div key={i} className="p-2 bg-white/5 rounded border border-white/5">
                                         <div className="text-[10px] text-white/30 mb-1">KEYWORDS</div>
                                         <div className="text-xs text-emerald-400 font-mono truncate">{rule.keywords.join(", ")}</div>
                                     </div>
                                 ))}
                             </div>
                        </div>
                    </div>
                </InfoCard>
            </div>
        </div>
      </div>
    </div>
  );
};

export default PersonaPanel;
