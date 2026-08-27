import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { User, Fingerprint, Brain, Heart, Shield, Lock, Hash, GitCommit, List, Eye, RefreshCw, CheckCircle, GraduationCap, BookOpen } from 'lucide-react';
import { InfoCard } from './InfoCard';
import { api } from '../api/apiService';
import { formatDisplayLabel } from '../utils/text';
import { useAvelineStore } from '../store/useStore';

interface PersonaPanelProps {
  persona: any;
  onPersonaChange?: (newPersona: any) => void;
  currentModel?: any; // Added prop
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

const PersonaCard = ({ p, isActive, switching, onSwitch, isNsfw = false }: any) => {
    return (
        <button
            onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onSwitch(p.filename);
            }}
            disabled={switching}
            className={`flex items-center justify-between p-3 rounded-lg border transition-all text-left group relative z-20 ${
                isActive 
                    ? isNsfw 
                        ? 'bg-rose-500/20 border-rose-500/30 ring-1 ring-rose-500/30' 
                        : 'bg-emerald-500/20 border-emerald-500/30 ring-1 ring-emerald-500/30'
                    : 'bg-black/20 border-white/5 hover:bg-white/10 hover:border-white/10 active:scale-[0.98]'
            } ${switching ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
            <div className="pointer-events-none">
                <div className={`text-sm font-bold ${
                    isActive 
                        ? isNsfw ? 'text-rose-300' : 'text-emerald-300' 
                        : 'text-white/80 group-hover:text-white'
                }`}>
                    {formatDisplayLabel(p.name)}
                </div>
                <div className="text-[10px] text-white/40 font-mono mt-0.5">
                    VER: {p.version || "?.?.?"}
                </div>
            </div>
            {isActive && (
                <div className={`h-2 w-2 rounded-full shadow-[0_0_10px_rgba(255,255,255,0.5)] ${
                    isNsfw ? 'bg-rose-500 shadow-rose-500/50' : 'bg-emerald-500 shadow-emerald-500/50'
                }`} />
            )}
        </button>
    );
};

const PersonaPanel = ({ persona, onPersonaChange, currentModel }: PersonaPanelProps) => {
  const [personas, setPersonas] = useState<any[]>([]);
  const [activeFilename, setActiveFilename] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const { studyMode } = useAvelineStore();

  useEffect(() => {
    loadPersonas();
  }, []);

  const loadPersonas = async () => {
    setLoading(true);
    try {
        const [listRes, currentRes] = await Promise.all([
            api.listPersonas(),
            api.getCurrentPersona()
        ]);
        
        if (Array.isArray(listRes)) {
            setPersonas(listRes);
        }
        if (currentRes?.data?.filename) {
            setActiveFilename(currentRes.data.filename);
        }
    } catch (e) {
        console.error("Failed to load personas", e);
    } finally {
        setLoading(false);
    }
  };

  const handleSwitchPersona = async (filename: string) => {
    setSwitching(true);
    try {
        const res = await api.switchPersona(filename);
        if (res?.status !== 'success') {
            // Prevent reload on error to avoid jumping to chat page on mobile
            // window.location.reload();
            console.error("Switch persona failed:", res);
            return;
        }

        const nextPersona = res?.data;
        if (onPersonaChange && nextPersona) {
            onPersonaChange(nextPersona);
            // Do NOT reload, just return. The parent state update will trigger re-render.
            setActiveFilename(filename);
            return;
        }

        const current = await api.getCurrentPersona();
        const refreshedPersona = current?.data;
        if (onPersonaChange && refreshedPersona) {
            onPersonaChange(refreshedPersona);
            setActiveFilename(filename);
            return;
        }

        // Only reload if we absolutely failed to update state
        // window.location.reload();
        console.warn("Persona switched but frontend state update might be incomplete.");
    } catch (e) {
        console.error("Failed to switch persona", e);
        // window.location.reload();
    } finally {
        setSwitching(false);
    }
  };

  if (!persona) {
    return (
        <div className="w-full min-h-[60vh] flex items-center justify-center text-white/30 font-mono animate-pulse text-center px-6">
            LOADING CORE IDENTITY MATRIX...
        </div>
    );
  }

  const { identity, backstory, personality } = persona;

  return (
    <div className="flex-1 p-4 sm:p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-end justify-between border-b border-white/10 pb-6">
            <div>
                <h1 className="text-2xl sm:text-4xl font-bold tracking-tight text-white mb-2 font-display">
                    IDENTITY <span className="text-emerald-500">MATRIX</span>
                </h1>
                <div className="flex items-center gap-4 text-xs font-mono text-white/40">
                    <span className="flex items-center gap-1">
                        <GitCommit size={12}/> VER: {persona?.meta?.version || identity?.version || "UNKNOWN"}
                    </span>
                    {persona?.meta?.last_updated && (
                        <span className="flex items-center gap-1">
                            <RefreshCw size={12}/> UPDATED: {persona.meta.last_updated}
                        </span>
                    )}
                </div>
            </div>
            <div className="text-right hidden md:block">
                 <div className="text-[10px] uppercase tracking-widest text-white/30 mb-1">DATA SOURCE</div>
                 <div className="text-emerald-400 font-mono text-sm uppercase truncate max-w-[200px]">
                    {persona?.meta?.schema_notes?.split('(')[0] || "LOCAL CONFIG"}
                 </div>
            </div>
        </div>

        {/* Persona Selector */}
        <div className="bg-white/5 border border-white/10 rounded-xl p-4 mb-6 relative z-10">
            {loading ? (
                <div className="flex items-center justify-center py-8 text-white/20 font-mono text-xs">
                    SYNCHRONIZING PERSONA DATABASE...
                </div>
            ) : (
                <div className="space-y-6">
                    {/* Cloud Section */}
                    {!studyMode && personas.filter(p => p.category === 'sfw').length > 0 && (
                        <div>
                             <div className="text-[10px] font-bold text-emerald-400/60 uppercase tracking-widest mb-2 flex items-center gap-2 px-1">
                                <Shield size={10} /> CLOUD MODULES (CLOUD)
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                {personas.filter(p => p.category === 'sfw').map((p) => (
                                    <PersonaCard 
                                        key={p.filename} 
                                        p={p} 
                                        isActive={p.filename === activeFilename || p.name === identity?.name}
                                        switching={switching} 
                                        onSwitch={handleSwitchPersona}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Study Section */}
                    {personas.filter(p => p.category === 'study').length > 0 && (
                        <div>
                             <div className="text-[10px] font-bold text-blue-400/60 uppercase tracking-widest mb-2 flex items-center gap-2 px-1 border-t border-white/5 pt-4 mt-2">
                                <GraduationCap size={10} /> STUDY MODULES (STUDY)
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                {personas.filter(p => p.category === 'study').map((p) => (
                                    <PersonaCard 
                                        key={p.filename} 
                                        p={p} 
                                        isActive={p.filename === activeFilename || p.name === identity?.name}
                                        switching={switching} 
                                        onSwitch={handleSwitchPersona}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Daily Section (Includes Legacy Sensitive/Local) */}
                    {!studyMode && personas.filter(p => p.category === 'daily' || p.category === 'sensitive').length > 0 && (
                        <div>
                             <div className="text-[10px] font-bold text-rose-400/60 uppercase tracking-widest mb-2 flex items-center gap-2 px-1 border-t border-white/5 pt-4 mt-2">
                                <Heart size={10} /> DAILY MODULES (DAILY)
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                {personas.filter(p => p.category === 'daily' || p.category === 'sensitive').map((p) => (
                                    <PersonaCard 
                                        key={p.filename} 
                                        p={p} 
                                        isActive={p.filename === activeFilename || p.name === identity?.name}
                                        switching={switching} 
                                        onSwitch={handleSwitchPersona}
                                        isNsfw={true}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* General/Other Section */}
                    {!studyMode && personas.filter(p => p.category !== 'sfw' && p.category !== 'sensitive' && p.category !== 'daily' && p.category !== 'study').length > 0 && (
                        <div>
                             <div className="text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2 flex items-center gap-2 px-1 border-t border-white/5 pt-4 mt-2">
                                <List size={10} /> GENERAL MODULES
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                {personas.filter(p => p.category !== 'sfw' && p.category !== 'sensitive' && p.category !== 'daily' && p.category !== 'study').map((p) => (
                                    <PersonaCard 
                                        key={p.filename} 
                                        p={p} 
                                        isActive={p.filename === activeFilename || p.name === identity?.name}
                                        switching={switching} 
                                        onSwitch={handleSwitchPersona}
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>

        {/* Info Cards Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-6">
                <InfoCard title="CORE SYSTEM IDENTITY" className="h-full">
                    <div className="space-y-6">
                        <div>
                            <div className="text-white/30 text-xs mb-2">DESIGNATION</div>
                            <div className="text-2xl font-bold text-white mb-1">
                                {formatDisplayLabel(identity?.name)} 
                                <span className="text-lg font-normal text-white/40">
                                    ({formatDisplayLabel(identity?.cn_name || identity?.aliases?.[0] || "")})
                                </span>
                            </div>
                            <p className="text-white/60 text-sm leading-relaxed">
                                {identity?.core_identity?.status || "Unknown Status"}
                            </p>
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
                                    <div className="text-sm font-mono text-white/80 truncate">
                                        {personality?.mbti || personality?.model?.MBTI || "N/A"}
                                    </div>
                                </div>
                                {personality?.alignment && (
                                    <div className="p-2 bg-white/5 rounded border border-white/5">
                                        <div className="text-[10px] text-white/30">ALIGNMENT</div>
                                        <div className="text-sm font-mono text-white/80 uppercase truncate">
                                            {personality.alignment}
                                        </div>
                                    </div>
                                )}
                                {personality?.big_five && !personality?.alignment && (
                                    <div className="p-2 bg-white/5 rounded border border-white/5">
                                        <div className="text-[10px] text-white/30">OPENNESS</div>
                                        <div className="text-sm font-mono text-white/80 uppercase truncate">
                                            {personality.big_five.openness?.split(' ')[0] || "HIGH"}
                                        </div>
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {personality?.traits?.map((t: any, i: number) => (
                                    <Tag 
                                        key={i} 
                                        text={typeof t === 'string' ? t : (t.name || t.trait)} 
                                        color="purple" 
                                    />
                                ))}
                            </div>
                        </div>

                        {identity?.core_identity?.core_fear && (
                            <div>
                                <div className="text-white/30 text-xs mb-2">CORE FEAR</div>
                                <div className="flex items-center gap-2 text-rose-400/80 text-sm">
                                    <Shield size={14} />
                                    {identity.core_identity.core_fear}
                                </div>
                            </div>
                        )}

                        {identity?.core_identity?.self_perception_evolution && (
                            <div>
                                <div className="text-white/30 text-xs mb-2">SELF PERCEPTION EVOLUTION</div>
                                <div className="space-y-2">
                                    {identity.core_identity.self_perception_evolution.map((stage: string, i: number) => (
                                        <div key={i} className="flex items-center gap-2 text-[10px] text-white/50">
                                            <div className="w-1 h-1 rounded-full bg-emerald-500/40" />
                                            {stage}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </InfoCard>

                {persona?.language_style && (
                    <InfoCard title="LANGUAGE & STYLE">
                        <div className="space-y-4">
                            <div>
                                <div className="text-white/30 text-xs mb-2">TONE & STYLE</div>
                                <p className="text-white/70 text-xs leading-relaxed italic">
                                    "{persona.language_style.tone}"
                                </p>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {persona.language_style.keywords?.map((word: string, i: number) => (
                                    <span key={i} className="text-[10px] font-mono text-emerald-400/60 bg-emerald-400/5 px-2 py-0.5 rounded border border-emerald-400/10">
                                        #{word}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </InfoCard>
                )}

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

            {/* Right Column: Interaction Logic & System Details */}
            <div className="space-y-6">
                <InfoCard title="INTERACTION LOGIC">
                    <div className="space-y-4">
                        {persona?.interaction_logic?.topic_priority && (
                            <div>
                                <div className="text-white/30 text-xs mb-2">TOPIC PRIORITY</div>
                                <div className="space-y-2">
                                    {persona.interaction_logic.topic_priority.map((item: any, i: number) => (
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
                        )}
                        
                        {(persona?.sensory_triggers?.rules || persona?.sensory_triggers) && (
                            <div className="pt-4 border-t border-white/5">
                                <div className="text-white/30 text-xs mb-2">SENSORY TRIGGERS</div>
                                <div className="grid grid-cols-2 gap-2">
                                    {(persona?.sensory_triggers?.rules || (Array.isArray(persona?.sensory_triggers) ? persona.sensory_triggers : [])).map((rule: any, i: number) => (
                                        <div key={i} className="p-2 bg-white/5 rounded border border-white/5">
                                            <div className="text-[10px] text-white/30 mb-1">KEYWORDS</div>
                                            <div className="text-xs text-emerald-400 font-mono truncate">
                                                {Array.isArray(rule.keywords) ? rule.keywords.join(", ") : rule.keyword || "UNKNOWN"}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </InfoCard>

                {persona?.interaction_logic?.response_chain && (
                    <InfoCard title="BEHAVIOR REACTION CHAIN" className="bg-purple-900/5 border-purple-500/10">
                        <div className="space-y-3">
                            {persona.interaction_logic.response_chain.map((step: any, i: number) => (
                                <div key={i} className="flex items-start gap-3">
                                    <div className="text-[10px] font-mono text-purple-400/60 mt-0.5">{String(step.step || i+1).padStart(2, '0')}</div>
                                    <div>
                                        <div className="text-xs font-bold text-white/80">{step.action}</div>
                                        <div className="text-[10px] text-white/40">{step.description}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </InfoCard>
                )}
            </div>
        </div>
      </div>
    </div>
  );
};

export default PersonaPanel;
