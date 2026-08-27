import React, { useMemo, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, Database, Brain, X, ScanFace, Shield, AlertTriangle, ChevronDown, ChevronRight, Gauge, HeartPulse, ListChecks, Boxes, Clock } from 'lucide-react';
import { EmotionType } from '../types';
import { EMOTIONS } from '../utils/emotion';
import { api } from '../api/apiService';

interface StatusPanelProps {
  stats: { 
    cpu: number; 
    gpu: number; 
    memory: number;
    scheduler?: {
      enabled: boolean;
      worker_count: number;
      tasks: {
        total: number;
        running: number;
        pending: number;
        completed: number;
        failed: number;
      };
      resources: {
        gpu_mem_used: number;
        gpu_mem_total: number;
        cpu_load: number;
      };
      biology?: {
        neurotransmitters: Record<string, number>;
        energy: number;
        sleep_debt: number;
      };
    };
  };
  emotion: EmotionType;
  lifeStatus: any;
  emotionMix?: Record<string, number>;
  colors?: [string, string, string, string];
}

const StatusCard = ({ title, children, className = "", onClick }: { title: string, children: React.ReactNode, className?: string, onClick?: () => void }) => (
  <div 
    onClick={onClick}
    className={`glass-card rounded-2xl p-6 transition-all duration-300 ${onClick ? 'cursor-pointer hover:bg-white/10 hover:border-white/20 active:scale-95' : ''} ${className}`}
  >
    <h3 className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
      {title}
    </h3>
    {children}
  </div>
);

const MetricRow = ({ label, value, unit = "" }: { label: string, value: string | number, unit?: string }) => (
    <div className="flex justify-between items-center gap-4 min-w-0 py-2 border-b border-white/5 last:border-0">
        <span className="text-xs text-white/50 font-mono truncate">{label}</span>
        <span className="text-sm font-mono text-white/90 text-glow truncate text-right max-w-[60%]">{value}<span className="text-white/30 ml-1">{unit}</span></span>
    </div>
);

const StatusPill = ({ status }: { status: string }) => {
    const normalized = String(status || 'unknown');
    const theme = (() => {
        if (normalized === 'healthy') return 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]';
        if (normalized === 'degraded') return 'bg-amber-500/10 border-amber-500/20 text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.2)]';
        if (normalized === 'unhealthy') return 'bg-rose-500/10 border-rose-500/20 text-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.2)]';
        if (normalized === 'error') return 'bg-rose-500/10 border-rose-500/20 text-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.2)]';
        return 'bg-white/5 border-white/10 text-white/50';
    })();

    return (
        <span className={`inline-flex items-center px-2 py-1 text-[10px] rounded border font-mono tracking-wider uppercase ${theme}`}>
            {normalized}
        </span>
    );
};

const CollapsibleSection = ({
    title,
    icon,
    isOpen,
    onToggle,
    children,
}: {
    title: string;
    icon?: React.ReactNode;
    isOpen: boolean;
    onToggle: () => void;
    children: React.ReactNode;
}) => (
    <div className="glass-card rounded-2xl overflow-hidden">
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

// --- VISUALIZATION COMPONENTS ---

interface MemoryHeatmapProps {
    activationGrid: number[];
}

const MemoryHeatmap = ({ activationGrid }: MemoryHeatmapProps) => {
    const grid = useMemo(() => {
        if (activationGrid && activationGrid.length > 0) return activationGrid;
        return Array(36).fill(0).map(() => Math.random());
    }, [activationGrid]);
    
    return (
        <div className="grid grid-cols-6 gap-1 w-full aspect-square max-w-[120px]">
            {grid.map((val, i) => (
                <motion.div
                    key={i}
                    className="w-full h-full rounded-[1px]"
                    animate={{ 
                        opacity: [0.1, 0.3 + val * 0.7, 0.1],
                        backgroundColor: val > 0.8 ? '#10B981' : val > 0.5 ? '#3B82F6' : '#ffffff' 
                    }}
                    transition={{ 
                        duration: 2 + Math.random() * 3, 
                        repeat: Infinity,
                        delay: Math.random() * 2
                    }}
                />
            ))}
        </div>
    );
};

const ReasoningDepthBar = ({ level, max = 6 }: { level: number, max?: number }) => (
    <div className="flex items-center gap-1 h-4">
        {[...Array(max)].map((_, i) => (
            <div 
                key={i} 
                className={`flex-1 h-full rounded-sm transition-all duration-500 ${
                    i < level 
                        ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]' 
                        : 'bg-white/5'
                }`}
            />
        ))}
    </div>
);

const PlanningStack = () => (
    <div className="space-y-2 font-mono text-[10px]">
        <div className="flex items-center justify-between p-2 bg-emerald-500/10 border border-emerald-500/20 rounded">
            <span className="text-emerald-300">SLOT_01: GOAL_PARSING</span>
            <span className="animate-pulse text-emerald-400">ACTIVE</span>
        </div>
        <div className="flex items-center justify-between p-2 bg-white/5 border border-white/5 rounded opacity-60">
            <span className="text-white/40">SLOT_02: SUBTASKING</span>
            <span className="text-white/20">IDLE</span>
        </div>
        <div className="flex items-center justify-between p-2 bg-white/5 border border-white/5 rounded opacity-60">
            <span className="text-white/40">SLOT_03: EXECUTION</span>
            <span className="text-white/20">WAITING</span>
        </div>
    </div>
);

const LatencyBreakdown = () => (
    <div className="flex items-end gap-1 h-16 mt-2">
        {[
            { h: '20%', label: 'PRS', color: 'bg-white/20' },
            { h: '60%', label: 'INF', color: 'bg-emerald-500/80' },
            { h: '15%', label: 'PP', color: 'bg-blue-500/60' },
            { h: '5%', label: 'IO', color: 'bg-purple-500/60' }
        ].map((item, i) => (
            <div key={i} className="flex-1 flex flex-col justify-end h-full gap-1 group">
                <div className={`w-full rounded-sm ${item.color}`} style={{ height: item.h }}></div>
                <span className="text-[8px] text-center text-white/20 font-mono group-hover:text-white/60 transition-colors">{item.label}</span>
            </div>
        ))}
    </div>
);

const ContextDriftIndicator = () => (
    <div className="flex items-center justify-between">
        <div className="relative w-16 h-16 rounded-full border-4 border-white/5 flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-4 border-emerald-500/20 border-t-emerald-500" style={{ transform: 'rotate(45deg)' }}></div>
            <div className="text-xs font-mono font-bold text-emerald-400">0.12</div>
        </div>
        <div className="flex-1 pl-4 text-xs">
            <div className="text-white/40 mb-1">DRIFT INDEX</div>
            <div className="text-emerald-400">STABLE</div>
            <div className="text-[10px] text-white/30 mt-1">VECTOR_SIM &gt; 0.9</div>
        </div>
    </div>
);

const CognitiveWaveform = ({ color, speed = 1 }: { color: string, speed?: number }) => {
    return (
        <div className="h-32 glass-card rounded-lg relative overflow-hidden mb-4 last:mb-0">
             {/* Grid */}
             <div className="absolute inset-0 opacity-10" 
                style={{ 
                  backgroundImage: `linear-gradient(to right, ${color}33 1px, transparent 1px), linear-gradient(to bottom, ${color}33 1px, transparent 1px)`,
                  backgroundSize: '20px 20px'
                }} 
             />
             
             {/* Data Stream Rain Effect */}
             <div className="absolute inset-0 flex justify-between px-4 opacity-20">
                {[...Array(10)].map((_, i) => (
                    <motion.div
                        key={i}
                        className="w-[1px] h-20 bg-gradient-to-b from-transparent to-white"
                        animate={{ top: ['-100%', '100%'], opacity: [0, 1, 0] }}
                        transition={{ 
                            duration: 2 + Math.random() * 2, 
                            repeat: Infinity, 
                            delay: Math.random() * 2,
                            ease: "linear"
                        }}
                        style={{ backgroundColor: color }}
                    />
                ))}
             </div>

             {/* Main Cognitive Load Wave */}
             <div className="absolute inset-0 flex items-center">
                 <svg className="w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                    <motion.path 
                        d="M0,50 Q10,40 20,50 T40,50 T60,50 T80,50 T100,50"
                        fill="none" 
                        stroke={color} 
                        strokeWidth="2"
                        initial={{ d: "M0,50 Q10,50 20,50 T40,50 T60,50 T80,50 T100,50" }}
                        animate={{ 
                            d: [
                                "M0,50 Q10,30 20,50 T40,70 T60,40 T80,60 T100,50",
                                "M0,50 Q10,60 20,40 T40,30 T60,60 T80,40 T100,50",
                                "M0,50 Q10,40 20,50 T40,50 T60,50 T80,50 T100,50"
                            ]
                        }}
                        transition={{ duration: 4 / speed, repeat: Infinity, ease: "easeInOut" }}
                    />
                    <motion.path 
                        fill={color}
                        fillOpacity="0.1"
                        stroke="none"
                        animate={{ 
                            d: [
                                "M0,50 Q10,30 20,50 T40,70 T60,40 T80,60 T100,50 V100 H0 Z",
                                "M0,50 Q10,60 20,40 T40,30 T60,60 T80,40 T100,50 V100 H0 Z",
                                "M0,50 Q10,40 20,50 T40,50 T60,50 T80,50 T100,50 V100 H0 Z"
                            ]
                        }}
                        transition={{ duration: 4 / speed, repeat: Infinity, ease: "easeInOut" }}
                    />
                 </svg>
             </div>
        </div>
    );
};

const SchedulerSection = ({ scheduler, color }: { scheduler?: StatusPanelProps['stats']['scheduler'], color: string }) => {
  const safeScheduler = scheduler && typeof scheduler === 'object' ? scheduler : null;
  if (!safeScheduler || !safeScheduler.enabled) return (
    <div className="text-center py-8 opacity-40 font-mono text-xs">
      C++ SCHEDULER ENGINE OFFLINE
    </div>
  );

  const tasks = safeScheduler.tasks && typeof safeScheduler.tasks === 'object' ? safeScheduler.tasks : { total: 0, running: 0, pending: 0, completed: 0, failed: 0 };
  const resources = safeScheduler.resources && typeof safeScheduler.resources === 'object' ? safeScheduler.resources : { gpu_mem_used: 0, gpu_mem_total: 0, cpu_load: 0 };
  const bio = safeScheduler.biology && typeof safeScheduler.biology === 'object' ? safeScheduler.biology : null;
  const gpuMemUsed = Number(resources.gpu_mem_used || 0);
  const gpuMemTotal = Number(resources.gpu_mem_total || 0);
  const gpuMemPercent = gpuMemTotal > 0 ? (gpuMemUsed / gpuMemTotal) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Task Metrics */}
      <div>
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
          <ListChecks size={12} />
          Task Pipeline
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-white/5 rounded-xl p-3 border border-white/5">
            <div className="text-[10px] text-white/30 uppercase mb-1">Running</div>
            <div className="text-xl font-mono text-emerald-400 text-glow">{tasks.running}</div>
          </div>
          <div className="bg-white/5 rounded-xl p-3 border border-white/5">
            <div className="text-[10px] text-white/30 uppercase mb-1">Queue</div>
            <div className="text-xl font-mono text-blue-400 text-glow">{tasks.pending}</div>
          </div>
        </div>
        <div className="mt-3 space-y-1">
          <div className="flex justify-between text-[10px] font-mono">
            <span className="text-white/30">COMPLETED</span>
            <span className="text-white/60">{tasks.completed}</span>
          </div>
          <div className="flex justify-between text-[10px] font-mono">
            <span className="text-white/30">FAILED</span>
            <span className="text-rose-400/60">{tasks.failed}</span>
          </div>
        </div>
      </div>

      {/* GPU Memory */}
      <div>
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
          <Boxes size={12} />
          GPU Memory Usage
        </div>
        <div className="h-2 bg-white/5 rounded-full overflow-hidden mb-2">
          <motion.div 
            className="h-full bg-gradient-to-r from-blue-500 to-emerald-500"
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, Math.max(0, gpuMemPercent))}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] font-mono">
          <span className="text-white/30">ALLOCATED</span>
          <span className="text-white/60">
            {(gpuMemUsed / 1024).toFixed(1)}GB / {(gpuMemTotal / 1024).toFixed(1)}GB
          </span>
        </div>
      </div>

      {/* Biology / Neurotransmitters */}
      {bio && (
        <div>
          <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
            <Brain size={12} />
            Neurotransmitters
          </div>
          <div className="space-y-3">
            {Object.entries(typeof bio.neurotransmitters === 'object' && bio.neurotransmitters ? bio.neurotransmitters : {}).map(([name, val]) => (
              <div key={name} className="space-y-1">
                <div className="flex justify-between text-[10px] font-mono uppercase">
                  <span className="text-white/40">{name}</span>
                  <span style={{ color }}>{(val * 100).toFixed(1)}%</span>
                </div>
                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                  <motion.div 
                    className="h-full"
                    style={{ backgroundColor: color }}
                    initial={{ width: 0 }}
                    animate={{ width: `${val * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div className="space-y-1">
              <div className="text-[9px] text-white/20 uppercase font-mono">Energy</div>
              <div className="text-xs font-mono text-white/70">{((bio.energy || 0) * 100).toFixed(0)}%</div>
            </div>
            <div className="space-y-1 text-right">
              <div className="text-[9px] text-white/20 uppercase font-mono">Sleep Debt</div>
              <div className="text-xs font-mono text-white/70">{((bio.sleep_debt || 0) * 100).toFixed(0)}%</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const StatusPanel = ({ stats, emotion, lifeStatus, emotionMix, colors }: StatusPanelProps) => {
  const safeStats = stats && typeof stats === 'object' ? stats : { cpu: 0, gpu: 0, memory: 0 };
  const safeLifeStatus = lifeStatus && typeof lifeStatus === 'object' ? lifeStatus : {};
  const safeEmotionMix = emotionMix && typeof emotionMix === 'object' ? emotionMix : null;
  const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
  const currentColors = colors || emoConfig.colors;
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [systemResources, setSystemResources] = useState<any>(null);
  const [sections, setSections] = useState<Record<string, boolean>>({
    overview: true,
    immune: true,
    activeCare: true,
    services: false,
    resources: false,
    scheduler: true,
    bio: false,
    memory: false,
    capabilities: true,
    controls: true,
  });
  // For Heatmap
  const [heatmapData, setHeatmapData] = useState<number[]>([]);

  useEffect(() => {
    try {
        const raw = localStorage.getItem('status_panel_sections_v1');
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') {
                setSections(prev => ({ ...prev, ...parsed }));
            }
        }
    } catch {}
  }, []);

  useEffect(() => {
    try {
        localStorage.setItem('status_panel_sections_v1', JSON.stringify(sections));
    } catch {}
  }, [sections]);

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
        try {
            const [healthRes, resRes] = await Promise.all([
                api.getHealth({ silent: true }),
                api.getHealthMetrics({ silent: true }),
            ]);

            if (!cancelled) {
                setHealth(healthRes);
                setSystemResources(resRes);
            }
        } catch {}
    };

    fetchData();
    // 用户要求：切到 Status 时查询一次，用的时候才查询，不再轮询以节省性能
    return () => {
        cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const fetchHeatmap = async () => {
        try {
            const memRes = await api.getWeightedMemories(36, 0.0);
            if (!cancelled && memRes?.status === 'success' && Array.isArray(memRes?.data)) {
                const weights = memRes.data.map((m: any) => Math.min(Number(m?.weight || 0) / 5.0, 1.0));
                while (weights.length < 36) weights.push(Math.random() * 0.1);
                setHeatmapData(weights.slice(0, 36));
            }
        } catch {}
    };

    fetchHeatmap();
    // 用户要求：不再轮询
    return () => {
        cancelled = true;
    };
  }, []);
  
  // Synthetic Data
    const cpuVal = Number.isFinite(safeStats.cpu) ? safeStats.cpu : 0;
    const gpuVal = Number.isFinite(safeStats.gpu) ? safeStats.gpu : 0;
    const loadFactor = (cpuVal + gpuVal) / 200;
    const contextSize = "13.2k / 128k";
  const inferSpeed = Math.floor(45 - loadFactor * 10);

  const services: Record<string, any> = health?.services && typeof health.services === 'object' ? health.services : {};
  const immune = services?.immune_system;
  const immuneStatus = String(immune?.status || 'unknown');
  const immuneDetails = immune?.details && typeof immune.details === 'object' ? immune.details : {};

  const activeCare = services?.active_care_service;
  const activeCareStatus = String(activeCare?.status || 'unknown');
  const activeCareDetails = activeCare?.details && typeof activeCare.details === 'object' ? activeCare.details : {};

  const allServiceEntries = useMemo(() => {
    return Object.entries(services)
        .map(([name, payload]) => ({ name, payload }))
        .sort((a, b) => a.name.localeCompare(b.name));
  }, [services]);

  const unhealthyServiceCount = useMemo(() => {
    return allServiceEntries.filter(e => {
        const s = String((e.payload as any)?.status || 'unknown');
        return s === 'unhealthy' || s === 'error';
    }).length;
  }, [allServiceEntries]);

  const nextActiveCareDecisionInSeconds = Number(activeCareDetails?.next_llm_decision_in_seconds ?? NaN);

  const resources = systemResources?.data && typeof systemResources.data === 'object' ? systemResources.data : {};
  const cpuUsage = Number(resources?.cpu_usage ?? health?.metrics?.cpu_usage ?? NaN);
  const memUsage = Number(resources?.memory_usage ?? health?.metrics?.memory_usage ?? NaN);
  const gpuUsage = Number(resources?.gpu_usage ?? NaN);
  const hasGpu = Boolean(resources?.has_gpu);

  const formatMaybeNumber = (value: any, digits: number = 1) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits) : '—';
  };

  const formatActiveModel = (value: any) => {
    const s = String(value ?? '').trim();
    if (!s || s === 'None' || s === 'unknown') return '—';
    return s;
  };
  
  // Determine if speaking/active based on lifeStatus or random
  const isSpeaking = safeLifeStatus?.activity === 'speaking' || safeLifeStatus?.isTyping || false;

  // Bio Data
  const bio = safeLifeStatus?.bio && typeof safeLifeStatus?.bio === 'object' ? safeLifeStatus?.bio : {};
  const energy = safeLifeStatus?.energy ?? 100;
  const hunger = safeLifeStatus?.hunger ?? 0;
  const thirst = safeLifeStatus?.thirst ?? 0;

  const renderMainContent = () => {
    switch (selectedWidget) {
        case 'IMMUNE':
            return (
                <div className="h-full flex flex-col p-4 md:p-6">
                    <h2 className="text-xl md:text-2xl font-bold mb-4 md:mb-6 flex items-center gap-3">
                        <Shield className="text-emerald-400" />
                        Immune System
                    </h2>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
                        <div className="glass-card rounded-2xl p-4 md:p-5">
                            <div className="flex items-center justify-between mb-4">
                                <div className="text-xs font-bold text-white/40 uppercase tracking-widest">STATUS</div>
                                <StatusPill status={immuneStatus} />
                            </div>
                            <div className="space-y-2">
                                <MetricRow label="RUNNING" value={immuneDetails?.running ? 'true' : 'false'} />
                                <MetricRow label="RECENT_ERRORS" value={Number(immuneDetails?.recent_errors || 0)} />
                                <MetricRow label="UNHEALTHY_SERVICES" value={unhealthyServiceCount} />
                            </div>
                        </div>
                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">AFFECTED SERVICES</div>
                            <div className="space-y-2 max-h-64 overflow-y-auto custom-scrollbar pr-2">
                                {allServiceEntries
                                    .filter(e => {
                                        const s = String((e.payload as any)?.status || 'unknown');
                                        return s === 'unhealthy' || s === 'error';
                                    })
                                    .slice(0, 50)
                                    .map(e => (
                                        <div key={e.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                                            <span className="text-xs font-mono text-white/70 truncate pr-4">{e.name}</span>
                                            <StatusPill status={String((e.payload as any)?.status || 'unknown')} />
                                        </div>
                                    ))}

                                {unhealthyServiceCount === 0 && (
                                    <div className="text-xs text-white/40 font-mono">ALL SERVICES HEALTHY</div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            );
        case 'SERVICES':
            return (
                <div className="h-full flex flex-col p-4 md:p-6">
                    <h2 className="text-xl md:text-2xl font-bold mb-4 md:mb-6 flex items-center gap-3">
                        <ListChecks className="text-blue-400" />
                        Service Health
                    </h2>
                    <div className="glass-card rounded-2xl p-4 md:p-5 overflow-hidden">
                        <div className="flex items-center justify-between mb-4">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest">OVERALL</div>
                            <StatusPill status={String(health?.status || 'unknown')} />
                        </div>
                        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar pr-2">
                            {allServiceEntries.map(e => (
                                <div key={e.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                                    <span className="text-xs font-mono text-white/70 truncate pr-4">{e.name}</span>
                                    <StatusPill status={String((e.payload as any)?.status || 'unknown')} />
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            );
        case 'ACTIVE_CARE':
            return (
                <div className="h-full flex flex-col p-4 md:p-6">
                    <h2 className="text-xl md:text-2xl font-bold mb-4 md:mb-6 flex items-center gap-3">
                        <Clock className="text-purple-400" />
                        Active Care
                    </h2>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
                        <div className="glass-card rounded-2xl p-4 md:p-5">
                            <div className="flex items-center justify-between mb-4">
                                <div className="text-xs font-bold text-white/40 uppercase tracking-widest">STATUS</div>
                                <StatusPill status={activeCareStatus} />
                            </div>
                            <div className="space-y-2">
                                <MetricRow label="RUNNING" value={activeCareDetails?.running ? 'true' : 'false'} />
                                <MetricRow label="NEXT_LLM_DECISION" value={Number.isFinite(nextActiveCareDecisionInSeconds) ? String(nextActiveCareDecisionInSeconds) : '—'} unit={Number.isFinite(nextActiveCareDecisionInSeconds) ? 's' : ''} />
                                <MetricRow label="LAST_INTENT" value={String(activeCareDetails?.last_decision_intent || '—')} />
                            </div>
                        </div>

                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">TASKS</div>
                            <div className="space-y-4">
                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="flex items-center justify-between">
                                        <div className="text-[10px] text-white/30 font-mono">PROACTIVE</div>
                                        <div className="text-[10px] text-white/50 font-mono uppercase">{String(activeCareDetails?.proactive_task_state || '—')}</div>
                                    </div>
                                    {activeCareDetails?.proactive_task_error ? (
                                        <div className="mt-2 text-xs text-rose-300/80 font-mono line-clamp-2" title={String(activeCareDetails?.proactive_task_error || '')}>
                                            {String(activeCareDetails?.proactive_task_error || '')}
                                        </div>
                                    ) : (
                                        <div className="mt-2 text-xs text-white/40 font-mono">—</div>
                                    )}
                                </div>

                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="flex items-center justify-between">
                                        <div className="text-[10px] text-white/30 font-mono">VOCAB</div>
                                        <div className="text-[10px] text-white/50 font-mono uppercase">{String(activeCareDetails?.vocab_task_state || '—')}</div>
                                    </div>
                                    {activeCareDetails?.vocab_task_error ? (
                                        <div className="mt-2 text-xs text-rose-300/80 font-mono line-clamp-2" title={String(activeCareDetails?.vocab_task_error || '')}>
                                            {String(activeCareDetails?.vocab_task_error || '')}
                                        </div>
                                    ) : (
                                        <div className="mt-2 text-xs text-white/40 font-mono">—</div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            );
        case 'MODULES':
            return (
                <div className="h-full flex flex-col p-6">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Boxes className="text-white/70" />
                        Core Modules
                    </h2>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">LLM</div>
                            <div className="space-y-2">
                                <MetricRow label="MODELS" value={String((resources as any)?.models_total ?? '—')} />
                                <MetricRow label="LOADED" value={String((resources as any)?.models_loaded ?? '—')} />
                                <MetricRow label="ACTIVE" value={formatActiveModel((resources as any)?.active_model)} />
                            </div>
                        </div>

                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">MEDIA</div>
                            <div className="space-y-2">
                                <MetricRow label="VOICES" value={String((resources as any)?.voices_total ?? '—')} />
                                <MetricRow label="IMAGE_MODELS" value={String((resources as any)?.image_models_total ?? '—')} />
                                <MetricRow label="GPU" value={hasGpu ? 'available' : 'n/a'} />
                            </div>
                        </div>
                    </div>
                </div>
            );
        case 'RESOURCES':
            return (
                <div className="h-full flex flex-col p-6">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Gauge className="text-rose-400" />
                        Resources
                    </h2>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">SYSTEM</div>
                            <div className="space-y-2">
                                <MetricRow label="CPU_USAGE" value={Number.isFinite(cpuUsage) ? cpuUsage.toFixed(1) : '—'} unit="%" />
                                <MetricRow label="MEMORY_USAGE" value={Number.isFinite(memUsage) ? memUsage.toFixed(1) : '—'} unit="%" />
                                <MetricRow label="GPU_USAGE" value={hasGpu ? (Number.isFinite(gpuUsage) ? gpuUsage.toFixed(1) : '—') : 'N/A'} unit={hasGpu ? '%' : ''} />
                            </div>
                        </div>
                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">DETAILS</div>
                            <div className="space-y-2">
                                <MetricRow label="CPU_COUNT" value={resources?.cpu_count ?? '—'} />
                                <MetricRow label="MEM_TOTAL" value={formatMaybeNumber((resources as any)?.memory_total_gb)} unit="GB" />
                                <MetricRow label="MEM_AVAIL" value={formatMaybeNumber((resources as any)?.memory_available_gb)} unit="GB" />
                                <MetricRow label="GPU_PRESENT" value={hasGpu ? 'true' : 'false'} />
                            </div>
                        </div>
                    </div>
                </div>
            );
        case 'SCHEDULER':
            return (
                <div className="h-full flex flex-col p-6 overflow-y-auto custom-scrollbar">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <ListChecks className="text-emerald-400" />
                        C++ Scheduler Engine
                    </h2>
                    <div className="glass-card rounded-2xl p-6">
                        <SchedulerSection scheduler={safeStats.scheduler} color={currentColors[0]} />
                    </div>
                </div>
            );
        case 'BIO':
            return (
                <div className="h-full flex flex-col p-6">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Activity className="text-pink-400" />
                        Biological System
                    </h2>
                    <div className="grid grid-cols-2 gap-8">
                         <div>
                            <h3 className="text-sm font-bold text-white/40 mb-4">NEUROTRANSMITTERS</h3>
                            <div className="space-y-4">
                                <MetricRow label="DOPAMINE" value={((bio.dopamine || 0) * 100).toFixed(1)} unit="%" />
                                <MetricRow label="SEROTONIN" value={((bio.serotonin || 0) * 100).toFixed(1)} unit="%" />
                                <MetricRow label="NOREPINEPHRINE" value={((bio.norepinephrine || 0) * 100).toFixed(1)} unit="%" />
                                <MetricRow label="OXYTOCIN" value={((bio.oxytocin || 0) * 100).toFixed(1)} unit="%" />
                            </div>
                         </div>
                         <div>
                            <h3 className="text-sm font-bold text-white/40 mb-4">PHYSIOLOGY</h3>
                            <div className="space-y-4">
                                <MetricRow label="ENERGY" value={energy.toFixed(1)} unit="%" />
                                <MetricRow label="HUNGER" value={hunger.toFixed(1)} unit="%" />
                                <MetricRow label="THIRST" value={thirst.toFixed(1)} unit="%" />
                            </div>
                         </div>
                    </div>
                </div>
            );
        case 'MEMORY':
            return (
                <div className="h-full flex flex-col p-6">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Database className="text-emerald-400" />
                        Memory Matrix
                    </h2>
                    <div className="flex-1 flex items-center justify-center">
                        <div className="scale-150">
                            <MemoryHeatmap activationGrid={heatmapData} />
                        </div>
                    </div>
                    <div className="mt-8 grid grid-cols-3 gap-4">
                        <MetricRow label="Retrieval" value="98" unit="ms" />
                        <MetricRow label="Fragments" value="12" />
                        <MetricRow label="Coherence" value="0.94" />
                    </div>
                </div>
            );
        case 'REASONING':
            return (
                <div className="h-full flex flex-col p-6">
                     <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Brain className="text-blue-400" />
                        Reasoning Engine
                    </h2>
                    <div className="flex-1 flex flex-col justify-center gap-8">
                        <div>
                            <div className="text-sm text-white/40 mb-2">DEPTH ANALYSIS</div>
                            <ReasoningDepthBar level={4} max={10} />
                        </div>
                        <PlanningStack />
                    </div>
                </div>
            );
        case 'SYSTEM':
             return (
                <div className="h-full flex flex-col p-6">
                    <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                        <Activity className="text-rose-400" />
                        System Core
                    </h2>
                    <CognitiveWaveform color={currentColors[1]} speed={1 + loadFactor} />
                    <div className="mt-6 space-y-4">
                         <MetricRow label="COGNITIVE_LOAD" value={(loadFactor * 100).toFixed(1)} unit="%" />
                         <MetricRow label="ATTENTION_HEADS" value="32" unit="ACTIVE" />
                         <MetricRow label="LAYER_SYNC" value="99.9" unit="%" />
                    </div>
                </div>
            );
        default:
            return (
                <div className="h-full w-full p-4 md:p-6 overflow-y-auto custom-scrollbar">
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 md:gap-6">
                        <div className="glass-card rounded-2xl p-5">
                            <div className="flex items-center justify-between mb-4">
                                <div className="text-xs font-bold text-white/40 uppercase tracking-widest">SYSTEM CORE</div>
                                <StatusPill status={String(health?.status || 'unknown')} />
                            </div>
                            <CognitiveWaveform color={currentColors[1]} speed={1 + loadFactor} />
                            <div className="mt-4 space-y-2">
                                <MetricRow label="COGNITIVE_LOAD" value={(loadFactor * 100).toFixed(1)} unit="%" />
                                <MetricRow label="ATTENTION_HEADS" value="32" unit="ACTIVE" />
                                <MetricRow label="LAYER_SYNC" value="99.9" unit="%" />
                            </div>
                        </div>

                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
                                <ListChecks size={12} className="text-emerald-400/70" />
                                C++ SCHEDULER
                            </div>
                            <SchedulerSection scheduler={safeStats.scheduler} color={currentColors[0]} />
                            <button
                                type="button"
                                onClick={() => setSelectedWidget('SCHEDULER')}
                                className="w-full mt-4 flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                            >
                                <ListChecks size={14} />
                                <span>OPEN SCHEDULER VIEW</span>
                            </button>
                        </div>

                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
                                <HeartPulse size={12} className="text-pink-400/70" />
                                BIO & EMOTION
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="text-[10px] text-white/30 font-mono mb-1">DOPAMINE</div>
                                    <div className="text-sm font-mono text-pink-400">{((bio.dopamine || 0) * 100).toFixed(0)}%</div>
                                </div>
                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="text-[10px] text-white/30 font-mono mb-1">ENERGY</div>
                                    <div className="text-sm font-mono text-yellow-400">{Number.isFinite(Number(energy)) ? Number(energy).toFixed(0) : '—'}%</div>
                                </div>
                            </div>
                            <div className="mt-3 grid grid-cols-2 gap-3">
                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="text-[10px] text-white/30 font-mono mb-1">HUNGER</div>
                                    <div className="text-sm font-mono text-amber-300">{Number.isFinite(Number(hunger)) ? Number(hunger).toFixed(0) : '—'}%</div>
                                </div>
                                <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                                    <div className="text-[10px] text-white/30 font-mono mb-1">THIRST</div>
                                    <div className="text-sm font-mono text-blue-300">{Number.isFinite(Number(thirst)) ? Number(thirst).toFixed(0) : '—'}%</div>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setSelectedWidget('BIO')}
                                className="w-full mt-4 flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                            >
                                <HeartPulse size={14} />
                                <span>OPEN BIO VIEW</span>
                            </button>
                        </div>

                        <div className="glass-card rounded-2xl p-5">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
                                <Database size={12} className="text-emerald-400/70" />
                                MEMORY SNAPSHOT
                            </div>
                            <div className="flex items-center gap-4">
                                <div className="w-20 h-20 opacity-80">
                                    <MemoryHeatmap activationGrid={heatmapData} />
                                </div>
                                <div className="flex-1">
                                    <div className="text-[10px] text-white/30 font-mono">WEIGHTED MEMORY</div>
                                    <div className="text-xs text-white/50 mt-1">HEATMAP SNAPSHOT</div>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setSelectedWidget('MEMORY')}
                                className="w-full mt-4 flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                            >
                                <Database size={14} />
                                <span>OPEN MEMORY VIEW</span>
                            </button>
                        </div>

                        <div className="glass-card rounded-2xl p-5 xl:col-span-2">
                            <div className="flex items-center justify-between mb-4">
                                <div className="text-xs font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
                                    <ListChecks size={12} className="text-blue-400/70" />
                                    SERVICE HEALTH
                                </div>
                                <button
                                    type="button"
                                    onClick={() => setSelectedWidget('SERVICES')}
                                    className="px-3 py-1 bg-white/10 hover:bg-white/20 border border-white/10 rounded-full text-[10px] font-mono text-white/70"
                                >
                                    VIEW ALL
                                </button>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {allServiceEntries.slice(0, 6).map(e => (
                                    <div key={e.name} className="flex items-center justify-between p-3 bg-white/5 border border-white/5 rounded-xl">
                                        <span className="text-xs font-mono text-white/70 truncate pr-4">{e.name}</span>
                                        <StatusPill status={String((e.payload as any)?.status || 'unknown')} />
                                    </div>
                                ))}
                                {allServiceEntries.length === 0 && (
                                    <div className="text-xs text-white/40 font-mono">NO SERVICES REGISTERED</div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            );
    }
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] h-full p-4 md:p-6 gap-4 md:gap-6 overflow-hidden">
      {/* Left Main Panel */}
      <div className="h-[400px] md:h-[500px] xl:h-auto glass-panel rounded-3xl overflow-hidden relative backdrop-blur-sm shadow-2xl transition-all duration-500 min-h-[350px] md:min-h-[400px]">
        <AnimatePresence mode="wait">
            <motion.div
                key={selectedWidget || 'default'}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 1.05 }}
                transition={{ duration: 0.3 }}
                className="w-full h-full"
            >
                {renderMainContent()}
            </motion.div>
        </AnimatePresence>
        
        {/* Back Button if in detail view */}
        {selectedWidget && (
             <button 
                onClick={() => setSelectedWidget(null)}
                className="absolute top-4 right-4 p-2 bg-white/5 hover:bg-white/20 rounded-lg text-white/60 hover:text-white transition-colors z-30"
            >
                <X size={20} />
            </button>
        )}
      </div>

      <div className="min-h-0 overflow-y-auto custom-scrollbar pr-2 space-y-4">
        <StatusCard title="KEY OVERVIEW" className="glass-card">
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <div className="text-xs text-white/40 font-mono">OVERALL</div>
                    <StatusPill status={String(health?.status || 'unknown')} />
                </div>
                <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-white/5 rounded-xl border border-white/10">
                        <div className="text-[10px] text-white/30 font-mono mb-1">CPU</div>
                        <div className="text-lg font-mono text-white/90 text-glow">{Number.isFinite(cpuUsage) ? cpuUsage.toFixed(0) : '—'}<span className="text-white/30 ml-1">%</span></div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-xl border border-white/10">
                        <div className="text-[10px] text-white/30 font-mono mb-1">MEM</div>
                        <div className="text-lg font-mono text-white/90 text-glow">{Number.isFinite(memUsage) ? memUsage.toFixed(0) : '—'}<span className="text-white/30 ml-1">%</span></div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-xl border border-white/10">
                        <div className="text-[10px] text-white/30 font-mono mb-1">GPU</div>
                        <div className="text-lg font-mono text-white/90 text-glow">{hasGpu ? (Number.isFinite(gpuUsage) ? gpuUsage.toFixed(0) : '—') : 'N/A'}{hasGpu && <span className="text-white/30 ml-1">%</span>}</div>
                    </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-white/5">
                    <div className="flex items-center gap-2 text-xs text-white/40 font-mono">
                        <Shield size={14} className="text-emerald-400/60" />
                        IMMUNE
                    </div>
                    <div className="flex items-center gap-2">
                        <StatusPill status={immuneStatus} />
                        {unhealthyServiceCount > 0 && (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-rose-300 bg-rose-500/10 border border-rose-500/20 rounded px-2 py-1">
                                <AlertTriangle size={12} />
                                {unhealthyServiceCount}
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </StatusCard>

        <CollapsibleSection
            title="IMMUNE SYSTEM"
            icon={<Shield size={14} className="text-emerald-400/60" />}
            isOpen={sections.immune}
            onToggle={() => setSections(prev => ({ ...prev, immune: !prev.immune }))}
        >
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <div className="text-xs text-white/50 font-mono">STATUS</div>
                    <StatusPill status={immuneStatus} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">RUNNING</div>
                        <div className="text-sm font-mono text-white/80">{immuneDetails?.running ? 'true' : 'false'}</div>
                    </div>
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">RECENT ERR</div>
                        <div className="text-sm font-mono text-white/80">{Number(immuneDetails?.recent_errors || 0)}</div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => setSelectedWidget('IMMUNE')}
                    className="w-full flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <Shield size={14} />
                    <span>OPEN IMMUNE VIEW</span>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="SERVICE HEALTH"
            icon={<ListChecks size={14} className="text-blue-400/60" />}
            isOpen={sections.services}
            onToggle={() => setSections(prev => ({ ...prev, services: !prev.services }))}
        >
            <div className="space-y-2">
                {allServiceEntries.slice(0, 8).map(e => (
                    <div key={e.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                        <span className="text-xs font-mono text-white/70 truncate pr-4">{e.name}</span>
                        <StatusPill status={String((e.payload as any)?.status || 'unknown')} />
                    </div>
                ))}
                {allServiceEntries.length === 0 && (
                    <div className="text-xs text-white/40 font-mono">NO SERVICES REGISTERED</div>
                )}
                <button
                    type="button"
                    onClick={() => setSelectedWidget('SERVICES')}
                    className="w-full mt-2 flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <ListChecks size={14} />
                    <span>VIEW ALL SERVICES</span>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="ACTIVE CARE"
            icon={<Clock size={14} className="text-purple-400/60" />}
            isOpen={sections.activeCare}
            onToggle={() => setSections(prev => ({ ...prev, activeCare: !prev.activeCare }))}
        >
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <div className="text-xs text-white/50 font-mono">STATUS</div>
                    <StatusPill status={activeCareStatus} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">NEXT</div>
                        <div className="text-sm font-mono text-white/80">{Number.isFinite(nextActiveCareDecisionInSeconds) ? `${nextActiveCareDecisionInSeconds}s` : '—'}</div>
                    </div>
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">INTENT</div>
                        <div className="text-sm font-mono text-white/80 truncate" title={String(activeCareDetails?.last_decision_intent || '')}>
                            {String(activeCareDetails?.last_decision_intent || '—')}
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">PROACTIVE</div>
                        <div className="text-xs font-mono text-white/70 truncate" title={String(activeCareDetails?.proactive_task_state || '')}>
                            {String(activeCareDetails?.proactive_task_state || '—')}
                        </div>
                    </div>
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">VOCAB</div>
                        <div className="text-xs font-mono text-white/70 truncate" title={String(activeCareDetails?.vocab_task_state || '')}>
                            {String(activeCareDetails?.vocab_task_state || '—')}
                        </div>
                    </div>
                </div>

                <button
                    type="button"
                    onClick={() => setSelectedWidget('ACTIVE_CARE')}
                    className="w-full flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <Clock size={14} />
                    <span>OPEN ACTIVE CARE VIEW</span>
                </button>
            </div>
        </CollapsibleSection>



        <CollapsibleSection
            title="C++ SCHEDULER"
            icon={<ListChecks size={14} className="text-emerald-400/60" />}
            isOpen={sections.scheduler}
            onToggle={() => setSections(prev => ({ ...prev, scheduler: !prev.scheduler }))}
        >
            <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                    <div className="p-2 bg-white/5 border border-white/5 rounded-lg">
                        <div className="text-[9px] text-white/30 font-mono">RUNNING</div>
                        <div className="text-sm font-mono text-emerald-400">{safeStats.scheduler?.tasks.running ?? 0}</div>
                    </div>
                    <div className="p-2 bg-white/5 border border-white/5 rounded-lg">
                        <div className="text-[9px] text-white/30 font-mono">QUEUE</div>
                        <div className="text-sm font-mono text-blue-400">{safeStats.scheduler?.tasks.pending ?? 0}</div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => setSelectedWidget('SCHEDULER')}
                    className="w-full flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <ListChecks size={14} />
                    <span>OPEN SCHEDULER VIEW</span>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="BIO & EMOTION"
            icon={<HeartPulse size={14} className="text-pink-400/60" />}
            isOpen={sections.bio}
            onToggle={() => setSections(prev => ({ ...prev, bio: !prev.bio }))}
        >
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <div className="text-xs text-white/50 font-mono">ACTIVE</div>
                    <div className="text-xs text-white/40">{safeEmotionMix ? Object.keys(safeEmotionMix).slice(0, 3).join(' / ') : emotion}</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">DOPAMINE</div>
                        <div className="text-sm font-mono text-pink-400">{((bio.dopamine || 0) * 100).toFixed(0)}%</div>
                    </div>
                    <div className="p-3 bg-white/5 border border-white/5 rounded-xl">
                        <div className="text-[10px] text-white/30 font-mono mb-1">ENERGY</div>
                        <div className="text-sm font-mono text-yellow-400">{energy.toFixed(0)}%</div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => setSelectedWidget('BIO')}
                    className="w-full flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <HeartPulse size={14} />
                    <span>OPEN BIO VIEW</span>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="MEMORY"
            icon={<Database size={14} className="text-emerald-400/60" />}
            isOpen={sections.memory}
            onToggle={() => setSections(prev => ({ ...prev, memory: !prev.memory }))}
        >
            <div className="space-y-3">
                <div className="flex gap-4 items-center">
                    <div className="w-16 h-16 opacity-50 pointer-events-none">
                        <MemoryHeatmap activationGrid={heatmapData} />
                    </div>
                    <div className="flex-1">
                        <div className="text-[10px] text-white/30 font-mono">WEIGHTED MEMORY</div>
                        <div className="text-xs text-white/50 mt-1">HEATMAP SNAPSHOT</div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => setSelectedWidget('MEMORY')}
                    className="w-full flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <Database size={14} />
                    <span>OPEN MEMORY VIEW</span>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="CORE CAPABILITIES"
            icon={<Boxes size={14} className="text-white/40" />}
            isOpen={sections.capabilities}
            onToggle={() => setSections(prev => ({ ...prev, capabilities: !prev.capabilities }))}
        >
            <div className="grid grid-cols-2 gap-3">
                <button type="button" onClick={() => setSelectedWidget('MODULES')} className="p-3 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl transition-colors text-left">
                    <div className="text-[10px] text-white/30 font-mono mb-1">CHAT/LLM</div>
                    <div className="text-xs text-white/60">WebSocket + Hybrid LLM</div>
                </button>
                <button type="button" onClick={() => setSelectedWidget('MODULES')} className="p-3 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl transition-colors text-left">
                    <div className="text-[10px] text-white/30 font-mono mb-1">TTS/VOICE</div>
                    <div className="text-xs text-white/60">CPU Worker</div>
                </button>
                <button type="button" onClick={() => setSelectedWidget('MODULES')} className="p-3 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl transition-colors text-left">
                    <div className="text-[10px] text-white/30 font-mono mb-1">IMAGE</div>
                    <div className="text-xs text-white/60">GPU Worker</div>
                </button>
                <button type="button" onClick={() => setSelectedWidget('ACTIVE_CARE')} className="p-3 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl transition-colors text-left">
                    <div className="text-[10px] text-white/30 font-mono mb-1">ACTIVE CARE</div>
                    <div className="text-xs text-white/60">Local decision loop</div>
                </button>
            </div>
        </CollapsibleSection>

        <CollapsibleSection
            title="CONTROLS"
            icon={<Cpu size={14} className="text-white/40" />}
            isOpen={sections.controls}
            onToggle={() => setSections(prev => ({ ...prev, controls: !prev.controls }))}
        >
            <div className="flex flex-col gap-3">
                <button 
                    onClick={() => (window as any).togglePetMode && (window as any).togglePetMode()}
                    className="flex items-center justify-center gap-2 p-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl transition-all active:scale-95 text-xs font-mono text-white/80"
                >
                    <ScanFace size={14} />
                    <span>ENTER PET MODE</span>
                </button>
            </div>
        </CollapsibleSection>
      </div>

    </div>
  );
};

export default StatusPanel;
