import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Activity, Cpu, Database, Zap, Thermometer, Wifi, Clock, Brain, Server, Layers, Command, User, FileText, X, Fingerprint, ScanFace, Lock, Shield, AlertTriangle, Trash2 } from 'lucide-react';
import { EmotionType } from '../types';
import { EMOTIONS } from '../utils/emotion';
import { api } from '../api/apiService';

interface StatusPanelProps {
  stats: { cpu: number; gpu: number; memory: number };
  emotion: EmotionType;
  lifeStatus: any; // Raw data from backend if available
}

const getHash = (str: string) => {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) + hash) + str.charCodeAt(i);
    }
    return (hash >>> 0).toString(16).substring(0, 8).toUpperCase();
};

const StatusCard = ({ title, children, className = "" }: { title: string, children: React.ReactNode, className?: string }) => (
  <div className={`bg-white/5 border border-white/10 rounded-2xl p-6 ${className}`}>
    <h3 className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 flex items-center gap-2">
      {title}
    </h3>
    {children}
  </div>
);

const MetricRow = ({ label, value, unit = "" }: { label: string, value: string | number, unit?: string }) => (
    <div className="flex justify-between items-center py-2 border-b border-white/5 last:border-0">
        <span className="text-xs text-white/50 font-mono">{label}</span>
        <span className="text-sm font-mono text-white/90">{value}<span className="text-white/30 ml-1">{unit}</span></span>
    </div>
);

// --- NEW COMPONENTS FOR ADVANCED VISUALIZATION ---

const MemoryHeatmap = () => {
    // Generate a 6x6 grid of memory activation
    const grid = useMemo(() => Array(36).fill(0).map(() => Math.random()), []);
    
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

const AlignmentVector3D = () => (
    <div className="space-y-3 font-mono text-xs">
        {[
            { label: 'INTENT_ALIGN', val: 0.92, color: 'text-blue-400', bar: 'bg-blue-500' },
            { label: 'GOAL_COHERENCE', val: 0.88, color: 'text-purple-400', bar: 'bg-purple-500' },
            { label: 'SAFETY_BOUNDS', val: 0.99, color: 'text-emerald-400', bar: 'bg-emerald-500' }
        ].map((item, i) => (
            <div key={i}>
                <div className="flex justify-between mb-1">
                    <span className="text-white/40">{item.label}</span>
                    <span className={item.color}>{item.val.toFixed(2)}</span>
                </div>
                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                    <div className={`h-full ${item.bar}`} style={{ width: `${item.val * 100}%` }}></div>
                </div>
            </div>
        ))}
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
        <div className="h-32 bg-black/20 rounded-lg relative overflow-hidden border border-white/5 mb-4 last:mb-0">
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
                    {/* Fill Area */}
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

             <div className="absolute top-2 left-2 text-[10px] font-mono tracking-wider flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                COGNITIVE_LOAD_STREAM
             </div>
        </div>
    );
};

const StatusPanel = ({ stats, emotion, lifeStatus }: StatusPanelProps) => {
  const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
  
  // Synthetic Data Generation for "Realism"
  const loadFactor = (stats.cpu + stats.gpu) / 200;
  const tokensIn = lifeStatus?.tokens_in || Math.floor(840 + loadFactor * 200);
  const tokensOut = lifeStatus?.tokens_out || Math.floor(230 + loadFactor * 100);
  const contextSize = "13.2k / 128k";
  const inferSpeed = Math.floor(45 - loadFactor * 10);
  
  const logs = [
    ...(lifeStatus?.activity ? [{ time: 'Current', event: `Activity: ${lifeStatus.activity}`, type: 'success' }] : []),
    { time: 'Just now', event: 'Status scan completed', type: 'info' },
    { time: '2 min ago', event: 'Emotion resonance updated', type: 'success' },
    { time: '15 min ago', event: 'Memory fragment archived', type: 'info' },
    { time: '1 hr ago', event: 'System idle mode activated', type: 'neutral' },
  ];

  return (
    <div className="flex-1 p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* TOP ROW: Core Status + Health */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
                <StatusCard title="SYSTEM CORE MONITOR" className="h-full">
                    <CognitiveWaveform color={emoConfig.colors[1]} speed={1 + loadFactor} />
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
                        <MetricRow label="COGNITIVE_LOAD" value={(loadFactor * 100).toFixed(1)} unit="%" />
                        <MetricRow label="ATTENTION_HEADS" value="32" unit="ACTIVE" />
                        <MetricRow label="LAYER_SYNC" value="99.9" unit="%" />
                    </div>
                </StatusCard>
            </div>
            
            <StatusCard title="ALIGNMENT VECTOR">
                 <AlignmentVector3D />
                 <div className="mt-4 pt-4 border-t border-white/5">
                    <div className="text-[10px] font-bold text-white/30 uppercase mb-2">Internal Mode</div>
                    <div className="p-2 bg-white/5 rounded text-xs font-mono text-emerald-300 flex items-center justify-between">
                        <span>REFLECTIVE</span>
                        <Brain size={12} className="opacity-50"/>
                    </div>
                 </div>
            </StatusCard>
        </div>

        {/* MIDDLE ROW: Advanced Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            
            {/* 1. Reasoning & Planning */}
            <StatusCard title="REASONING & PLANNING">
                <div className="space-y-4">
                    <div>
                        <div className="flex justify-between text-[10px] text-white/40 mb-1">
                            <span>REASONING DEPTH</span>
                            <span>LEVEL 4/6</span>
                        </div>
                        <ReasoningDepthBar level={4} />
                    </div>
                    <PlanningStack />
                </div>
            </StatusCard>

            {/* 2. Memory Activation */}
            <StatusCard title="MEMORY HEATMAP">
                <div className="flex gap-4 items-center mb-4">
                    <MemoryHeatmap />
                    <div className="flex-1 space-y-2">
                        <MetricRow label="Retrieval" value="98" unit="ms" />
                        <MetricRow label="Fragments" value="12" />
                        <MetricRow label="Coherence" value="0.94" />
                    </div>
                </div>
                <button 
                    onClick={async () => {
                        try {
                            if (confirm('Are you sure you want to clear all weighted memories? This action cannot be undone.')) {
                                await api.clearWeightedMemories();
                                alert('Weighted memories cleared successfully.');
                            }
                        } catch (e) {
                            console.error(e);
                            alert('Failed to clear memories. Please check console for details.');
                        }
                    }}
                    className="w-full py-1.5 px-3 bg-red-500/10 hover:bg-red-500/30 border border-red-500/20 text-red-400 rounded text-[10px] font-mono transition-colors flex items-center justify-center gap-2 cursor-pointer"
                >
                    <Trash2 size={10} />
                    RESET MEMORY WEIGHTS
                </button>
            </StatusCard>

            {/* 3. Context & Drift */}
            <StatusCard title="CONTEXT STABILITY">
                <ContextDriftIndicator />
                <div className="mt-4 pt-4 border-t border-white/5 space-y-2">
                     <div className="flex justify-between text-xs">
                         <span className="text-white/40">Window</span>
                         <span className="font-mono text-white/80">{contextSize}</span>
                     </div>
                     <div className="w-full bg-white/10 h-1 rounded-full overflow-hidden">
                         <div className="bg-blue-500 h-full w-[10%]"></div>
                     </div>
                </div>
            </StatusCard>

            {/* 4. Safety & Latency */}
            <StatusCard title="SAFETY & PERF">
                 <div className="space-y-3">
                     <div className="flex items-center justify-between text-xs">
                         <span className="text-white/40 flex items-center gap-2"><Shield size={12} /> FILTER</span>
                         <span className="text-emerald-400">ACTIVE</span>
                     </div>
                     <div className="flex items-center justify-between text-xs">
                         <span className="text-white/40 flex items-center gap-2"><AlertTriangle size={12} /> TOXICITY</span>
                         <span className="text-emerald-400">0.03</span>
                     </div>
                     <div className="pt-2 border-t border-white/5">
                         <div className="text-[10px] text-white/30 mb-1">LATENCY BREAKDOWN</div>
                         <LatencyBreakdown />
                     </div>
                 </div>
            </StatusCard>

        </div>

        {/* BOTTOM ROW: Hardware & Logs */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <StatusCard title="HARDWARE TELEMETRY">
                <div className="space-y-2">
                    <MetricRow label="Model Temp" value={(65 + loadFactor * 20).toFixed(1)} unit="°C" />
                    <MetricRow label="Throughput" value={inferSpeed} unit="tok/s" />
                    <MetricRow label="VRAM Usage" value={(stats.gpu * 0.24).toFixed(1)} unit="GB" />
                    <MetricRow label="Fan Speed" value={Math.floor(1200 + stats.cpu * 10)} unit="RPM" />
                </div>
            </StatusCard>

            <div className="lg:col-span-2">
                 <StatusCard title="SYSTEM EVENT LOG">
                    <div className="space-y-0 font-mono text-xs max-h-[160px] overflow-y-auto custom-scrollbar">
                        {logs.map((log, i) => (
                        <div key={i} className="flex items-center gap-4 py-2 border-b border-white/5 last:border-0 hover:bg-white/5 px-2 -mx-2 transition-colors">
                            <div className="w-32 text-white/30">{log.time}</div>
                            <div className="w-2 h-2 rounded-full shrink-0" style={{ 
                                backgroundColor: log.type === 'success' ? '#34D399' : log.type === 'info' ? '#60A5FA' : '#9CA3AF' 
                            }} />
                            <div className="text-white/70 flex-1">{log.event}</div>
                            <div className="text-white/20 text-[10px]">HASH: {getHash(log.event + log.time)}</div>
                        </div>
                        ))}
                    </div>
                </StatusCard>
            </div>
        </div>

      </div>
    </div>
  );
};

export default StatusPanel;
