import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Database, Cpu, Wifi, Shield, Gauge, Layers, Brain, ListChecks, Boxes, ChevronDown } from 'lucide-react';
import { api } from '../../api/apiService';
import config from '../../api/config';
import DeviceWidget from '../DeviceWidget';

type MobileStatusPanelProps = {
  connected: boolean;
  clock: string;
  stats: {
    cpu: number;
    gpu: number;
    memory: number;
    scheduler?: any;
  };
  lifeStatus: any;
  colors?: [string, string, string, string];
  emotion: any;
};

type MemoryHeatmapProps = {
  activationGrid: number[];
};

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

function getSafeColors(colors?: [string, string, string, string]) {
  return colors ?? ['#34d399', '#22c55e', '#60a5fa', '#a78bfa'];
}

function getMobileStatusSections() {
  return [
    {
      id: 'resources',
      title: '资源监控',
      subtitle: 'CPU / 内存 / GPU',
      icon: <Cpu size={16} className="opacity-80" />,
    },
    {
      id: 'scheduler',
      title: '调度引擎',
      subtitle: 'C++ 任务调度与 GPU 显存',
      icon: <ListChecks size={16} className="opacity-80" />,
    },
    {
      id: 'bio',
      title: '生物系统',
      subtitle: '神经递质与生理指标',
      icon: <Brain size={16} className="opacity-80" />,
    },
    {
      id: 'memory',
      title: '记忆矩阵',
      subtitle: '长期记忆与上下文状态',
      icon: <Database size={16} className="opacity-80" />,
    },
    {
      id: 'modules',
      title: '模块健康',
      subtitle: '服务与子系统状态',
      icon: <Layers size={16} className="opacity-80" />,
    },
    {
      id: 'network',
      title: '网络与连接',
      subtitle: '链路状态与传输质量',
      icon: <Wifi size={16} className="opacity-80" />,
    },
    {
      id: 'security',
      title: '安全与权限',
      subtitle: '隐私、鉴权与设备能力',
      icon: <Shield size={16} className="opacity-80" />,
    },
  ] as const;
}

function MobileStatusOverview({ connected, clock, lifeStatus, emotion, accent, cpu, mem, gpu }: {
  connected: boolean;
  clock: string;
  lifeStatus: any;
  emotion: any;
  accent: string;
  cpu: number;
  mem: number;
  gpu: number;
}) {
  const coreStatus = connected ? 'ONLINE' : 'OFFLINE';
  const syncRate = connected ? 99.9 : 0;

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4 overflow-hidden relative">
        <div
          className="absolute inset-0 opacity-40"
          style={{
            background:
              `radial-gradient(800px circle at 20% 10%, ${accent}22, transparent 45%), radial-gradient(900px circle at 80% 80%, ${accent}14, transparent 55%)`,
          }}
        />
        <div className="relative">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em]">CORE STATUS</div>
              <div className="mt-2 text-2xl font-cinzel tracking-widest text-white">AVELINE</div>
              <div className="mt-1 text-xs font-mono text-white/30 truncate">{clock}</div>
            </div>
            <div className="flex flex-col items-end gap-2">
              <div
                className={`px-3 py-1 rounded-full text-[10px] font-mono tracking-widest border ${connected ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' : 'bg-rose-500/10 text-rose-300 border-rose-500/20'}`}
              >
                {connected ? 'LINK // OK' : 'LINK // DOWN'}
              </div>
              <div className="text-[10px] font-mono text-white/30">EMO: {String((lifeStatus as any)?.emotion || emotion || 'NEUTRAL').toUpperCase()}</div>
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-white/5 grid grid-cols-2 gap-4">
            <div className="bg-black/20 border border-white/5 rounded-xl p-3">
              <div className="text-[10px] text-white/30 font-mono">CORE_STATUS</div>
              <div className="mt-1 text-sm font-mono text-white/80" style={{ color: connected ? undefined : '#fda4af' }}>
                {coreStatus}
              </div>
            </div>
            <div className="bg-black/20 border border-white/5 rounded-xl p-3">
              <div className="text-[10px] text-white/30 font-mono">SYNC_RATE</div>
              <div className="mt-1 text-sm font-mono text-white/80">{syncRate.toFixed(1)}%</div>
            </div>
          </div>
        </div>
      </div>

      <div className="glass-card rounded-2xl p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em]">KEY OVERVIEW</div>
          <div className="text-[10px] font-mono text-white/30">{connected ? 'ACTIVE' : 'STANDBY'}</div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="p-3 bg-white/5 rounded-xl border border-white/10">
            <div className="text-[10px] text-white/30 font-mono mb-1">CPU</div>
            <div className="text-lg font-mono text-white/90 text-glow">{Number.isFinite(cpu) ? cpu.toFixed(0) : '—'}<span className="text-white/30 ml-1">%</span></div>
          </div>
          <div className="p-3 bg-white/5 rounded-xl border border-white/10">
            <div className="text-[10px] text-white/30 font-mono mb-1">MEM</div>
            <div className="text-lg font-mono text-white/90 text-glow">{Number.isFinite(mem) ? mem.toFixed(0) : '—'}<span className="text-white/30 ml-1">%</span></div>
          </div>
          <div className="p-3 bg-white/5 rounded-xl border border-white/10">
            <div className="text-[10px] text-white/30 font-mono mb-1">GPU</div>
            <div className="text-lg font-mono text-white/90 text-glow">{Number.isFinite(gpu) ? gpu.toFixed(0) : '—'}<span className="text-white/30 ml-1">%</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileStatusSectionContent({ id, connected, clock, stats, lifeStatus, colors, emotion, heatmapData }: MobileStatusPanelProps & { id: string, heatmapData?: number[] }) {
  const safeColors = getSafeColors(colors);
  const accent = safeColors[1];

  const cpu = Number.isFinite(stats?.cpu) ? stats.cpu : NaN;
  const mem = Number.isFinite(stats?.memory) ? stats.memory : NaN;
  const gpu = Number.isFinite(stats?.gpu) ? stats.gpu : NaN;

  if (id === 'overview') {
    return (
      <MobileStatusOverview
        connected={connected}
        clock={clock}
        lifeStatus={lifeStatus}
        emotion={emotion}
        accent={accent}
        cpu={cpu}
        mem={mem}
        gpu={gpu}
      />
    );
  }

  if (id === 'resources') {
    return (
      <div className="space-y-4">
        <div className="glass-card rounded-2xl p-4">
          <DeviceWidget cpu={stats.cpu} gpu={stats.gpu} memory={stats.memory} colors={safeColors} emotion={emotion} />
        </div>
      </div>
    );
  }

  if (id === 'scheduler') {
    const scheduler = stats?.scheduler || {};
    const tasks = scheduler.tasks || { total: 0, running: 0, pending: 0, completed: 0, failed: 0 };
    const resources = scheduler.resources || { gpu_mem_used: 0, gpu_mem_total: 0, cpu_load: 0 };
    const gpuMemUsed = Number(resources.gpu_mem_used || 0);
    const gpuMemTotal = Number(resources.gpu_mem_total || 0);
    const gpuMemPercent = gpuMemTotal > 0 ? (gpuMemUsed / gpuMemTotal) * 100 : 0;

    return (
      <div className="space-y-4">
        <div className="glass-card rounded-2xl p-4">
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

        <div className="glass-card rounded-2xl p-4">
          <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
            <Boxes size={12} />
            GPU Memory
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
      </div>
    );
  }

  if (id === 'memory') {
    return (
      <div className="glass-card rounded-2xl p-4 flex flex-col items-center">
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3 w-full text-left flex items-center gap-2">
          <Database size={12} />
          Memory Matrix
        </div>
        <MemoryHeatmap activationGrid={heatmapData || []} />
        <div className="mt-4 w-full text-[10px] font-mono text-white/30 text-center">
          Weighted Memory Activation
        </div>
      </div>
    );
  }

  if (id === 'bio') {
    const bio = (lifeStatus as any)?.bio || {};
    const energy = (lifeStatus as any)?.energy ?? 100;
    const hunger = (lifeStatus as any)?.hunger ?? 0;
    const thirst = (lifeStatus as any)?.thirst ?? 0;

    return (
      <div className="glass-card rounded-2xl p-4">
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3">NEUROTRANSMITTERS</div>
        <div className="space-y-2 text-xs font-mono text-white/50 mb-4">
          <div className="flex items-center justify-between"><span>DOPAMINE</span><span className="text-white/70">{((bio.dopamine || 0) * 100).toFixed(0)}%</span></div>
          <div className="flex items-center justify-between"><span>SEROTONIN</span><span className="text-white/70">{((bio.serotonin || 0) * 100).toFixed(0)}%</span></div>
          <div className="flex items-center justify-between"><span>NOREPINEPHRINE</span><span className="text-white/70">{((bio.norepinephrine || 0) * 100).toFixed(0)}%</span></div>
          <div className="flex items-center justify-between"><span>OXYTOCIN</span><span className="text-white/70">{((bio.oxytocin || 0) * 100).toFixed(0)}%</span></div>
        </div>

        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3">PHYSIOLOGY</div>
        <div className="space-y-2 text-xs font-mono text-white/50">
          <div className="flex items-center justify-between"><span>ENERGY</span><span className="text-white/70">{Number(energy).toFixed(0)}%</span></div>
          <div className="flex items-center justify-between"><span>HUNGER</span><span className="text-white/70">{Number(hunger).toFixed(0)}%</span></div>
          <div className="flex items-center justify-between"><span>THIRST</span><span className="text-white/70">{Number(thirst).toFixed(0)}%</span></div>
        </div>
      </div>
    );
  }

  if (id === 'modules') {
    const activity = String((lifeStatus as any)?.activity || '—');
    const energy = (lifeStatus as any)?.energy;
    const hunger = (lifeStatus as any)?.hunger;
    const thirst = (lifeStatus as any)?.thirst;

    return (
      <div className="glass-card rounded-2xl p-4">
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3">SUBSYSTEMS</div>
        <div className="space-y-2 text-xs font-mono text-white/50">
          <div className="flex items-center justify-between"><span>ACTIVITY</span><span className="text-white/70 truncate max-w-[60%] text-right">{activity}</span></div>
          <div className="flex items-center justify-between"><span>ENERGY</span><span className="text-white/70">{Number.isFinite(Number(energy)) ? String(energy) : '—'}</span></div>
          <div className="flex items-center justify-between"><span>HUNGER</span><span className="text-white/70">{Number.isFinite(Number(hunger)) ? String(hunger) : '—'}</span></div>
          <div className="flex items-center justify-between"><span>THIRST</span><span className="text-white/70">{Number.isFinite(Number(thirst)) ? String(thirst) : '—'}</span></div>
        </div>
      </div>
    );
  }

  if (id === 'network') {
    const ws = String((lifeStatus as any)?.ws_status || (connected ? 'connected' : 'disconnected'));
    const latency = Number((lifeStatus as any)?.latency_ms);

    return (
      <div className="glass-card rounded-2xl p-4">
        <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3">LINK</div>
        <div className="space-y-2 text-xs font-mono text-white/50">
          <div className="flex items-center justify-between"><span>WS</span><span className="text-white/70">{ws}</span></div>
          <div className="flex items-center justify-between"><span>LATENCY</span><span className="text-white/70">{Number.isFinite(latency) ? `${latency.toFixed(0)}ms` : '—'}</span></div>
          <div className="flex items-center justify-between"><span>API_BASE</span><span className="text-white/70 truncate max-w-[60%] text-right">{String(localStorage.getItem('AVELINE_API_URL') || config.apiBaseUrl)}</span></div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="text-[10px] font-bold text-white/30 uppercase tracking-[0.2em] mb-3">POLICY</div>
      <div className="text-xs font-mono text-white/50 leading-relaxed">
        未来这里可以接后端的权限/隐私配置：访问令牌、通知、麦克风、后台常驻等。
      </div>
    </div>
  );
}

export function MobileStatusPanel({ connected, clock, stats, lifeStatus, colors, emotion }: MobileStatusPanelProps) {
  const [openSection, setOpenSection] = useState<string | null>('overview');
  const [mountedSectionIds, setMountedSectionIds] = useState<string[]>(['overview']);
  const [heatmapData, setHeatmapData] = useState<number[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (openSection === 'memory') {
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
    }
    return () => { cancelled = true; };
  }, [openSection]);

  const safeColors = getSafeColors(colors);
  const accent = safeColors[1];

  const sections = useMemo(
    () => [
      {
        id: 'overview',
        title: '概览',
        subtitle: '核心状态与关键指标',
        icon: <Gauge size={16} className="opacity-80" />,
      },
      ...getMobileStatusSections(),
    ],
    []
  );

  return (
    <div className="space-y-3">
      {sections.map((s) => {
        const isOpen = openSection === s.id;
        const isMounted = mountedSectionIds.includes(s.id);
        return (
          <div key={s.id} className="glass-card rounded-2xl overflow-hidden">
            <button
              type="button"
              onClick={() => {
                setOpenSection((prev) => {
                  const next = prev === s.id ? null : s.id;
                  if (next) setMountedSectionIds((prevMounted) => (prevMounted.includes(next) ? prevMounted : [...prevMounted, next]));
                  return next;
                });
              }}
              className="w-full flex items-center justify-between gap-3 p-4 text-left"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center" style={{ boxShadow: `0 0 18px ${accent}14` }}>
                  {s.icon}
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-white/90 truncate">{s.title}</div>
                  <div className="text-[11px] text-white/35 truncate">{s.subtitle}</div>
                </div>
              </div>
              <ChevronDown
                size={18}
                className={`text-white/30 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
              />
            </button>

            <div
              className={`grid transition-[grid-template-rows] duration-200 ease-out ${isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
            >
              <div className="overflow-hidden">
                <div
                  className={`px-4 transition-all duration-200 ease-out ${
                    isOpen ? 'pb-4 opacity-100 translate-y-0' : 'pb-0 opacity-0 -translate-y-1'
                  }`}
                >
                  {isMounted && (
                    <MobileStatusSectionContent
                      id={s.id}
                      connected={connected}
                      clock={clock}
                      stats={stats}
                      lifeStatus={lifeStatus}
                      colors={colors}
                      emotion={emotion}
                      heatmapData={heatmapData}
                    />
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
