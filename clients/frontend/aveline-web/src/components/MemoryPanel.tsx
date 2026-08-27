import React, { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../api/apiService';
import { Message, WeightedMemory } from '../types/index';
import { CustomSelect } from './ui/CustomSelect';
import { Calendar as CalendarPopup } from './ui/Calendar';
import { useLongPress } from '../hooks/useLongPress';
import { useAvelineStore } from '../store/useStore';
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
  FileText,
  Filter,
  Calendar,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { InfoCard } from './InfoCard';

interface MemoryPanelProps {
  memoryData: Message[];
  onClearHistory: () => void;
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

const SessionMessageItem = ({ msg, isExpanded, onToggleExpand, onDelete, domRef }: { 
    msg: Message, 
    isExpanded: boolean, 
    onToggleExpand: (id: string | number) => void,
    onDelete: (msg: Message) => void,
    domRef?: (el: HTMLDivElement | null) => void
}) => {
    const bind = useLongPress((e) => {
        onDelete(msg);
    }, () => {});

    const shouldTruncate = msg.text.length > 150;
    const displayText = shouldTruncate && !isExpanded 
        ? msg.text.substring(0, 150) + "..." 
        : msg.text;

    return (
        <motion.div
            ref={domRef}
            layout
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, x: -10 }}
            className="group p-4 rounded-xl bg-white/[0.02] border border-white/[0.05] hover:bg-white/[0.04] transition-colors relative"
            {...bind}
            onContextMenu={(e) => {
                e.preventDefault();
                onDelete(msg);
            }}
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
                        {displayText}
                        {shouldTruncate && (
                            <button 
                                onClick={(e) => { e.stopPropagation(); onToggleExpand(msg.id); }}
                                className="ml-2 text-emerald-400/70 hover:text-emerald-300 text-[10px] font-mono inline-flex items-center gap-1 transition-colors uppercase tracking-wider bg-emerald-500/5 px-1.5 py-0.5 rounded border border-emerald-500/10"
                            >
                                {isExpanded ? (
                                    <>Collapse <ChevronUp size={8} /></>
                                ) : (
                                    <>Expand <ChevronDown size={8} /></>
                                )}
                            </button>
                        )}
                    </div>
                </div>
                <div className="opacity-0 group-hover:opacity-100 transition-opacity flex flex-col gap-2">
                    <button 
                        onClick={(e) => { e.stopPropagation(); onDelete(msg); }}
                        className="p-1.5 hover:bg-rose-500/10 rounded text-white/20 hover:text-rose-400 transition-colors"
                        title="Delete Message"
                    >
                        <Trash2 size={14} />
                    </button>
                </div>
            </div>
        </motion.div>
    );
};

const MemoryPanel = React.memo(({ memoryData, onClearHistory }: MemoryPanelProps) => {
  const { setMessages } = useAvelineStore();
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'session' | 'weighted'>('session');
  const [weightedMemories, setWeightedMemories] = useState<WeightedMemory[]>([]);
  const [backendStats, setBackendStats] = useState<{topic_weights?: Record<string, number>}>({});
  
  // Filters
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [roleFilter, setRoleFilter] = useState('all'); // New Role Filter for Session
  const [showCalendar, setShowCalendar] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const calendarButtonRef = React.useRef<HTMLButtonElement>(null); // Ref for Calendar positioning
  
  // UI State
  const [expandedMemories, setExpandedMemories] = useState<Record<string, boolean>>({});
  const [expandedSessionMessages, setExpandedSessionMessages] = useState<Record<string, boolean>>({});
  
  // Refs for scrolling
  const sessionMessageRefs = React.useRef<Record<string, HTMLDivElement | null>>({});
  const weightedMemoryRefs = React.useRef<Record<string, HTMLDivElement | null>>({});

  const scrollToDate = (date: Date) => {
      // Find the first message matching the date
      const targetDateStr = date.toDateString();
      let targetId: string | null = null;
      
      if (activeTab === 'session') {
          const msg = filteredMessages.find(m => new Date(m.id).toDateString() === targetDateStr);
          if (msg) targetId = msg.id.toString();
      } else {
          const mem = filteredWeightedMemories.find(m => new Date(m.timestamp * 1000).toDateString() === targetDateStr);
          if (mem) targetId = mem.id;
      }

      if (targetId) {
          const refs = activeTab === 'session' ? sessionMessageRefs.current : weightedMemoryRefs.current;
          const el = refs[targetId];
          if (el) {
              el.scrollIntoView({ behavior: 'smooth', block: 'center' });
              // Optional: Highlight effect
              el.classList.add('bg-emerald-500/20');
              setTimeout(() => el.classList.remove('bg-emerald-500/20'), 2000);
          }
      }
  };

  const toggleSessionExpand = (id: string | number) => {
    setExpandedSessionMessages(prev => ({
        ...prev,
        [id.toString()]: !prev[id.toString()]
    }));
  };

  const handleDeleteSessionMessage = async (msg: Message) => {
      // Use simple confirm for now, can be replaced with custom dialog if needed
      if (confirm('Delete this message?')) {
          try {
              // Assuming "default" session for now as per current architecture
              await api.deleteMessage("default", msg.id.toString());
              setMessages(prev => prev.filter(m => m.id !== msg.id));
          } catch (e) {
              console.error("Failed to delete message", e);
          }
      }
  };

  const handleDeleteWeightedMemory = async (id: string) => {
      if (confirm('Delete this core memory?')) {
          try {
              await api.deleteWeightedMemory(id);
              setWeightedMemories(prev => prev.filter(m => m.id !== id));
          } catch (e) {
              console.error("Failed to delete weighted memory", e);
          }
      }
  };

  useEffect(() => {
    const fetchMemories = async () => {
        try {
            const res = await api.getWeightedMemories(100, 0.1); // Increased limit for better filtering context
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

  // Extract unique categories (topics) from loaded memories
  const availableCategories = useMemo(() => {
    const topics = new Set<string>();
    weightedMemories.forEach(m => {
        m.topics.forEach(t => topics.add(t));
    });
    return Array.from(topics).sort();
  }, [weightedMemories]);

  // Derived state for "Simulated Memory"
  const memoryStats = useMemo(() => {
    const userMsgs = memoryData.filter(m => m.isUser);
    const botMsgs = memoryData.filter(m => !m.isUser);
    const totalChars = memoryData.reduce((acc, m) => acc + m.text.length, 0);
    
    let topics: string[] = [];
    if (backendStats?.topic_weights && Object.keys(backendStats.topic_weights).length > 0) {
        topics = Object.keys(backendStats.topic_weights)
            .sort((a, b) => (backendStats.topic_weights?.[b] || 0) - (backendStats.topic_weights?.[a] || 0))
            .slice(0, 10);
    } else {
        // Simple topic extraction (mock)
        const words = memoryData.flatMap(m => m.text.split(' ')).filter(w => w.length > 4);
        topics = Array.from(new Set(words)).slice(0, 5);
    }

    return {
        userCount: userMsgs.length,
        botCount: botMsgs.length,
        totalChars,
        topics,
        lastActive: memoryData.length > 0 ? new Date(memoryData[memoryData.length - 1].id).toLocaleTimeString() : "N/A"
    };
  }, [memoryData, backendStats]);

  const filteredMessages = useMemo(() => {
    return memoryData.filter(m => {
      // 1. Search Term
      if (searchTerm && !m.text.toLowerCase().includes(searchTerm.toLowerCase())) {
          return false;
      }

      // 2. Role Filter (Category for Session)
      if (roleFilter !== 'all') {
          if (roleFilter === 'user' && !m.isUser) return false;
          if (roleFilter === 'aveline' && m.isUser) return false;
      }

      return true;
    });
  }, [memoryData, searchTerm, roleFilter]); // selectedDate removed from dependencies

  const filteredWeightedMemories = useMemo(() => {
    return weightedMemories.filter(m => {
      // 1. Search Term
      const matchesSearch = m.content.toLowerCase().includes(searchTerm.toLowerCase()) ||
                            m.topics.some(t => t.toLowerCase().includes(searchTerm.toLowerCase()));
      if (!matchesSearch) return false;

      // 2. Category Filter
      if (categoryFilter !== 'all') {
        if (categoryFilter === 'IMPORTANT') {
            if (!m.is_important) return false;
        } else if (!m.topics.includes(categoryFilter)) {
            return false;
        }
      }

      return true;
    });
  }, [weightedMemories, searchTerm, categoryFilter]); // selectedDate removed

  const toggleExpand = (id: string) => {
    setExpandedMemories(prev => ({
        ...prev,
        [id]: !prev[id]
    }));
  };

  const handleExport = () => {
    try {
      const data = JSON.stringify(memoryData, null, 2);
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


  useEffect(() => {
    if (selectedDate) {
        // Allow time for the list to re-render
        setTimeout(() => {
            scrollToDate(selectedDate);
        }, 100);
    }
  }, [selectedDate, activeTab]);

  return (
    <div className="flex-1 p-4 sm:p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="flex flex-col gap-6 pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-emerald-500/10 rounded-xl border border-emerald-500/20">
                <Database className="text-emerald-400" size={20} />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white font-display leading-tight">
                  MNEMOSYNE ARCHIVE
                </h1>
                <div className="text-[10px] text-white/40 font-mono tracking-wider uppercase">Cognitive Storage System</div>
              </div>
            </div>
            
            <div className="flex gap-2">
              <button onClick={handleExport} className="p-2 hover:bg-white/10 rounded-lg text-white/40 hover:text-white transition-colors border border-transparent hover:border-white/10">
                  <Download size={16} />
              </button>
              <button onClick={onClearHistory} className="p-2 hover:bg-rose-500/10 rounded-lg text-white/40 hover:text-rose-400 transition-colors border border-transparent hover:border-rose-500/20">
                  <Trash2 size={16} />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 sm:gap-4">
             <div className="bg-black/20 border border-white/5 rounded-lg px-3 py-2 flex items-center gap-3">
                <Database size={14} className="text-emerald-500/50" />
                <div className="flex flex-col">
                   <span className="text-[9px] text-white/30 font-mono uppercase">DB Size</span>
                   <span className="text-xs text-white/70 font-mono">{(memoryStats.totalChars / 1024).toFixed(2)} KB</span>
                </div>
             </div>
             <div className="bg-black/20 border border-white/5 rounded-lg px-3 py-2 flex items-center gap-3">
                <Activity size={14} className="text-blue-500/50" />
                <div className="flex flex-col">
                   <span className="text-[9px] text-white/30 font-mono uppercase">Last Write</span>
                   <span className="text-xs text-white/70 font-mono">{memoryStats.lastActive}</span>
                </div>
             </div>
             <div className="bg-black/20 border border-white/5 rounded-lg px-3 py-2 flex items-center gap-3">
                <GitBranch size={14} className="text-purple-500/50" />
                <div className="flex flex-col">
                   <span className="text-[9px] text-white/30 font-mono uppercase">Nodes</span>
                   <span className="text-xs text-white/70 font-mono">{memoryData.length}</span>
                </div>
             </div>
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
                                    {memoryData.slice(-3).map((m: Message, i) => (
                                        <div key={i} className="text-xs text-emerald-100/60 truncate">
                                            <span className="text-emerald-500/30 mr-2">{m.isUser ? '>' : '#'}</span>
                                            {m.text}
                                        </div>
                                    ))}
                                    {memoryData.length === 0 && <span className="text-white/20 text-xs italic">No active context loaded.</span>}
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
                <div className="flex flex-wrap gap-2 mb-4 p-1 bg-white/5 rounded-lg w-full sm:w-fit">
                    <button 
                        onClick={() => setActiveTab('session')}
                        className={`flex-1 sm:flex-none px-4 py-1.5 rounded-md text-xs font-mono transition-all text-center ${activeTab === 'session' ? 'bg-emerald-500/20 text-emerald-300 shadow-sm' : 'text-white/40 hover:text-white/60'}`}
                    >
                        SESSION_STREAM
                    </button>
                    <button 
                        onClick={() => setActiveTab('weighted')}
                        className={`flex-1 sm:flex-none px-4 py-1.5 rounded-md text-xs font-mono transition-all text-center ${activeTab === 'weighted' ? 'bg-purple-500/20 text-purple-300 shadow-sm' : 'text-white/40 hover:text-white/60'}`}
                    >
                        CORE_MEMORY
                    </button>
                </div>

                {/* Filters & Search */}
                <div className="space-y-3 mb-4">
                    <div className="flex flex-wrap gap-2 items-center">
                        
                        <div className="relative shrink-0">
                            <button 
                                ref={calendarButtonRef}
                                onClick={() => setShowCalendar(!showCalendar)}
                                className={`p-2 rounded-lg transition-colors border border-transparent ${
                                    selectedDate || showCalendar ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-white/40 hover:text-white hover:bg-white/5 hover:border-white/10'
                                }`}
                                title="Locate Date"
                            >
                                <Calendar size={16} />
                            </button>
                            <AnimatePresence>
                                {showCalendar && (
                                    <CalendarPopup 
                                        selectedDate={selectedDate}
                                        onSelectDate={(date) => {
                                            setSelectedDate(date);
                                            setShowCalendar(false);
                                        }}
                                        onClose={() => setShowCalendar(false)}
                                        triggerRef={calendarButtonRef}
                                    />
                                )}
                            </AnimatePresence>
                        </div>
                        
                        {activeTab === 'weighted' && (
                            <div className="flex-1 min-w-[140px] max-w-[200px]">
                                <CustomSelect
                                    value={categoryFilter}
                                    onChange={setCategoryFilter}
                                    options={[
                                        { value: 'all', label: 'ALL CATEGORIES' },
                                        { value: 'IMPORTANT', label: '★ IMPORTANT' },
                                        ...availableCategories.map(c => ({ value: c, label: c.toUpperCase() }))
                                    ]}
                                    placeholder="CATEGORY"
                                    className="w-full"
                                />
                            </div>
                        )}

                        {activeTab === 'session' && (
                            <div className="flex-1 min-w-[140px] max-w-[200px]">
                                <CustomSelect
                                    value={roleFilter}
                                    onChange={setRoleFilter}
                                    options={[
                                        { value: 'all', label: 'ALL ROLES' },
                                        { value: 'user', label: 'USER ONLY' },
                                        { value: 'aveline', label: 'AVELINE ONLY' }
                                    ]}
                                    placeholder="CATEGORY"
                                    className="w-full"
                                />
                            </div>
                        )}
                    </div>

                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20" size={14} />
                        <input 
                            type="text"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            placeholder={activeTab === 'session' ? "Search session logs..." : "Search core memories..."}
                            className="w-full bg-black/20 border border-white/5 rounded-lg pl-9 pr-4 py-2 text-xs font-mono text-white/70 placeholder-white/20 focus:outline-none focus:border-emerald-500/30 transition-colors"
                        />
                    </div>
                </div>

                {/* Content Area */}
                <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 min-h-0">
                    <AnimatePresence mode="popLayout">
                        {activeTab === 'session' ? (
                            <div className="space-y-3">
                                {filteredMessages.slice().reverse().map((msg) => (
                                    <SessionMessageItem 
                                        key={msg.id}
                                        msg={msg}
                                        domRef={(el) => sessionMessageRefs.current[msg.id.toString()] = el}
                                        isExpanded={!!expandedSessionMessages[msg.id.toString()]}
                                        onToggleExpand={toggleSessionExpand}
                                        onDelete={handleDeleteSessionMessage}
                                    />
                                ))}
                                {filteredMessages.length === 0 && (
                                    <div className="flex flex-col items-center justify-center h-64 text-white/20">
                                        <Database size={48} className="mb-4 opacity-20" />
                                        <p className="font-mono text-sm uppercase tracking-widest">No memory traces found</p>
                                    </div>
                                )}
                            </div>
                        ) : (
                            filteredWeightedMemories.map((mem) => {
                                const isExpanded = expandedMemories[mem.id];
                                const shouldTruncate = mem.content.length > 150;
                                const displayContent = shouldTruncate && !isExpanded 
                                    ? mem.content.substring(0, 150) + "..." 
                                    : mem.content;

                                return (
                                <motion.div
                                    key={mem.id}
                                    ref={(el) => { weightedMemoryRefs.current[mem.id] = el; }}
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
                                                {displayContent}
                                                {shouldTruncate && (
                                                    <button 
                                                        onClick={() => toggleExpand(mem.id)}
                                                        className="ml-2 text-purple-400/70 hover:text-purple-300 text-[10px] font-mono inline-flex items-center gap-1 transition-colors uppercase tracking-wider bg-purple-500/5 px-1.5 py-0.5 rounded border border-purple-500/10"
                                                    >
                                                        {isExpanded ? (
                                                            <>Collapse <ChevronUp size={8} /></>
                                                        ) : (
                                                            <>Expand <ChevronDown size={8} /></>
                                                        )}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                                );
                            })
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
