import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, RefreshCw, CheckCircle, Clock, Grid, AlertTriangle, BarChart, Book, Search, ChevronRight, ArrowLeft, Play, Zap, Award, Flame, XCircle, FolderOpen, NotebookPen, Eye } from 'lucide-react';
import { api } from '../api/apiService';
import { InfoCard } from './InfoCard';
import { StudyFileManager } from './StudyFileManager';
import { FocusMonitorPanel } from './study/FocusMonitorPanel';

interface WordTranslation {
  type: string;
  translation: string;
}

interface WordPhrase {
  phrase: string;
  translation: string;
}

interface WordSentence {
  sentence: string;
  translation: string;
}

interface DailyWord {
  word: string;
  translations: WordTranslation[];
  phrases?: WordPhrase[];
  sentences?: WordSentence[];
  us?: string;
  uk?: string;
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

interface SessionStats {
  active: boolean;
  duration: number;
  words_reviewed: number;
  correct_count: number;
  accuracy: number;
  streak: number;
}

type ViewType = 'daily' | 'records' | 'tools' | 'files' | 'dictionary' | 'curve' | 'mistakes' | 'focus';

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
  
  // Dictionary Search State
  const [dictSearch, setDictSearch] = useState('');
  const [dictResults, setDictResults] = useState<any[] | null>(null);

  // Dictionary List State
  const [showDictList, setShowDictList] = useState(false);
  const [dictList, setDictList] = useState<any[]>([]);
  const [dictPage, setDictPage] = useState(1);
  const [dictHasMore, setDictHasMore] = useState(true);
  const [dictLoading, setDictLoading] = useState(false);
  const [showResources, setShowResources] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const dictScrollRef = useRef<HTMLDivElement | null>(null);

  // App Mode State
  const [isReviewMode, setIsReviewMode] = useState(false);
  const [currentCardIndex, setCurrentCardIndex] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [sessionStats, setSessionStats] = useState<SessionStats | null>(null);
  const [sessionSummary, setSessionSummary] = useState<any>(null); // To show after session
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const [studyOverview, setStudyOverview] = useState<any>(null);
  const [studySessions, setStudySessions] = useState<any[]>([]);
  const [studyPanelBundle, setStudyPanelBundle] = useState<any>(null);
  const [recordTopic, setRecordTopic] = useState('英语');
  const [recordContent, setRecordContent] = useState('');
  const [recordDuration, setRecordDuration] = useState<number>(45);

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
      
      // Also fetch session stats
      const stats = await api.getSessionStats();
      if (stats && stats.data) setSessionStats(stats.data);
      
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

  const fetchStudyRecords = async () => {
    setLoading(true);
    setError(null);
    try {
      const panelRes = await api.workspaceStudyPanel({
        conversationId: 'default_user',
        historyLimit: 20,
        silent: true,
      });
      const panel = (panelRes && panelRes.data) ? panelRes.data : null;
      setStudyPanelBundle(panel);
      setStudyOverview((panel && panel.study_panel) ? panel.study_panel : null);
      const sessions =
        (((panel && panel.workspace_snapshot && panel.workspace_snapshot.portrait && panel.workspace_snapshot.portrait.study && panel.workspace_snapshot.portrait.study.sessions) || [])) as any[];
      setStudySessions(sessions);
      await fetchDictStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载学习记录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRecordStudy = async () => {
    const topic = recordTopic.trim();
    const content = recordContent.trim();
    if (!topic || !content) {
      setError('请先填写学习主题和记录内容');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.workspaceStudyRecord({ topic, content });
      setSuccessMsg('学习记录已保存');
      setRecordContent('');
      await fetchStudyRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : '写入学习记录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStartStudy = async () => {
    const topic = recordTopic.trim();
    if (!topic) {
      setError('请先填写学习主题');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.dailyDataRecordStudy({
        subject: topic,
        duration_minutes: Math.max(5, Number(recordDuration || 45)),
        note: recordContent.trim() || undefined,
        enter_low_disturbance: true,
        switch_mode_to_study: true,
      });
      setSuccessMsg('学习会话已开始');
      await fetchStudyRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : '开始学习会话失败');
    } finally {
      setLoading(false);
    }
  };

  const handleFinishStudy = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.dailyDataFinishStudy();
      setSuccessMsg('学习会话已结束并记录');
      await fetchStudyRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : '结束学习会话失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeView === 'daily') fetchWords();
    else if (activeView === 'tools') fetchTools();
    else if (activeView === 'dictionary') fetchDictStats();
    else if (activeView === 'curve') fetchCurve();
    else if (activeView === 'mistakes') fetchMistakes();
    else if (activeView === 'records') fetchStudyRecords();
  }, [activeView]);

  // Session Timer
  useEffect(() => {
    if (isReviewMode && !timerRef.current) {
      timerRef.current = setInterval(async () => {
        // Optimistic local update or just let backend handle it on submit
        // We can poll stats every minute if we want, but local tracking is smoother
      }, 60000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [isReviewMode]);

  const startReview = async () => {
    try {
      await api.startSession();
      setIsReviewMode(true);
      setCurrentCardIndex(0);
      setShowAnswer(false);
      setSessionSummary(null);
      // Ensure we have words
      if (words.length === 0) fetchWords();
    } catch (e) {
      console.error("Failed to start session", e);
    }
  };

  const submitReview = async (quality: number) => {
    if (!words[currentCardIndex]) return;
    
    const word = words[currentCardIndex].word;
    
    // Optimistic UI update
    const nextIndex = currentCardIndex + 1;
    
    try {
      const res = await api.submitReview(word, quality);
      if (res && res.data && res.data.session_stats) {
        setSessionStats(res.data.session_stats);
      }
    } catch (e) {
      console.error("Review submit failed", e);
    }

    if (nextIndex >= words.length) {
      // Session Complete
      finishSession();
    } else {
      setCurrentCardIndex(nextIndex);
      setShowAnswer(false);
    }
  };

  const finishSession = async () => {
    try {
      const res = await api.endSession();
      setSessionSummary(res.data);
      setIsReviewMode(false);
      fetchWords(); // Refresh for next batch
    } catch (e) {
      console.error("End session failed", e);
      setIsReviewMode(false);
    }
  };

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
        { id: 'daily', label: 'Learn', icon: <Zap size={16} /> },
        { id: 'records', label: 'Records', icon: <NotebookPen size={16} /> },
        { id: 'tools', label: 'Tools', icon: <Grid size={16} /> },
        { id: 'files', label: 'Project', icon: <FolderOpen size={16} /> },
        { id: 'dictionary', label: 'Dict', icon: <Book size={16} /> },
        { id: 'curve', label: 'Stats', icon: <BarChart size={16} /> },
        { id: 'mistakes', label: 'Mistakes', icon: <AlertTriangle size={16} /> },
        { id: 'focus', label: 'Focus', icon: <Eye size={16} /> },
      ].map((tab) => (
        <button
          key={tab.id}
          onClick={() => {
            if (isReviewMode) {
                if (confirm("Quit review session?")) {
                    setIsReviewMode(false);
                    setActiveView(tab.id as ViewType);
                }
            } else {
                setActiveView(tab.id as ViewType);
            }
            setActiveCategory(null);
            setActiveTool(null);
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all duration-300 border ${
            activeView === tab.id
              ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30 shadow-[0_0_10px_rgba(16,185,129,0.2)]'
              : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80 border-transparent hover:border-white/10'
          }`}
        >
          {tab.icon}
          <span>{tab.label}</span>
        </button>
      ))}
    </div>
  );

  // --- REVIEW APP COMPONENT ---
  const renderReviewSession = () => {
    const word = words[currentCardIndex];
    if (!word) return null;

    return (
        <div className="flex-1 flex flex-col h-full relative">
            {/* Progress Bar */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-white/10 rounded-full overflow-hidden">
                <div 
                    className="h-full bg-emerald-500 transition-all duration-300"
                    style={{ width: `${((currentCardIndex) / words.length) * 100}%` }}
                />
            </div>

            <div className="flex items-center justify-between mt-3 mb-4 px-1">
                <span className="text-xs text-white/40 font-mono">
                    {currentCardIndex + 1} / {words.length}
                </span>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-emerald-400 font-medium flex items-center gap-1">
                        <Flame size={12} /> {sessionStats?.streak || 0}
                    </span>
                    <button onClick={() => setIsReviewMode(false)} className="text-white/40 hover:text-white transition-colors">
                        <XCircle size={16} />
                    </button>
                </div>
            </div>

            {/* Flashcard Area */}
            <div className="flex-1 flex flex-col relative perspective-1000">
                <AnimatePresence mode='wait'>
                    {!showAnswer ? (
                        <motion.div 
                            key="front"
                            initial={{ rotateY: -90, opacity: 0 }}
                            animate={{ rotateY: 0, opacity: 1 }}
                            exit={{ rotateY: 90, opacity: 0 }}
                            transition={{ duration: 0.3 }}
                            className="flex-1 glass-card rounded-2xl p-6 flex flex-col items-center justify-center text-center cursor-pointer hover:bg-white/5 transition-colors shadow-lg border border-white/10"
                            onClick={() => setShowAnswer(true)}
                        >
                            <span className="text-xs text-emerald-400 uppercase tracking-widest mb-4 font-medium bg-emerald-500/10 px-2 py-1 rounded">
                                {word.status === 'new' ? 'New Word' : 'Review'}
                            </span>
                            <h2 className="text-4xl font-bold text-white mb-4 font-serif tracking-wide text-glow">{word.word}</h2>
                            <p className="text-white/30 text-sm">Tap to flip</p>
                        </motion.div>
                    ) : (
                        <motion.div 
                            key="back"
                            initial={{ rotateY: 90, opacity: 0 }}
                            animate={{ rotateY: 0, opacity: 1 }}
                            exit={{ rotateY: -90, opacity: 0 }}
                            transition={{ duration: 0.3 }}
                            className="flex-1 glass-card rounded-2xl p-6 flex flex-col items-start justify-center shadow-lg border border-white/10 relative overflow-hidden"
                        >
                            <div className="absolute top-0 left-0 w-1 h-full bg-emerald-500/50" />
                            <h3 className="text-2xl font-bold text-white/90 mb-4 font-serif">{word.word}</h3>
                            
                            <div className="space-y-3 w-full">
                                {word.translations.map((t, i) => (
                                    <div key={i} className="flex items-start gap-3 p-2 rounded-lg bg-white/5 w-full">
                                        <span className="text-xs text-emerald-400 font-mono pt-0.5 uppercase w-8 text-right flex-shrink-0">{t.type}</span>
                                        <span className="text-base text-zinc-100">{t.translation}</span>
                                    </div>
                                ))}
                            </div>

                            {word.phrases && word.phrases.length > 0 && (
                                <div className="mt-6 pt-4 border-t border-white/10 w-full">
                                    <h4 className="text-xs text-white/40 uppercase tracking-wider mb-2">Example Phrase</h4>
                                    <p className="text-sm text-indigo-300 italic mb-1">"{word.phrases[0].phrase}"</p>
                                    <p className="text-xs text-white/50">{word.phrases[0].translation}</p>
                                </div>
                            )}

                            {word.sentences && word.sentences.length > 0 && (
                                <div className="mt-6 pt-4 border-t border-white/10 w-full">
                                    <h4 className="text-xs text-white/40 uppercase tracking-wider mb-2">Example Sentence</h4>
                                    <div className="space-y-3">
                                      {word.sentences.slice(0, 2).map((s, idx) => (
                                        <div key={idx} className="space-y-1">
                                          <p className="text-sm text-emerald-300 italic">"{s.sentence}"</p>
                                          <p className="text-xs text-white/50">{s.translation}</p>
                                        </div>
                                      ))}
                                    </div>
                                </div>
                            )}
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* Controls */}
            <div className="mt-6 h-20">
                {showAnswer ? (
                    <div className="grid grid-cols-4 gap-2 h-full">
                        <button onClick={() => submitReview(1)} className="flex flex-col items-center justify-center gap-1 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-xl border border-red-500/30 transition-all">
                            <span className="text-sm font-bold">Again</span>
                            <span className="text-[10px] opacity-60">1m</span>
                        </button>
                        <button onClick={() => submitReview(2)} className="flex flex-col items-center justify-center gap-1 bg-orange-500/20 hover:bg-orange-500/30 text-orange-300 rounded-xl border border-orange-500/30 transition-all">
                            <span className="text-sm font-bold">Hard</span>
                            <span className="text-[10px] opacity-60">10m</span>
                        </button>
                        <button onClick={() => submitReview(3)} className="flex flex-col items-center justify-center gap-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 rounded-xl border border-blue-500/30 transition-all">
                            <span className="text-sm font-bold">Good</span>
                            <span className="text-[10px] opacity-60">1d</span>
                        </button>
                        <button onClick={() => submitReview(4)} className="flex flex-col items-center justify-center gap-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 rounded-xl border border-emerald-500/30 transition-all">
                            <span className="text-sm font-bold">Easy</span>
                            <span className="text-[10px] opacity-60">3d</span>
                        </button>
                    </div>
                ) : (
                    <button 
                        onClick={() => setShowAnswer(true)}
                        className="w-full h-full bg-white/10 hover:bg-white/15 text-white rounded-xl border border-white/10 font-medium tracking-wide transition-all active:scale-[0.99]"
                    >
                        Show Answer
                    </button>
                )}
            </div>
        </div>
    );
  };

  const renderSessionSummary = () => (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <motion.div 
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-emerald-500/20 p-6 rounded-full mb-6 border border-emerald-500/30 shadow-[0_0_30px_rgba(16,185,129,0.2)]"
          >
              <CheckCircle size={48} className="text-emerald-400" />
          </motion.div>
          <h2 className="text-2xl font-bold text-white mb-2">Session Complete!</h2>
          <p className="text-white/60 mb-8">You reviewed {sessionSummary?.words_reviewed || 0} words.</p>
          
          <div className="grid grid-cols-2 gap-4 w-full mb-8">
              <div className="glass-card p-4 rounded-xl">
                  <div className="text-xs text-white/40 uppercase">Accuracy</div>
                  <div className="text-xl font-bold text-white">{typeof sessionStats?.accuracy === 'number' ? sessionStats.accuracy.toFixed(0) : '0'}%</div>
              </div>
              <div className="glass-card p-4 rounded-xl">
                  <div className="text-xs text-white/40 uppercase">Streak</div>
                  <div className="text-xl font-bold text-amber-400">{sessionStats?.streak ?? 0}</div>
              </div>
          </div>

          <button 
            onClick={() => { setSessionSummary(null); fetchWords(); }}
            className="px-8 py-3 bg-white/10 hover:bg-white/20 text-white rounded-xl border border-white/10 transition-all w-full"
          >
              Continue Learning
          </button>
      </div>
  );

  const renderDashboard = () => (
    <div className="flex-1 flex flex-col gap-4 overflow-y-auto custom-scrollbar p-1">
        {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 flex items-center gap-3 text-red-400 text-xs">
                <AlertTriangle size={14} />
                <span className="flex-1">{error}</span>
                <button onClick={() => setError(null)} className="opacity-60 hover:opacity-100">
                    <XCircle size={14} />
                </button>
            </div>
        )}
        {successMsg && (
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 flex items-center gap-3 text-emerald-400 text-xs animate-in fade-in slide-in-from-top-2">
                <CheckCircle size={14} />
                <span className="flex-1">{successMsg}</span>
                <button onClick={() => setSuccessMsg(null)} className="opacity-60 hover:opacity-100">
                    <XCircle size={14} />
                </button>
            </div>
        )}
        {/* Hero Section */}
        <div className="glass-card rounded-2xl p-6 relative overflow-hidden group">
            <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/20 blur-[50px] rounded-full -mr-10 -mt-10" />
            
            <div className="relative z-10">
                <h2 className="text-xl font-bold text-white mb-1">Ready to learn?</h2>
                <p className="text-sm text-white/60 mb-6">
                    {words.length > 0 
                        ? `You have ${words.length} words scheduled for today.`
                        : 'No words scheduled for today. Great job!'}
                </p>
                
                {words.length > 0 ? (
                    <>
                        <div className="flex items-center gap-4 mb-6">
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-white/5 rounded-lg">
                                    <Clock size={16} className="text-blue-400" />
                                </div>
                                <div>
                                    <div className="text-xs text-white/40">Pending</div>
                                    <div className="text-sm font-bold text-white">{words.filter(w => w.status === 'review').length}</div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-white/5 rounded-lg">
                                    <Award size={16} className="text-amber-400" />
                                </div>
                                <div>
                                    <div className="text-xs text-white/40">New</div>
                                    <div className="text-sm font-bold text-white">{words.filter(w => w.status === 'new').length}</div>
                                </div>
                            </div>
                        </div>

                        <button 
                            onClick={startReview}
                            className="w-full py-3 bg-emerald-500 hover:bg-emerald-400 text-white rounded-xl font-medium shadow-[0_4px_20px_rgba(16,185,129,0.3)] hover:shadow-[0_4px_25px_rgba(16,185,129,0.4)] transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <Play size={18} fill="currentColor" />
                            Start Session
                        </button>
                    </>
                ) : (
                    <div className="flex flex-col gap-3">
                        <button 
                            onClick={() => setActiveView('dictionary')}
                            className="w-full py-3 bg-white/5 hover:bg-white/10 text-white/80 rounded-xl font-medium border border-white/10 transition-all flex items-center justify-center gap-2"
                        >
                            <BookOpen size={18} />
                            Browse Dictionary
                        </button>
                        <p className="text-[10px] text-center text-white/30 italic">
                            Try searching for new words to add them to your learning list
                        </p>
                    </div>
                )}
            </div>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-2 gap-3">
             <div className="glass-card rounded-xl p-4">
                 <div className="flex items-center gap-2 mb-2">
                     <Flame size={14} className="text-amber-500" />
                     <span className="text-xs text-white/60">Streak</span>
                 </div>
                 <div className="text-2xl font-bold text-white">{sessionStats?.streak || 0}</div>
             </div>
             <div className="glass-card rounded-xl p-4">
                 <div className="flex items-center gap-2 mb-2">
                     <CheckCircle size={14} className="text-emerald-500" />
                     <span className="text-xs text-white/60">Learned</span>
                 </div>
                 <div className="text-2xl font-bold text-white">{dictStats?.learned_words || 0}</div>
             </div>
        </div>

        {/* Word Preview List */}
        <div className="mt-2">
            <h3 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-3">Up Next</h3>
            <div className="space-y-2">
                {words.slice(0, 5).map((w, i) => (
                    <div key={i} className="glass-panel border border-white/5 rounded-lg p-3 flex items-center justify-between">
                        <span className="text-sm text-zinc-200">{w.word}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                            w.status === 'new' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'
                        }`}>
                            {w.status.toUpperCase()}
                        </span>
                    </div>
                ))}
                {words.length > 5 && (
                    <div className="text-center text-xs text-white/30 pt-2">
                        + {words.length - 5} more words
                    </div>
                )}
            </div>
        </div>
    </div>
  );

  const renderDailyView = () => {
    if (isReviewMode) return renderReviewSession();
    if (sessionSummary) return renderSessionSummary();
    
    if (loading && !words.length) return (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-white/30">
          <RefreshCw className="animate-spin w-6 h-6" />
          <div className="flex flex-col items-center gap-2">
            <p className="text-xs">Loading your daily words...</p>
            <button 
                onClick={() => fetchWords()}
                className="text-[10px] px-3 py-1 bg-white/5 hover:bg-white/10 border border-white/10 rounded-full transition-colors"
            >
                Retry
            </button>
          </div>
        </div>
    );
    
    return renderDashboard();
  };

  // --- TOOLS RENDERER ---
  const renderToolResult = () => {
    if (!toolResult || toolResult.status === 'error') {
      return (
        <div className="glass-card rounded-xl p-4">
          <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Result</h4>
          {toolResult?.status === 'error' ? (
            <p className="text-sm text-red-400">{toolResult.message}</p>
          ) : (
            <p className="text-xs text-white/30 italic text-center py-4">Run the tool to see results</p>
          )}
        </div>
      );
    }

    const data = toolResult.data;

    // Specialized Rendering for Common Tools
    
    // 1. Math Problem Generation
    if (activeTool?.id === 'problem_gen' && activeCategory === 'math' && Array.isArray(data)) {
      return (
        <div className="space-y-4">
          <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Practice Problems</h4>
          {data.map((p, i) => (
            <div key={i} className="glass-card rounded-xl p-4 border-l-2 border-l-blue-500/50">
              <div className="flex justify-between items-start mb-2">
                <span className="text-[10px] bg-blue-500/10 text-blue-300 px-1.5 py-0.5 rounded">Problem {i + 1}</span>
                <span className="text-[10px] text-white/30">{p.module}</span>
              </div>
              <p className="text-sm text-white/90 mb-4 font-serif leading-relaxed">{p.question}</p>
              <details className="cursor-pointer group">
                <summary className="text-xs text-emerald-400/60 hover:text-emerald-400 transition-colors list-none flex items-center gap-1">
                  <ChevronRight size={12} className="group-open:rotate-90 transition-transform" />
                  View Answer & Steps
                </summary>
                <div className="mt-3 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10 animate-in fade-in slide-in-from-top-2">
                  <p className="text-sm text-emerald-300 mb-2 font-medium">Answer: {p.answer}</p>
                  {p.steps && (
                    <div className="space-y-1.5">
                      <p className="text-[10px] text-emerald-500/50 uppercase font-bold">Solution Steps:</p>
                      {p.steps.map((step: string, idx: number) => (
                        <p key={idx} className="text-xs text-white/60 leading-relaxed">{idx + 1}. {step}</p>
                      ))}
                    </div>
                  )}
                </div>
              </details>
            </div>
          ))}
        </div>
      );
    }

    // 2. Poetry Quiz
    if (activeTool?.id === 'poetry_quiz' && activeCategory === 'chinese' && Array.isArray(data)) {
      return (
        <div className="space-y-4">
          <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Poetry Quiz</h4>
          {data.map((q, i) => (
            <div key={i} className="glass-card rounded-xl p-4 border-l-2 border-l-amber-500/50">
              <div className="flex justify-between items-start mb-2">
                <span className="text-[10px] bg-amber-500/10 text-amber-300 px-1.5 py-0.5 rounded">Quiz {i + 1}</span>
                <span className="text-[10px] text-white/30">{q.author} - 《{q.title}》</span>
              </div>
              <p className="text-sm text-white/90 mb-4 font-serif text-center leading-loose tracking-widest">
                {q.context_before && <span className="block opacity-40 text-xs mb-1">{q.context_before}</span>}
                <span className="underline underline-offset-8 decoration-amber-500/30 decoration-dashed">
                  {q.question_line}
                </span>
                {q.context_after && <span className="block opacity-40 text-xs mt-1">{q.context_after}</span>}
              </p>
              <details className="cursor-pointer group">
                <summary className="text-xs text-emerald-400/60 hover:text-emerald-400 transition-colors list-none flex items-center gap-1">
                  <ChevronRight size={12} className="group-open:rotate-90 transition-transform" />
                  Show Answer
                </summary>
                <div className="mt-3 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10 text-center animate-in fade-in slide-in-from-top-2">
                  <p className="text-lg font-serif text-emerald-300">{q.answer}</p>
                </div>
              </details>
            </div>
          ))}
        </div>
      );
    }

    // 3. Genetics Calculator
    if (activeTool?.id === 'biology_genetics_calculator' && data.genotypes) {
      return (
        <div className="space-y-4">
          <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Genetics Results</h4>
          <div className="glass-card rounded-xl p-4 border-l-2 border-l-pink-500/50">
             <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="p-2 bg-white/5 rounded-lg text-center">
                    <p className="text-[10px] text-white/40 uppercase">Parent 1</p>
                    <p className="text-lg font-mono text-pink-400">{data.parents?.[0] || 'Unknown'}</p>
                </div>
                <div className="p-2 bg-white/5 rounded-lg text-center">
                    <p className="text-[10px] text-white/40 uppercase">Parent 2</p>
                    <p className="text-lg font-mono text-pink-400">{data.parents?.[1] || 'Unknown'}</p>
                </div>
             </div>
             
             <div className="space-y-3">
                <p className="text-xs font-medium text-white/60">Offspring Genotypes:</p>
                <div className="grid grid-cols-1 gap-2">
                    {Object.entries(data.genotypes).map(([g, p]: [string, any]) => (
                        <div key={g} className="flex items-center justify-between text-xs p-2 bg-white/5 rounded border border-white/5">
                            <span className="font-mono text-white/90">{g}</span>
                            <span className="text-emerald-400 font-bold">{(p * 100).toFixed(1)}%</span>
                        </div>
                    ))}
                </div>
             </div>
          </div>
        </div>
      );
    }

    // 4. Climate Judger
    if (activeTool?.id === 'geography_climate_judge' && data.climate_type) {
      return (
        <div className="space-y-4">
          <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Climate Analysis</h4>
          <div className="glass-card rounded-xl p-4 border-l-2 border-l-sky-500/50">
             <div className="text-center py-4 mb-4 bg-sky-500/10 rounded-xl border border-sky-500/20">
                <p className="text-xs text-sky-300/60 uppercase tracking-widest mb-1">Resulting Type</p>
                <p className="text-xl font-bold text-white text-glow">{data.climate_type}</p>
             </div>
             
             <div className="space-y-2">
                <p className="text-[10px] text-white/40 uppercase font-bold px-1">Reasoning Logic</p>
                {data.reasoning?.map((step: string, i: number) => (
                    <div key={i} className="flex gap-2 text-xs text-white/70 leading-relaxed p-2 bg-white/5 rounded">
                        <span className="text-sky-400 font-mono">{i+1}.</span>
                        <span>{step}</span>
                    </div>
                ))}
             </div>
          </div>
        </div>
      );
    }

    // 5. Multimedia Tags (Image/Audio)
    if (typeof data === 'string') {
        if (data.includes('[GEN_IMG:')) {
            const imgPath = data.match(/\[GEN_IMG:\s*(.*?)\]/)?.[1];
            // Convert file path to accessible URL if needed, or assume a static serving path
            const displayPath = imgPath?.split(/[\\/]/).pop();
            return (
                <div className="space-y-4">
                    <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Generated Visualization</h4>
                    <div className="glass-card rounded-xl p-2 overflow-hidden border border-white/10">
                        <img 
                            src={`/api/static/images/generated/${displayPath}`} 
                            alt="Generated Math Plot" 
                            className="w-full h-auto rounded-lg shadow-2xl"
                            onError={(e) => {
                                (e.target as HTMLImageElement).src = 'https://via.placeholder.com/400x300?text=Image+Load+Error';
                            }}
                        />
                        <p className="text-[10px] text-white/30 mt-2 px-2 italic truncate">{imgPath}</p>
                    </div>
                </div>
            );
        }
        if (data.includes('[GEN_AUDIO:')) {
            const audioPath = data.match(/\[GEN_AUDIO:\s*(.*?)\]/)?.[1];
            const displayPath = audioPath?.split(/[\\/]/).pop();
            return (
                <div className="space-y-4">
                    <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Generated Audio</h4>
                    <div className="glass-card rounded-xl p-4 border border-white/10 flex flex-col items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 animate-pulse">
                            <Play size={24} />
                        </div>
                        <audio controls className="w-full h-8 filter invert hue-rotate-180 opacity-70">
                            <source src={`/api/static/audio/${displayPath}`} type="audio/wav" />
                            Your browser does not support the audio element.
                        </audio>
                        <p className="text-[10px] text-white/30 italic truncate w-full text-center">{audioPath}</p>
                    </div>
                </div>
            );
        }
    }

    // Default JSON View (Cleaned up)
    return (
      <div className="glass-card rounded-xl p-4">
        <h4 className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wider text-glow">Result Data</h4>
        <pre className="text-xs text-white/70 whitespace-pre-wrap font-mono bg-black/20 p-3 rounded-lg border border-white/5">
          {JSON.stringify(data, null, 2)}
        </pre>
      </div>
    );
  };

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
          
          <div className="glass-card rounded-xl p-4 space-y-4">
             <p className="text-xs text-white/50">{activeTool.desc}</p>
             
             {/* Dynamic Inputs */}
            {activeTool.inputs?.map((input) => (
              <div key={input.name} className="space-y-1">
                <label className="text-xs text-white/70">{input.label}</label>
                {input.name === 'content' ? (
                  <textarea 
                    className="w-full glass-panel border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500/50 outline-none transition-all duration-300 shadow-inner min-h-[120px] font-mono"
                    placeholder={`Enter ${input.label}...`}
                    value={toolInputs[input.name] || ''}
                    onChange={(e) => setToolInputs({...toolInputs, [input.name]: e.target.value})}
                  />
                ) : (
                  <input 
                    type={input.type === 'number' ? 'number' : 'text'}
                    className="w-full glass-panel border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500/50 outline-none transition-all duration-300 shadow-inner"
                    placeholder={`Enter ${input.label}...`}
                    value={toolInputs[input.name] || ''}
                    onChange={(e) => setToolInputs({...toolInputs, [input.name]: e.target.value})}
                  />
                )}
              </div>
            ))}
             
             <button 
               onClick={runTool}
               disabled={loading}
               className="w-full bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 rounded-lg py-2 flex items-center justify-center gap-2 text-sm font-medium transition-all duration-300 shadow-[0_0_15px_rgba(16,185,129,0.1)] hover:shadow-[0_0_20px_rgba(16,185,129,0.2)]"
             >
               {loading ? <RefreshCw className="animate-spin" size={16} /> : <Play size={16} />}
               Run Tool
             </button>
          </div>

          {/* Results Area */}
          {renderToolResult()}
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
                 className="glass-card rounded-xl p-4 flex items-center justify-between hover:bg-white/10 transition-all duration-300 cursor-pointer group hover:shadow-[0_0_15px_rgba(255,255,255,0.05)]"
               >
                  <div>
                    <h4 className="text-sm font-medium text-zinc-200 group-hover:text-emerald-400 transition-colors text-glow">{t.name}</h4>
                    <p className="text-xs text-zinc-500 group-hover:text-zinc-400 transition-colors">{t.desc}</p>
                  </div>
                  <ChevronRight size={16} className="text-zinc-600 group-hover:text-emerald-400 transition-colors" />
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
                className="glass-card rounded-xl p-4 flex items-center justify-between hover:bg-white/10 transition-all duration-300 cursor-pointer group hover:shadow-[0_0_15px_rgba(255,255,255,0.05)]"
              >
                  <div>
                    <h4 className="text-sm font-medium text-zinc-200 group-hover:text-emerald-400 transition-colors capitalize text-glow">{cat}</h4>
                    <p className="text-xs text-zinc-500 group-hover:text-zinc-400 transition-colors">{toolsMap[cat].length} Tools</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <ChevronRight size={16} className="text-zinc-600 group-hover:text-emerald-400 transition-colors" />
                  </div>
              </div>
            ))}
         </div>
      </div>
    );
  };

  const handleSelectWord = (word: string) => {
    setDictSearch(word);
    setShowDictList(false);
    // Trigger search
    setTimeout(() => {
        handleDictSearchWithQuery(word);
    }, 0);
  };

  const handleDictSearchWithQuery = async (query: string) => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await api.searchDictionary(query);
      if (res?.data) {
        if (res.data.matches) {
            setDictResults(res.data.matches);
        } else {
            setDictResults(Array.isArray(res.data) ? res.data : [res.data]);
        }
      }
    } catch (err) {
      console.error(err);
      setError("Search failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDictSearch = async () => {
    handleDictSearchWithQuery(dictSearch);
  };

  const fetchDictList = async (page: number, reset: boolean = false) => {
    if (dictLoading) return;
    setDictLoading(true);
    try {
      const res = await api.getDictList(page, 50);
      if (res && res.data) {
        if (reset) {
          setDictList(res.data.words);
        } else {
          setDictList(prev => [...prev, ...res.data.words]);
        }
        setDictHasMore(res.data.has_more);
        setDictPage(page);
      }
    } catch (err) {
      console.error("Failed to load dictionary list", err);
    } finally {
      setDictLoading(false);
    }
  };

  const handleDictListOpen = () => {
    setShowDictList(true);
    if (dictList.length === 0) {
      fetchDictList(1, true);
    }
  };

  const handleSwitchDict = async (filename: string, isSentence: boolean = false) => {
    setLoading(true);
    try {
      const res = await api.switchVocabulary(filename, isSentence);
      if (res && res.status === 'success') {
        // Refresh stats and words
        setSuccessMsg(isSentence ? `Switched sentence set to ${filename}` : `Switched dictionary to ${filename}`);
        fetchDictStats();
        fetchWords();
        setShowDictList(false);
        setDictResults(null);
        setDictList([]);
        setTimeout(() => setSuccessMsg(null), 3000);
      }
    } catch (err) {
      console.error("Failed to switch dictionary", err);
      setError("Switch failed");
    } finally {
      setLoading(false);
    }
  };

  const handleAddToLearning = async (word: string) => {
    try {
        const res = await api.addToLearning(word);
        if (res && res.status === 'success') {
            setSuccessMsg(`Added '${word}' to your learning list`);
            fetchDictStats(); // Update learned count
            setTimeout(() => setSuccessMsg(null), 3000);
        } else {
            setError(res?.message || "Failed to add word");
        }
    } catch (err) {
        setError("Add to learning failed");
    }
  };

  const renderDictionary = () => (
    <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden">
      <div className="flex gap-2 flex-shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" size={16} />
          <input 
            type="text" 
            placeholder="Search dictionary..." 
            className="w-full glass-panel border border-white/10 rounded-xl py-2 pl-9 pr-12 text-sm text-white placeholder:text-white/30 outline-none focus:border-emerald-500/50 focus:bg-white/10 transition-all duration-300 shadow-inner"
            value={dictSearch}
            onChange={(e) => setDictSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleDictSearch()}
          />
          <button 
            onClick={handleDictSearch}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-white/40 hover:text-emerald-400 transition-colors"
          >
            <Search size={14} />
          </button>
        </div>
        <div className="flex gap-1">
            <button 
                onClick={() => { setShowDictList(!showDictList); setShowResources(false); if(!showDictList && dictList.length === 0) fetchDictList(1, true); }}
                className={`px-3 py-2 glass-panel border rounded-xl transition-all duration-300 shadow-sm ${showDictList ? 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10' : 'text-white/40 border-white/10 hover:text-emerald-300 hover:bg-emerald-500/10'}`}
                title="Browse All"
            >
                <BookOpen size={16} />
            </button>
            <button 
                onClick={() => { setShowResources(!showResources); setShowDictList(false); }}
                className={`px-3 py-2 glass-panel border rounded-xl transition-all duration-300 shadow-sm ${showResources ? 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10' : 'text-white/40 border-white/10 hover:text-emerald-300 hover:bg-emerald-500/10'}`}
                title="Manage Resources"
            >
                <Grid size={16} />
            </button>
        </div>
      </div>

      <div
        ref={dictScrollRef}
        className="flex-1 min-h-0 overflow-y-auto custom-scrollbar pr-2"
        onScroll={(e) => {
          if (!showDictList) return;
          const target = e.currentTarget;
          if (target.scrollHeight - target.scrollTop <= target.clientHeight + 50) {
            if (!dictLoading && dictHasMore) {
              fetchDictList(dictPage + 1);
            }
          }
        }}
      >
      {showResources ? (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between mb-2">
                <button 
                    onClick={() => setShowResources(false)}
                    className="flex items-center gap-1 text-xs text-white/40 hover:text-emerald-300 transition-colors"
                >
                    <ArrowLeft size={12} /> Back
                </button>
                <span className="text-xs text-white/30">
                    Current: {dictStats?.current_dictionary || 'Default'} / {dictStats?.current_sentence_collection || 'None'}
                </span>
            </div>
            
            <div className="space-y-6">
                {/* Word Files */}
                <div className="space-y-2">
                    <h4 className="text-xs font-medium text-white/40 uppercase tracking-wider px-1">Word Dictionaries</h4>
                    <div className="grid grid-cols-1 gap-2">
                        {dictStats?.available_word_files && dictStats.available_word_files.length > 0 ? (
                            dictStats.available_word_files.map((file: string) => (
                                <button
                                    key={file}
                                    onClick={() => handleSwitchDict(file, false)}
                                    className={`glass-card rounded-xl p-3 text-left hover:bg-white/10 transition-all duration-300 group ${dictStats?.current_dictionary === file ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-white/5'}`}
                                >
                                    <div className="flex items-center justify-between">
                                        <span className={`text-sm ${dictStats?.current_dictionary === file ? 'text-emerald-400 font-medium' : 'text-white/70'}`}>{file}</span>
                                        {dictStats?.current_dictionary === file && <CheckCircle size={14} className="text-emerald-500" />}
                                    </div>
                                </button>
                            ))
                        ) : (
                            <div className="p-4 border border-dashed border-white/10 rounded-xl text-center text-white/20 text-xs">
                                No dictionary files found in data/study_data/English/Words
                            </div>
                        )}
                    </div>
                </div>

                {/* Sentence Files */}
                <div className="space-y-2">
                    <h4 className="text-xs font-medium text-white/40 uppercase tracking-wider px-1">Sentence Collections</h4>
                    <div className="grid grid-cols-1 gap-2">
                        {dictStats?.available_sentence_files && dictStats.available_sentence_files.length > 0 ? (
                            dictStats.available_sentence_files.map((file: string) => (
                                <button
                                    key={file}
                                    onClick={() => handleSwitchDict(file, true)}
                                    className={`glass-card rounded-xl p-3 text-left hover:bg-white/10 transition-all duration-300 group ${dictStats?.current_sentence_collection === file ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-white/5'}`}
                                >
                                    <div className="flex items-center justify-between">
                                        <span className={`text-sm ${dictStats?.current_sentence_collection === file ? 'text-emerald-400 font-medium' : 'text-white/70'}`}>{file}</span>
                                        {dictStats?.current_sentence_collection === file && <CheckCircle size={14} className="text-emerald-500" />}
                                    </div>
                                </button>
                            ))
                        ) : (
                            <div className="p-4 border border-dashed border-white/10 rounded-xl text-center text-white/20 text-xs">
                                No sentence files found in data/study_data/English/Sentence
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
      ) : showDictList ? (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between mb-2">
                <button 
                    onClick={() => setShowDictList(false)}
                    className="flex items-center gap-1 text-xs text-white/40 hover:text-emerald-300 transition-colors"
                >
                    <ArrowLeft size={12} /> Back
                </button>
                <span className="text-xs text-white/30">
                    {dictList.length} words loaded
                </span>
            </div>
            
            <div className="space-y-2">
                {dictList.map((w, i) => (
                    <button 
                        key={`${w.word}-${i}`} 
                        onClick={() => handleSelectWord(w.word)}
                        className="w-full text-left glass-card rounded-lg p-3 hover:bg-white/10 transition-all duration-300 group flex items-center justify-between"
                    >
                        <span className="font-mono text-emerald-400 font-medium group-hover:text-emerald-300 transition-colors text-glow">{w.word}</span>
                        <div className="flex items-center gap-3 overflow-hidden">
                            {w.translations?.[0] && (
                                <span className="text-xs text-white/50 truncate text-right max-w-[100px]">
                                    {w.translations[0].translation}
                                </span>
                            )}
                            <button 
                                onClick={(e) => { e.stopPropagation(); handleAddToLearning(w.word); }}
                                className="p-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 rounded-md border border-emerald-500/20 transition-all opacity-0 group-hover:opacity-100"
                                title="Add to learning"
                            >
                                <Zap size={12} />
                            </button>
                            <ChevronRight size={14} className="text-white/20 group-hover:text-emerald-400 transition-colors flex-shrink-0" />
                        </div>
                    </button>
                ))}
                {dictLoading && (
                    <div className="py-2 flex justify-center">
                        <RefreshCw className="animate-spin text-zinc-500" size={16} />
                    </div>
                )}
                {!dictHasMore && dictList.length > 0 && (
                    <div className="py-2 text-center text-xs text-zinc-600">
                        End of dictionary
                    </div>
                )}
            </div>
        </div>
      ) : dictResults ? (
         <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-medium text-white/50 uppercase tracking-wider">Search Results</h4>
              <button onClick={() => { setDictResults(null); setDictSearch(''); }} className="text-xs text-indigo-400 hover:text-indigo-300">Clear</button>
            </div>
            {dictResults.map((w, i) => (
              <InfoCard key={i} className="group !p-3">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-bold text-white/90 font-mono tracking-wide">{w.word}</h3>
                    <button 
                        onClick={() => handleAddToLearning(w.word)}
                        className="flex items-center gap-1 px-2 py-1 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[10px] rounded-md border border-emerald-500/20 transition-all"
                    >
                        <Zap size={10} /> Add to Learn
                    </button>
                  </div>
                  <div className="space-y-0.5">
                    {w.definition && w.definition.map((t: any, i: number) => (
                      <div key={i} className="flex items-start gap-2 text-xs text-white/60">
                        <span className="text-[10px] text-white/30 uppercase w-6 pt-0.5 text-right font-mono flex-shrink-0">{t.type}.</span>
                        <span>{t.translation}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </InfoCard>
            ))}
         </div>
      ) : (
         <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
            <div className="w-20 h-20 rounded-full bg-emerald-500/5 flex items-center justify-center mb-6 border border-emerald-500/10 shadow-[0_0_30px_rgba(16,185,129,0.05)]">
                <BookOpen size={40} className="text-emerald-500/40" />
            </div>
            <h3 className="text-white/80 font-medium mb-2">English Dictionary</h3>
            <p className="text-sm text-white/40 mb-8 max-w-[200px]">
                Search for any word to see its translation and add it to your learning list
            </p>
            
            <div className="grid grid-cols-1 gap-3 w-full max-w-[240px]">
                <button 
                    onClick={() => { setShowDictList(true); fetchDictList(1, true); }}
                    className="flex items-center justify-center gap-2 py-3 px-4 glass-panel border border-white/10 rounded-xl text-sm text-white/70 hover:text-emerald-400 hover:border-emerald-500/30 transition-all duration-300"
                >
                    <BookOpen size={16} />
                    Browse All Words
                </button>
                <button 
                    onClick={() => setShowResources(true)}
                    className="flex items-center justify-center gap-2 py-3 px-4 glass-panel border border-white/10 rounded-xl text-sm text-white/70 hover:text-emerald-400 hover:border-emerald-500/30 transition-all duration-300"
                >
                    <Grid size={16} />
                    Switch Dictionary
                </button>
            </div>
         </div>
      )}
      </div>
    </div>
  );

  const renderRecordsView = () => {
    const vocabSummary = (studyOverview && studyOverview.daily_summary && studyOverview.daily_summary.vocab) || {};
    const sessionSummaryData = (studyOverview && studyOverview.daily_summary && studyOverview.daily_summary.session) || {};
    const dueWords = Number(vocabSummary.to_review || 0);
    const dailyQuota = Number(vocabSummary.daily_quota || 20);
    const todaySessions = Array.isArray(studySessions) ? [...studySessions].reverse() : [];
    const recentChat = (studyPanelBundle && studyPanelBundle.recent_chat_history) || [];
    return (
      <div className="flex-1 min-h-0 flex flex-col gap-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-white/50">待复习</div>
            <div className="text-2xl font-bold text-amber-300">{dueWords}</div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-white/50">每日目标</div>
            <div className="text-2xl font-bold text-emerald-300">{dailyQuota}</div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-white/50">今日已复习</div>
            <div className="text-2xl font-bold text-white">{Number(sessionSummaryData.words_reviewed || 0)}</div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-white/50">连续学习</div>
            <div className="text-2xl font-bold text-white">{Number(studyOverview?.study_streak_days || 0)} 天</div>
          </div>
        </div>

        <div className="glass-card rounded-xl p-4 text-xs text-white/60">
          待复习是累计欠账，不受每日 20 新词上限限制；如果历史欠账&gt;20，会显示 24、30 这种数字。
        </div>

        <div className="glass-card rounded-xl p-4 text-xs text-white/60">
          当前聚合：学习面板 + 用户状态 + Aveline状态 + 最近聊天 {Array.isArray(recentChat) ? recentChat.length : 0} 条，可直接用于写日报。
        </div>

        <div className="grid md:grid-cols-2 gap-4 min-h-0 flex-1">
          <div className="glass-card rounded-xl p-4 space-y-3">
            <div className="text-sm text-white/80 font-medium">学习记录面板</div>
            <input
              value={recordTopic}
              onChange={(e) => setRecordTopic(e.target.value)}
              placeholder="学习主题，如：英语 / 数学 / 计算机网络"
              className="w-full px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-sm text-white outline-none focus:border-emerald-500/40"
            />
            <textarea
              value={recordContent}
              onChange={(e) => setRecordContent(e.target.value)}
              placeholder="记录内容，如：完成阅读第3章，整理错题12道"
              className="w-full h-24 px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-sm text-white outline-none focus:border-emerald-500/40 resize-none"
            />
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={5}
                max={240}
                value={recordDuration}
                onChange={(e) => setRecordDuration(Number(e.target.value || 45))}
                className="w-28 px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-sm text-white outline-none focus:border-emerald-500/40"
              />
              <span className="text-xs text-white/50">分钟</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button
                onClick={handleStartStudy}
                className="px-3 py-2 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs hover:bg-emerald-500/30"
              >
                开始学习
              </button>
              <button
                onClick={handleFinishStudy}
                className="px-3 py-2 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-500/30 text-xs hover:bg-blue-500/30"
              >
                结束学习
              </button>
              <button
                onClick={handleRecordStudy}
                className="px-3 py-2 rounded-lg bg-white/10 text-white border border-white/20 text-xs hover:bg-white/20"
              >
                仅记录
              </button>
            </div>
            {successMsg && <div className="text-xs text-emerald-300">{successMsg}</div>}
            {error && <div className="text-xs text-red-300">{error}</div>}
          </div>

          <div className="glass-card rounded-xl p-4 min-h-0 flex flex-col">
            <div className="text-sm text-white/80 font-medium mb-3">今日学习流水</div>
            <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar pr-1 space-y-2">
              {todaySessions.length === 0 && (
                <div className="text-xs text-white/40 py-8 text-center">今天还没有学习记录</div>
              )}
              {todaySessions.map((item, idx) => (
                <div key={`${item.time || 't'}-${idx}`} className="bg-black/25 border border-white/10 rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-emerald-300">{item.topic || '学习'}</span>
                    <span className="text-[11px] text-white/40 font-mono">{item.time || '--:--'}</span>
                  </div>
                  <div className="text-xs text-white/70 mt-1">{item.content || ''}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-black/20">
      <div className="p-3 border-b border-white/5 bg-black/10">
        {renderHeader()}
      </div>
      
      <div className="flex-1 min-h-0 overflow-hidden relative p-3 flex flex-col">
        <AnimatePresence mode='wait'>
          <motion.div
            key={activeView}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
            className="flex-1 min-h-0 flex flex-col"
          >
            {activeView === 'daily' && renderDailyView()}
            {activeView === 'records' && renderRecordsView()}
            {activeView === 'tools' && renderTools()}
            {activeView === 'files' && <StudyFileManager />}
            {activeView === 'dictionary' && renderDictionary()}
            {activeView === 'curve' && (
                <div className="flex-1 flex flex-col gap-4">
                    <div className="glass-card rounded-xl p-6 flex flex-col items-center justify-center">
                        <h3 className="text-sm font-medium text-white/80 mb-6">Retention Curve</h3>
                        <div className="flex items-end gap-2 h-40 w-full px-4">
                            {curveData.length > 0 ? curveData.map((val, i) => (
                                <div key={i} className="flex-1 flex flex-col items-center gap-2">
                                    <div className="w-full bg-emerald-500/20 rounded-t-sm relative group">
                                        <div 
                                            className="absolute bottom-0 left-0 w-full bg-emerald-500 rounded-t-sm transition-all duration-500"
                                            style={{ height: `${val}%` }}
                                        />
                                        <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-black/80 text-white text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                                            {val}% Retention
                                        </div>
                                    </div>
                                    <span className="text-[10px] text-white/30">Day {i+1}</span>
                                </div>
                            )) : (
                                <div className="w-full h-full flex items-center justify-center text-white/20">
                                    No data available
                                </div>
                            )}
                        </div>
                    </div>
                    
                    <div className="glass-card rounded-xl p-4">
                        <h3 className="text-sm font-medium text-white/80 mb-4">Learning Stats</h3>
                        <div className="space-y-4">
                            <div className="flex justify-between items-center">
                                <span className="text-xs text-white/60">Total Words</span>
                                <span className="text-sm font-mono text-white">{dictStats?.total_words || 0}</span>
                            </div>
                            <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-indigo-500" style={{ width: '100%' }} />
                            </div>
                            
                            <div className="flex justify-between items-center">
                                <span className="text-xs text-white/60">Mastered</span>
                                <span className="text-sm font-mono text-emerald-400">{dictStats?.learned_words || 0}</span>
                            </div>
                            <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-emerald-500" style={{ width: `${dictStats?.total_words ? (dictStats.learned_words / dictStats.total_words * 100) : 0}%` }} />
                            </div>

                            <div className="flex justify-between items-center">
                                <span className="text-xs text-white/60">To Review</span>
                                <span className="text-sm font-mono text-amber-400">{dictStats?.to_review || 0}</span>
                            </div>
                             <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-amber-500" style={{ width: `${dictStats?.total_words ? (dictStats.to_review / dictStats.total_words * 100) : 0}%` }} />
                            </div>
                        </div>
                    </div>
                </div>
            )}
            {activeView === 'mistakes' && (
                 <div className="flex-1 overflow-y-auto custom-scrollbar">
                    {mistakesData.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-white/20 pt-20">
                            <CheckCircle size={48} className="mb-4 opacity-50" />
                            <p className="text-sm">No mistakes recorded yet!</p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {mistakesData.map((m, i) => (
                                <div key={i} className="glass-card rounded-xl p-4 border-l-2 border-l-red-500/50">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="text-lg font-bold text-white/90">{m.word}</h3>
                                        <span className="text-xs text-red-400 bg-red-500/10 px-2 py-1 rounded">
                                            {m.error_count} errors
                                        </span>
                                    </div>
                                    <div className="space-y-1">
                                        {m.translations?.map((t: any, j: number) => (
                                            <div key={j} className="text-xs text-white/60">
                                                {t.translation}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                 </div>
            )}
            {activeView === 'focus' && (
                <FocusMonitorPanel />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
};

export default StudyPanel;
