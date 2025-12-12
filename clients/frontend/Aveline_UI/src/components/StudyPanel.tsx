import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, RefreshCw, CheckCircle, Clock, Grid, AlertTriangle, BarChart, Book, Search, ChevronRight, ArrowLeft, Play } from 'lucide-react';
import { api } from '../api/apiService';
import { InfoCard } from './InfoCard';

interface WordTranslation {
  type: string;
  translation: string;
}

interface WordPhrase {
  phrase: string;
  translation: string;
}

interface DailyWord {
  word: string;
  translations: WordTranslation[];
  phrases?: WordPhrase[];
  status: 'new' | 'review';
  due_time?: number;
}

interface ToolInput {
  name: string;
  label: string;
  type: string;
  min?: number;
  max?: number;
}

interface Tool {
  id: string;
  name: string;
  desc: string;
  type: string;
  inputs?: ToolInput[];
}

interface ToolCategory {
  id: string;
  name: string;
  desc: string;
  count: number;
}

type ViewType = 'daily' | 'tools' | 'dictionary' | 'curve' | 'mistakes';

const StudyPanel: React.FC = () => {
  const [activeView, setActiveView] = useState<ViewType>('daily');
  const [words, setWords] = useState<DailyWord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Tools State
  const [toolsMap, setToolsMap] = useState<Record<string, Tool[]>>({});
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<Tool | null>(null);
  const [toolInputs, setToolInputs] = useState<Record<string, any>>({});
  const [toolResult, setToolResult] = useState<any>(null);

  // Other Data State
  const [dictStats, setDictStats] = useState<any>(null);
  const [curveData, setCurveData] = useState<number[]>([]);
  const [mistakesData, setMistakesData] = useState<any[]>([]);

  const fetchWords = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.getDailyVocabulary(20);
      if (response && response.data) {
        setWords(response.data);
      } else {
        setWords([]);
        setError("Invalid response format");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch vocabulary");
    } finally {
      setLoading(false);
    }
  };

  const fetchTools = async () => {
    setLoading(true);
    try {
      const res = await api.getStudyTools();
      if (res && res.data) setToolsMap(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchDictStats = async () => {
    try {
      const res = await api.getDictStats();
      if (res && res.data) setDictStats(res.data);
    } catch (err) { console.error(err); }
  };

  const fetchCurve = async () => {
    try {
      const res = await api.getMemoryCurve();
      if (res && res.data) setCurveData(res.data);
    } catch (err) { console.error(err); }
  };

  const fetchMistakes = async () => {
    try {
      const res = await api.getMistakes();
      if (res && res.data) setMistakesData(res.data);
    } catch (err) { console.error(err); }
  };

  useEffect(() => {
    if (activeView === 'daily') fetchWords();
    else if (activeView === 'tools') fetchTools();
    else if (activeView === 'dictionary') fetchDictStats();
    else if (activeView === 'curve') fetchCurve();
    else if (activeView === 'mistakes') fetchMistakes();
  }, [activeView]);

  const runTool = async () => {
    if (!activeCategory || !activeTool) return;
    setLoading(true);
    try {
      const res = await api.runStudyTool(activeCategory, activeTool.id, toolInputs);
      setToolResult(res);
    } catch (err) {
      setToolResult({ status: 'error', message: err instanceof Error ? err.message : 'Failed to run tool' });
    } finally {
      setLoading(false);
    }
  };

  const container = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.05 } }
  };

  const item = {
    hidden: { opacity: 0, y: 20 },
    show: { opacity: 1, y: 0 }
  };

  const renderHeader = () => (
    <div className="flex items-center gap-2 overflow-x-auto pb-2 mb-2 no-scrollbar">
      {[
        { id: 'daily', label: 'Daily', icon: <BookOpen size={16} /> },
        { id: 'tools', label: 'Tools', icon: <Grid size={16} /> },
        { id: 'dictionary', label: 'Dict', icon: <Book size={16} /> },
        { id: 'curve', label: 'Memory', icon: <BarChart size={16} /> },
        { id: 'mistakes', label: 'Mistakes', icon: <AlertTriangle size={16} /> },
      ].map((tab) => (
        <button
          key={tab.id}
          onClick={() => {
            setActiveView(tab.id as ViewType);
            setActiveCategory(null);
            setActiveTool(null);
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
            activeView === tab.id
              ? 'bg-indigo-500 text-white'
              : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80'
          }`}
        >
          {tab.icon}
          <span>{tab.label}</span>
        </button>
      ))}
    </div>
  );

  const renderDailyWords = () => (
    <div className="flex-1 flex flex-col min-h-0">
       <div className="flex items-center justify-between mb-3 px-1">
          <div>
            <h3 className="text-sm font-medium text-white/90">Today's Words</h3>
            <p className="text-[10px] text-white/40">Keep up your streak!</p>
          </div>
          <button 
            onClick={fetchWords}
            disabled={loading}
            className="p-1.5 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/80 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
       </div>

       {loading ? (
        <div className="flex-1 flex items-center justify-center text-white/30">
          <div className="flex flex-col items-center gap-2">
            <RefreshCw className="animate-spin w-6 h-6" />
            <span className="text-xs">Loading words...</span>
          </div>
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center text-red-400/80">
          <p className="text-xs">{error}</p>
        </div>
      ) : words.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-white/30">
          <p className="text-sm">No words for today.</p>
        </div>
      ) : (
        <motion.div 
          variants={container}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-3 pb-4 overflow-y-auto custom-scrollbar pr-1"
        >
          {words.map((word, index) => (
            <motion.div key={`${word.word}-${index}`} variants={item}>
              <InfoCard className="group !p-3">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-bold text-white/90 font-mono tracking-wide">{word.word}</h3>
                    <div className={`px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider font-medium border ${
                      word.status === 'new' 
                        ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
                        : 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                    }`}>
                      {word.status === 'new' ? 'New' : 'Review'}
                    </div>
                  </div>
                  
                  <div className="space-y-0.5">
                    {word.translations.map((t, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs text-white/60">
                        <span className="text-[10px] text-white/30 uppercase w-6 pt-0.5 text-right font-mono flex-shrink-0">{t.type}.</span>
                        <span>{t.translation}</span>
                      </div>
                    ))}
                  </div>

                  {word.phrases && word.phrases.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-white/5">
                      <div className="space-y-1">
                        {word.phrases.slice(0, 1).map((p, i) => (
                          <div key={i} className="text-[11px]">
                            <span className="text-indigo-300/80 font-medium">{p.phrase}</span>
                            <span className="text-white/40 mx-1">-</span>
                            <span className="text-white/50">{p.translation}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </InfoCard>
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );

  const renderTools = () => {
    // 3. Tool Execution Interface
    if (activeTool && activeCategory) {
      return (
        <div className="flex-1 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
          <div className="flex items-center gap-2 mb-2">
             <button onClick={() => { setActiveTool(null); setToolResult(null); setToolInputs({}); }} className="p-1 hover:bg-white/10 rounded-full">
               <ArrowLeft size={16} className="text-white/60" />
             </button>
             <h3 className="text-sm font-medium text-white/90">{activeTool.name}</h3>
          </div>
          
          <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-4 space-y-4">
             <p className="text-xs text-white/50">{activeTool.desc}</p>
             
             {/* Dynamic Inputs */}
             {activeTool.inputs?.map((input) => (
               <div key={input.name} className="space-y-1">
                 <label className="text-xs text-white/70">{input.label}</label>
                 <input 
                   type={input.type === 'number' ? 'number' : 'text'}
                   className="w-full bg-zinc-800/50 border border-white/5 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500/50 outline-none"
                   value={toolInputs[input.name] || ''}
                   onChange={(e) => setToolInputs({...toolInputs, [input.name]: e.target.value})}
                 />
               </div>
             ))}
             
             <button 
               onClick={runTool}
               disabled={loading}
               className="w-full bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg py-2 flex items-center justify-center gap-2 text-sm font-medium transition-colors"
             >
               {loading ? <RefreshCw className="animate-spin" size={16} /> : <Play size={16} />}
               Run Tool
             </button>
          </div>

          {/* Results */}
          {toolResult && (
            <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-4">
               <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider">Result</h4>
               {toolResult.status === 'error' ? (
                 <p className="text-sm text-red-400">{toolResult.message}</p>
               ) : (
                 <pre className="text-xs text-white/70 whitespace-pre-wrap font-mono">
                   {JSON.stringify(toolResult.data, null, 2)}
                 </pre>
               )}
            </div>
          )}
        </div>
      );
    }

    // 2. Tools List in Category
    if (activeCategory) {
      const tools = toolsMap[activeCategory] || [];
      return (
        <div className="flex-1 flex flex-col gap-3 overflow-y-auto custom-scrollbar">
           <div className="flex items-center gap-2 mb-2">
             <button onClick={() => setActiveCategory(null)} className="p-1 hover:bg-white/10 rounded-full">
               <ArrowLeft size={16} className="text-white/60" />
             </button>
             <h3 className="text-sm font-medium text-white/90 capitalize">{activeCategory} Tools</h3>
           </div>
           
           {tools.length === 0 ? (
             <p className="text-white/40 text-sm text-center py-8">No tools available.</p>
           ) : (
             tools.map((t) => (
               <div 
                 key={t.id} 
                 onClick={() => setActiveTool(t)}
                 className="bg-zinc-900/50 border border-white/5 rounded-xl p-4 flex items-center justify-between hover:bg-zinc-800/50 transition-colors cursor-pointer group"
               >
                  <div>
                    <h4 className="text-sm font-medium text-zinc-200 group-hover:text-emerald-400 transition-colors">{t.name}</h4>
                    <p className="text-xs text-zinc-500">{t.desc}</p>
                  </div>
                  <ChevronRight size={16} className="text-zinc-600 group-hover:text-zinc-400" />
               </div>
             ))
           )}
        </div>
      );
    }

    // 1. Categories List
    return (
      <div className="flex-1 overflow-y-auto custom-scrollbar">
         <div className="grid grid-cols-1 gap-3">
            {Object.keys(toolsMap).map((cat) => (
              <div 
                key={cat} 
                onClick={() => setActiveCategory(cat)}
                className="bg-zinc-900/50 border border-white/5 rounded-xl p-4 flex items-center justify-between hover:bg-zinc-800/50 transition-colors cursor-pointer group"
              >
                  <div>
                    <h4 className="text-sm font-medium text-zinc-200 group-hover:text-emerald-400 transition-colors capitalize">{cat}</h4>
                    <p className="text-xs text-zinc-500">{toolsMap[cat].length} Tools</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <ChevronRight size={16} className="text-zinc-600 group-hover:text-zinc-400" />
                  </div>
              </div>
            ))}
         </div>
      </div>
    );
  };

  const renderDictionary = () => (
    <div className="flex-1 flex flex-col gap-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
        <input 
          type="text" 
          placeholder="Search dictionary..." 
          className="w-full bg-zinc-900/80 border border-white/5 rounded-xl py-2 pl-9 pr-4 text-sm text-zinc-200 outline-none focus:border-emerald-500/50"
        />
      </div>
      <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm flex-col gap-2">
        {dictStats ? (
          <>
            <p className="text-emerald-400 text-lg font-mono">{dictStats.total_words}</p>
            <p>Total Words</p>
            <div className="flex gap-4 mt-4">
               <div className="text-center">
                 <p className="text-white/80 font-bold">{dictStats.learned_words}</p>
                 <p className="text-xs text-white/40">Learned</p>
               </div>
               <div className="text-center">
                 <p className="text-amber-400 font-bold">{dictStats.to_review}</p>
                 <p className="text-xs text-white/40">Due</p>
               </div>
            </div>
          </>
        ) : (
          <RefreshCw className="animate-spin text-white/20" />
        )}
      </div>
    </div>
  );

  const renderCurve = () => (
    <div className="flex-1 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
       <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-4">
          <h4 className="text-sm font-medium text-zinc-200 mb-4">Memory Retention</h4>
          <div className="h-32 flex items-end justify-between gap-1 px-2">
             {curveData.length > 0 ? curveData.map((h, i) => (
               <div key={i} className="w-full bg-indigo-500/20 rounded-t relative group">
                  <div 
                    className="absolute bottom-0 left-0 right-0 bg-indigo-500 rounded-t transition-all duration-1000"
                    style={{ height: `${h}%` }}
                  />
               </div>
             )) : (
               <div className="w-full h-full flex items-center justify-center text-white/20 text-xs">No data yet</div>
             )}
          </div>
          <div className="flex justify-between mt-2 text-[10px] text-zinc-500">
             <span>1d</span>
             <span>2d</span>
             <span>3d</span>
             <span>4d</span>
             <span>5d</span>
             <span>6d</span>
             <span>7d</span>
          </div>
       </div>

       {dictStats && (
        <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-3">
              <div className="text-2xl font-mono text-emerald-400">{dictStats.learned_words}</div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Learned</div>
            </div>
            <div className="bg-zinc-900/50 border border-white/5 rounded-xl p-3">
              <div className="text-2xl font-mono text-amber-400">{dictStats.to_review}</div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider">To Review</div>
            </div>
        </div>
       )}
    </div>
  );

  const renderMistakes = () => (
    <div className="flex-1 overflow-y-auto custom-scrollbar">
       <h4 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">High Error Rate</h4>
       {mistakesData.length === 0 ? (
          <div className="text-center py-10 text-white/30 text-sm">No mistakes recorded yet.</div>
       ) : (
         <div className="space-y-2">
            {mistakesData.map((w, i) => (
               <div key={i} className="bg-zinc-900/50 border border-white/5 rounded-lg p-3 flex items-center justify-between">
                  <div>
                    <span className="text-sm text-zinc-300 font-medium">{w.word}</span>
                    <p className="text-[10px] text-white/40">{w.translations?.[0]?.translation}</p>
                  </div>
                  <div className="flex items-center gap-2">
                     <span className="text-xs text-red-400">{w.error_count}x</span>
                  </div>
               </div>
            ))}
         </div>
       )}
    </div>
  );

  return (
    <div className="h-full flex flex-col p-4 bg-zinc-950">
      {renderHeader()}
      
      <div className="flex-1 overflow-hidden relative flex flex-col">
        {activeView === 'daily' && renderDailyWords()}
        {activeView === 'tools' && renderTools()}
        {activeView === 'dictionary' && renderDictionary()}
        {activeView === 'curve' && renderCurve()}
        {activeView === 'mistakes' && renderMistakes()}
      </div>
    </div>
  );
};

export default StudyPanel;
