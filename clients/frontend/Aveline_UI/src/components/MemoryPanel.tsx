import React, { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../api/apiService';
import { Message, WeightedMemory } from '../types/index';
import { 
  Database, 
  Search, 
  Download, 
  Trash2, 
  Brain, 
  Cpu, 
  Zap,
  Clock,
  Hash,
  Activity,
  GitBranch,
  Layers,
  FileText
} from 'lucide-react';
import { InfoCard } from './InfoCard';

interface MemoryPanelProps {
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  onToggleTTS: (id: number) => void;
  onDelete: (id: number) => void;
  storageKey: string;
}

const Tag = ({ text, color = "emerald" }: { text: string, color?: "emerald" | "blue" | "purple" | "rose" | "amber" }) => {
    const colors = {
        emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300",
        blue: "bg-blue-500/10 border-blue-500/20 text-blue-300",
        purple: "bg-purple-500/10 border-purple-500/20 text-purple-300",
        rose: "bg-rose-500/10 border-rose-500/20 text-rose-300",
        amber: "bg-amber-500/10 border-amber-500/20 text-amber-300"
    };

    return (
        <span className={`px-2 py-1 text-[10px] rounded border ${colors[color]} font-mono inline-block`}>
            {text}
        </span>
    );
};

const MemoryPanel = React.memo(({ messages, setMessages, onDelete, storageKey }: MemoryPanelProps) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'session' | 'weighted'>('session');
  const [weightedMemories, setWeightedMemories] = useState<WeightedMemory[]>([]);
  const [backendStats, setBackendStats] = useState<{topic_weights?: Record<string, number>}>({});

  useEffect(() => {
    const fetchMemories = async () => {
        try {
            const res = await api.getWeightedMemories(50, 0.1);
            if (res.status === 'success') {
                setWeightedMemories(res.data);
                if (res.stats) {
                    setBackendStats(res.stats);
                }
            }
        } catch (e) {
            console.error("Failed to fetch weighted memories", e);
        }
    };
    fetchMemories();
    const interval = setInterval(fetchMemories, 30000);
    return () => clearInterval(interval);
  }, []);

  // Derived state for "Simulated Memory"
  const memoryStats = useMemo(() => {
    const userMsgs = messages.filter(m => m.isUser);
    const botMsgs = messages.filter(m => !m.isUser);
    const totalChars = messages.reduce((acc, m) => acc + m.text.length, 0);
    
    let topics: string[] = [];
    if (backendStats?.topic_weights && Object.keys(backendStats.topic_weights).length > 0) {
        topics = Object.keys(backendStats.topic_weights)
            .sort((a, b) => (backendStats.topic_weights?.[b] || 0) - (backendStats.topic_weights?.[a] || 0))
            .slice(0, 10);
    } else {
        // Simple topic extraction (mock)
        const words = messages.flatMap(m => m.text.split(' ')).filter(w => w.length > 4);
        topics = Array.from(new Set(words)).slice(0, 5);
    }

    return {
        userCount: userMsgs.length,
        botCount: botMsgs.length,
        totalChars,
        topics,
        lastActive: messages.length > 0 ? new Date(messages[messages.length - 1].id).toLocaleTimeString() : "N/A"
    };
  }, [messages, backendStats]);

  const filteredMessages = useMemo(() => {
    return messages.filter(m => 
      m.text.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [messages, searchTerm]);

  const filteredWeightedMemories = useMemo(() => {
    return weightedMemories.filter(m => 
      m.content.toLowerCase().includes(searchTerm.toLowerCase()) ||
      m.topics.some(t => t.toLowerCase().includes(searchTerm.toLowerCase()))
    );
  }, [weightedMemories, searchTerm]);

  const handleExport = () => {
    try {
      const data = JSON.stringify(messages, null, 2);
      const blob = new Blob([data], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `aveline_memory_dump_${new Date().toISOString().split('T')[0]}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Export failed", e);
    }
  };

  const handleClearMemory = async () => {
    if (window.confirm('WARNING: Irreversible data deletion. Proceed to clear all memory logs?')) {
        try { await api.clearMemory(); } catch {}
        try { localStorage.removeItem(storageKey); } catch {}
        setMessages([{ id: Date.now(), isUser: false, text: "System memory purged. Aveline core re-initialized." }]);
    }
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex items-end justify-between border-b border-white/10 pb-6">
          <div>
            <h1 className="text-4xl font-bold tracking-tight text-white mb-2 font-display">
              MNEMOSYNE <span className="text-emerald-500">ARCHIVE</span>
            </h1>
            <div className="flex items-center gap-4 text-xs font-mono text-white/40">
              <span className="flex items-center gap-1"><Database size={12}/> DB_SIZE: {(memoryStats.totalChars / 1024).toFixed(2)} KB</span>
              <span className="flex items-center gap-1"><Activity size={12}/> LAST_WRITE: {memoryStats.lastActive}</span>
              <span className="flex items-center gap-1"><GitBranch size={12}/> NODES: {messages.length}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleExport} className="p-2 hover:bg-white/10 rounded-lg text-white/40 hover:text-white transition-colors">
                <Download size={18} />
            </button>
            <button onClick={handleClearMemory} className="p-2 hover:bg-rose-500/10 rounded-lg text-white/40 hover:text-rose-400 transition-colors">
                <Trash2 size={18} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full">
            
            {/* Left Column: Cognitive Synthesis (The "Brain" View) */}
            <div className="lg:col-span-1 space-y-6">
                <InfoCard title="COGNITIVE SYNTHESIS" className="bg-emerald-900/5 border-emerald-500/10 h-full">
                    <div className="space-y-6">
                        
                        {/* Active Context */}
                        <div>
                            <div className="text-[10px] text-emerald-400/50 mb-2 font-mono flex items-center gap-2">
                                <Brain size={12} /> ACTIVE CONTEXT WINDOW
                            </div>
                            <div className="bg-black/20 rounded-lg p-3 border border-emerald-500/10 min-h-[100px] relative overflow-hidden">
                                <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/20 pointer-events-none"></div>
                                <div className="space-y-2">
                                    {messages.slice(-3).map((m, i) => (
                                        <div key={i} className="text-xs text-emerald-100/60 truncate">
                                            <span className="text-emerald-500/30 mr-2">{m.isUser ? '>' : '#'}</span>
                                            {m.text}
                                        </div>
                                    ))}
                                    {messages.length === 0 && <span className="text-white/20 text-xs italic">No active context loaded.</span>}
                                </div>
                            </div>
                        </div>

                        {/* Semantic Clusters */}
                        <div>
                             <div className="text-[10px] text-emerald-400/50 mb-2 font-mono flex items-center gap-2">
                                <Layers size={12} /> SEMANTIC CLUSTERS
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {memoryStats.topics.map((t, i) => (
                                    <Tag key={i} text={t.toUpperCase()} color="emerald" />
                                ))}
                                <Tag text="USER_INTERACTION" color="blue" />
                                <Tag text="SYSTEM_LOGS" color="purple" />
                            </div>
                        </div>

                        {/* Processing Status */}
                        <div>
                             <div className="text-[10px] text-emerald-400/50 mb-2 font-mono flex items-center gap-2">
                                <Cpu size={12} /> NEURAL PROCESSING
                            </div>
                            <div className="space-y-3">
                                <div className="flex items-center justify-between text-xs text-white/40">
                                    <span>Consolidation</span>
                                    <span className="text-emerald-400">98%</span>
                                </div>
                                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                                    <div className="h-full bg-emerald-500/40 w-[98%]"></div>
                                </div>
                                <div className="flex items-center justify-between text-xs text-white/40">
                                    <span>Vector Indexing</span>
                                    <span className="text-blue-400">RUNNING</span>
                                </div>
                                <div className="h-1 bg-white/5 rounded-full overflow-hidden relative">
                                    <motion.div 
                                        className="h-full bg-blue-500/40 w-[30%]"
                                        animate={{ left: ["0%", "100%"] }}
                                        transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Auto-Summary (Mock) */}
                        <div className="pt-4 border-t border-white/5">
                            <div className="text-[10px] text-amber-400/50 mb-2 font-mono flex items-center gap-2">
                                <FileText size={12} /> LATEST EPISODIC RECALL
                            </div>
                            <p className="text-xs text-white/50 leading-relaxed italic">
                                "Interaction patterns suggest user is currently focused on system optimization and persona calibration. Emotional valence is neutral-positive. Recommend maintaining high responsiveness."
                            </p>
                        </div>

                    </div>
                </InfoCard>
            </div>

            {/* Right Column: Raw Logs (The "List" View) */}
            <div className="lg:col-span-2 flex flex-col h-[calc(100vh-200px)]">
                
                {/* Tab Switcher */}
                <div className="flex gap-2 mb-4 p-1 bg-white/5 rounded-lg w-fit">
                    <button 
                        onClick={() => setActiveTab('session')}
                        className={`px-4 py-1.5 rounded-md text-xs font-mono transition-all ${activeTab === 'session' ? 'bg-emerald-500/20 text-emerald-300 shadow-sm' : 'text-white/40 hover:text-white/60'}`}
                    >
                        SESSION_STREAM
                    </button>
                    <button 
                        onClick={() => setActiveTab('weighted')}
                        className={`px-4 py-1.5 rounded-md text-xs font-mono transition-all ${activeTab === 'weighted' ? 'bg-purple-500/20 text-purple-300 shadow-sm' : 'text-white/40 hover:text-white/60'}`}
                    >
                        CORE_MEMORY
                    </button>
                </div>

                <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20" size={16} />
                    <input 
                        type="text" 
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        placeholder="SEARCH MEMORY STREAMS..."
                        className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-3 text-sm text-white focus:outline-none focus:border-emerald-500/30 transition-colors font-mono"
                    />
                </div>

                <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-2">
                    <AnimatePresence mode="wait">
                        {activeTab === 'session' ? (
                            filteredMessages.slice().reverse().map((msg) => (
                            <motion.div
                                key={msg.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, x: -10 }}
                                className="group p-4 rounded-xl bg-white/[0.02] border border-white/[0.05] hover:bg-white/[0.04] transition-colors"
                            >
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`text-[10px] font-bold tracking-wider ${msg.isUser ? 'text-blue-400' : 'text-emerald-400'}`}>
                                                {msg.isUser ? 'USER' : 'AVELINE'}
                                            </span>
                                            <span className="text-[10px] text-white/20 font-mono">
                                                {new Date(msg.id).toLocaleTimeString()}
                                            </span>
                                        </div>
                                        <div className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap font-sans">
                                            {msg.text}
                                        </div>
                                    </div>
                                    <div className="opacity-0 group-hover:opacity-100 transition-opacity flex flex-col gap-2">
                                        <button 
                                            onClick={() => onDelete(msg.id)}
                                            className="p-1.5 hover:bg-rose-500/20 rounded text-white/20 hover:text-rose-400 transition-colors"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                        <button className="p-1.5 hover:bg-white/10 rounded text-white/20 hover:text-white transition-colors">
                                            <Zap size={14} />
                                        </button>
                                    </div>
                                </div>
                            </motion.div>
                            ))
                        ) : (
                            filteredWeightedMemories.map((mem) => (
                                <motion.div
                                    key={mem.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, x: -10 }}
                                    className="group p-4 rounded-xl bg-purple-500/[0.02] border border-purple-500/[0.1] hover:bg-purple-500/[0.04] transition-colors"
                                >
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2 mb-2">
                                                <span className="text-[10px] font-bold tracking-wider text-purple-400">
                                                    WEIGHT: {mem.weight.toFixed(2)}
                                                </span>
                                                <span className="text-[10px] text-white/20 font-mono">
                                                    {new Date(mem.timestamp * 1000).toLocaleString()}
                                                </span>
                                                <div className="flex flex-wrap gap-1 ml-2">
                                                    {mem.is_important && (
                                                        <span className="text-[9px] px-1.5 py-0.5 bg-amber-500/20 text-amber-300 rounded border border-amber-500/20">IMPORTANT</span>
                                                    )}
                                                    {mem.topics.map(t => (
                                                        <span key={t} className="text-[9px] px-1.5 py-0.5 bg-white/5 rounded text-white/40 border border-white/5">{t}</span>
                                                    ))}
                                                    {mem.emotions && mem.emotions.map(e => (
                                                        <span key={e} className="text-[9px] px-1.5 py-0.5 bg-rose-500/10 text-rose-300 rounded border border-rose-500/20">{e}</span>
                                                    ))}
                                                </div>
                                            </div>
                                            <div className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap font-sans">
                                                {mem.content}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            ))
                        )}
                    </AnimatePresence>
                    {((activeTab === 'session' && filteredMessages.length === 0) || (activeTab === 'weighted' && filteredWeightedMemories.length === 0)) && (
                        <div className="text-center py-20 text-white/20 text-sm font-mono">
                            NO MATCHING MEMORY FRAGMENTS FOUND
                        </div>
                    )}
                </div>
            </div>

        </div>
      </div>
    </div>
  );
});

export default MemoryPanel;
