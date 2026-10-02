import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Calendar, Clock, FileText, Folder, ChevronRight, ChevronLeft, RefreshCw, AlertCircle, Book, X, Droplets, Brain, CheckCircle2 } from 'lucide-react';
import { api } from '../api/apiService';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type DailyDataEntry = {
  name: string;
  type: 'dir' | 'file';
  size?: number | null;
  count?: number | null;
  mtime?: number | null;
  ext?: string | null;
};

type DiaryEntry = {
  filename: string;
  content: string;
};

type ActiveCareRuntime = {
  running?: boolean;
  tasks?: {
    proactive?: boolean;
    startup?: boolean;
    vocab?: boolean;
    maintenance?: boolean;
  };
  next_decision_in_seconds?: number;
  next_decision_at?: string | null;
  last_computed_sleep_seconds?: number;
  last_decision_intent?: string;
  client_probe?: string;
  last_check_started_at?: string | null;
  last_check_finished_at?: string | null;
  last_skip_reason?: string | null;
  last_check_phase?: string | null;
  event_subscription_active?: boolean;
};

type ActiveCareStatusResponse = {
  status: 'success' | 'error';
  data?: ActiveCareRuntime;
  message?: string;
  detail?: string;
};

type PersistentStatusEntry = {
  name?: string;
  description?: string;
  expires_at?: number | null;
  updated_at?: number;
};

type PortraitPayload = {
  schedule?: {
    wakeup?: string | null;
    sleep?: string | null;
  };
  drink?: {
    total_ml?: number;
    count?: number;
  };
  study?: {
    total_minutes?: number;
    count?: number;
    sessions?: Array<{
      topic?: string;
      content?: string;
      time?: string;
    }>;
  };
  meals?: Array<{
    type?: string;
    content?: string;
    time?: string;
  }>;
  persistent_statuses?: PersistentStatusEntry[];
  body_metrics?: {
    weight_kg?: number | null;
    weight_updated_at?: number;
  };
  mode?: {
    preference_mode?: string;
    reduced_mode_active?: boolean;
    reduced_mode_reason?: string;
    reduced_mode_expected_end_ts?: number;
  };
};

export default function DailyDataPanel() {
  const [activeTab, setActiveTab] = useState<'portrait' | 'schedule' | 'diary' | 'files'>('portrait');
  const [loadingSchedule, setLoadingSchedule] = useState(false);
  const [activeCare, setActiveCare] = useState<ActiveCareRuntime | null>(null);
  const [loadingActiveCare, setLoadingActiveCare] = useState(false);
  const [portrait, setPortrait] = useState<PortraitPayload | null>(null);
  const [portraitDate, setPortraitDate] = useState('');
  const [loadingPortrait, setLoadingPortrait] = useState(false);
  const [portraitMessage, setPortraitMessage] = useState('');
  const [drinkUnits, setDrinkUnits] = useState(1);
  const [drinkLoading, setDrinkLoading] = useState(false);
  const [weightInput, setWeightInput] = useState('');
  const [weightLoading, setWeightLoading] = useState(false);
  const [studySubject, setStudySubject] = useState('');
  const [studyDuration, setStudyDuration] = useState(45);
  const [studyNote, setStudyNote] = useState('');
  const [studyLoading, setStudyLoading] = useState(false);
  
  // Diary State
  const [diaryDate, setDiaryDate] = useState(new Date());
  const [diaryEntries, setDiaryEntries] = useState<DiaryEntry[]>([]);
  const [loadingDiary, setLoadingDiary] = useState(false);

  // File Explorer State
  const [currentPath, setCurrentPath] = useState('');
  const [files, setFiles] = useState<DailyDataEntry[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [viewingFile, setViewingFile] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab === 'portrait') {
      fetchPortrait();
    } else if (activeTab === 'schedule') {
      fetchSchedule();
    } else if (activeTab === 'diary') {
      fetchDiary(diaryDate);
    } else if (activeTab === 'files') {
      fetchFiles(currentPath);
    }
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === 'diary') {
      fetchDiary(diaryDate);
    }
  }, [diaryDate]);

  const fetchSchedule = async () => {
    setLoadingSchedule(true);
    try {
      await Promise.all([fetchPortrait(), fetchActiveCareStatus()]);
    } catch (e) {
      console.error("Failed to fetch dynamic schedule view", e);
    } finally {
      setLoadingSchedule(false);
    }
  };

  const fetchPortrait = async () => {
    setLoadingPortrait(true);
    try {
      const res = await api.dailyDataPortraitToday({ silent: true });
      if (res?.status === 'success') {
        const nextPortrait = (res.portrait || null) as PortraitPayload | null;
        setPortrait(nextPortrait);
        const weightVal = nextPortrait?.body_metrics?.weight_kg;
        if (typeof weightVal === 'number' && Number.isFinite(weightVal)) {
          setWeightInput(weightVal.toFixed(1));
        }
        setPortraitDate(String(res.date || ''));
      }
    } catch (e) {
      console.error('Failed to fetch portrait', e);
    } finally {
      setLoadingPortrait(false);
    }
  };

  const handleQuickDrink = async (units: number) => {
    setDrinkLoading(true);
    setPortraitMessage('');
    try {
      const res = await api.dailyDataRecordDrink({ units }, { silent: true });
      if (res?.status === 'success') {
        setPortrait((res.portrait || null) as PortraitPayload | null);
        setPortraitMessage(`已记录喝水 ${res.drink_ml || units * 250}ml`);
      }
    } catch (e) {
      console.error('Failed to record drink', e);
      setPortraitMessage('喝水记录失败');
    } finally {
      setDrinkLoading(false);
    }
  };

  const handleSaveWeight = async () => {
    const value = Number(weightInput);
    if (!Number.isFinite(value)) {
      setPortraitMessage('请输入有效体重');
      return;
    }
    setWeightLoading(true);
    setPortraitMessage('');
    try {
      const res = await api.dailyDataRecordBodyMetrics({ weight_kg: value }, { silent: true });
      if (res?.status === 'success') {
        setPortrait((res.portrait || null) as PortraitPayload | null);
        setPortraitMessage(`体重已更新：${value.toFixed(1)}kg`);
      }
    } catch (e) {
      console.error('Failed to record body metrics', e);
      setPortraitMessage('体重更新失败');
    } finally {
      setWeightLoading(false);
    }
  };

  const handleStartStudy = async () => {
    const subject = studySubject.trim();
    if (!subject) {
      setPortraitMessage('请先填写学习科目');
      return;
    }
    setStudyLoading(true);
    setPortraitMessage('');
    try {
      const res = await api.dailyDataRecordStudy(
        {
          subject,
          duration_minutes: studyDuration,
          note: studyNote.trim(),
          enter_low_disturbance: true,
          switch_mode_to_study: true,
        },
        { silent: true },
      );
      if (res?.status === 'success') {
        setPortrait((res.portrait || null) as PortraitPayload | null);
        setPortraitMessage(`已开始学习：${subject}（${studyDuration}分钟，低打扰已开启）`);
      }
    } catch (e) {
      console.error('Failed to record study', e);
      setPortraitMessage('学习记录失败');
    } finally {
      setStudyLoading(false);
    }
  };

  const handleFinishStudy = async () => {
    setStudyLoading(true);
    setPortraitMessage('');
    try {
      const res = await api.dailyDataFinishStudy({ silent: true });
      if (res?.status === 'success') {
        setPortrait((res.portrait || null) as PortraitPayload | null);
        setPortraitMessage('学习时段已结束，低打扰已关闭');
      }
    } catch (e) {
      console.error('Failed to finish study', e);
      setPortraitMessage('结束学习失败');
    } finally {
      setStudyLoading(false);
    }
  };

  const fetchActiveCareStatus = async () => {
    setLoadingActiveCare(true);
    try {
      const res = (await api.getActiveCareStatus({ silent: true })) as ActiveCareStatusResponse;
      if (res?.status === 'success') {
        setActiveCare((res.data || null) as ActiveCareRuntime | null);
      }
    } catch (e) {
      console.error("Failed to fetch Active Care status", e);
    } finally {
      setLoadingActiveCare(false);
    }
  };

  const getDiaryPath = (date: Date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `daily/${year}/${month}/${day}/diary`;
  };

  const fetchDiary = async (date: Date) => {
    setLoadingDiary(true);
    setDiaryEntries([]);
    try {
      const path = getDiaryPath(date);
      // Check if directory exists first or just try to list
      const res = await api.dailyDataList({ path, limit: 100 });
      
      if (res.status === 'success' && Array.isArray(res.items)) {
        const entries: DiaryEntry[] = [];
        // Filter for files only
        const fileItems = res.items.filter((item: DailyDataEntry) => item.type === 'file');
        
        // Fetch content for each file
        for (const item of fileItems) {
          try {
            const contentRes = await api.dailyDataRead({ path: `${path}/${item.name}` });
            if (contentRes.status === 'success') {
              entries.push({
                filename: item.name,
                content: contentRes.content || ''
              });
            }
          } catch (err) {
            console.error(`Failed to read diary entry ${item.name}`, err);
          }
        }
        setDiaryEntries(entries);
      }
    } catch (e) {
      console.log("No diary entries found for this date (or directory missing)");
      // It's normal to fail if directory doesn't exist
    } finally {
      setLoadingDiary(false);
    }
  };

  const handleDateChange = (days: number) => {
    const newDate = new Date(diaryDate);
    newDate.setDate(diaryDate.getDate() + days);
    setDiaryDate(newDate);
  };

  const fetchFiles = async (path: string) => {
    setLoadingFiles(true);
    try {
      const res = await api.dailyDataList({ path, limit: 100 });
      if (res.status === 'success' && Array.isArray(res.items)) {
        // Sort by name descending (newest dates first)
        const sortedItems = [...res.items].sort((a: DailyDataEntry, b: DailyDataEntry) => {
            return b.name.localeCompare(a.name);
        });
        setFiles(sortedItems);
      }
    } catch (e) {
      console.error("Failed to fetch files", e);
    } finally {
      setLoadingFiles(false);
    }
  };

  const handleFileClick = async (entry: DailyDataEntry) => {
    const fullPath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
    if (entry.type === 'dir') {
      setCurrentPath(fullPath);
      fetchFiles(fullPath);
    } else {
      // Read file
      try {
        const res = await api.dailyDataRead({ path: fullPath });
        if (res.status === 'success') {
          setViewingFile(entry.name);
          setFileContent(res.content || '');
        }
      } catch (e) {
        console.error("Failed to read file", e);
      }
    }
  };

  const goUp = () => {
    if (!currentPath) return;
    const parts = currentPath.split('/');
    parts.pop();
    const newPath = parts.join('/');
    setCurrentPath(newPath);
    fetchFiles(newPath);
  };

  return (
    <div className="flex flex-col h-full bg-black/20 backdrop-blur-md rounded-2xl border border-white/10 overflow-hidden text-white/90 md:bg-black/20 md:border-white/10 bg-transparent border-none">
      {/* Header */}
      <div className="p-4 md:p-6 border-b border-white/10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Calendar className="text-emerald-400 shrink-0" size={24} />
          <div>
            <h2 className="text-xl md:text-2xl font-bold tracking-tight font-display">
              Daily Data Center
            </h2>
            <p className="text-[10px] md:text-sm text-white/40 mt-0.5">Manage schedules, diaries, and logs.</p>
          </div>
        </div>
        
        <div className="flex bg-black/40 rounded-lg p-1 gap-1 w-full sm:w-auto overflow-x-auto no-scrollbar">
          {(['portrait', 'schedule', 'diary', 'files'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`flex-1 sm:flex-none px-4 py-2 rounded-md text-xs md:text-sm font-medium transition-all whitespace-nowrap ${
                activeTab === tab 
                  ? 'bg-emerald-500/20 text-emerald-300 shadow-sm' 
                  : 'text-white/40 hover:text-white/80 hover:bg-white/5'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden p-4 md:p-6">
        <AnimatePresence mode="wait">
          {activeTab === 'portrait' && (
            <motion.div
              key="portrait"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full overflow-y-auto custom-scrollbar"
            >
              {loadingPortrait ? (
                <div className="flex items-center justify-center h-40 text-white/30 animate-pulse">Loading portrait...</div>
              ) : (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                  <div className="xl:col-span-2 space-y-4">
                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-semibold text-emerald-300">用户画像（今日）</h3>
                        <button
                          onClick={fetchPortrait}
                          className="text-xs px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-white/70 transition-colors"
                        >
                          Refresh
                        </button>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">日期</div>
                          <div className="font-mono text-emerald-200">{portraitDate || '—'}</div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">打扰级别</div>
                          <div className="font-mono text-emerald-200">
                            {portrait?.mode?.reduced_mode_active ? '低打扰中' : '普通'}
                            {portrait?.mode?.preference_mode ? ` / ${portrait.mode.preference_mode}` : ''}
                          </div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">今日饮水</div>
                          <div className="font-mono text-emerald-200">
                            {Number.isFinite(portrait?.drink?.total_ml) ? `${portrait?.drink?.total_ml} ml` : '0 ml'}
                            <span className="text-white/40 ml-2">({portrait?.drink?.count || 0} 次)</span>
                          </div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">今日学习</div>
                          <div className="font-mono text-emerald-200">
                            {Number.isFinite(portrait?.study?.total_minutes) ? `${portrait?.study?.total_minutes} 分钟` : '0 分钟'}
                            <span className="text-white/40 ml-2">({portrait?.study?.count || 0} 次)</span>
                          </div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">当前体重</div>
                          <div className="font-mono text-emerald-200">
                            {Number.isFinite(portrait?.body_metrics?.weight_kg)
                              ? `${portrait?.body_metrics?.weight_kg} kg`
                              : '未设置'}
                          </div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">起床</div>
                          <div className="font-mono text-emerald-200">{portrait?.schedule?.wakeup || '未记录'}</div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-white/40 text-xs mb-1">睡觉</div>
                          <div className="font-mono text-emerald-200">{portrait?.schedule?.sleep || '未记录'}</div>
                        </div>
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <h4 className="text-sm font-semibold text-white/80 mb-3">最近学习记录</h4>
                      <div className="space-y-2 max-h-56 overflow-y-auto custom-scrollbar pr-1">
                        {(portrait?.study?.sessions || []).slice().reverse().map((item, idx) => (
                          <div key={`${item.time || 't'}-${idx}`} className="bg-black/20 rounded-lg border border-white/10 p-3">
                            <div className="flex items-center justify-between">
                              <span className="text-emerald-300">{item.topic || '学习'}</span>
                              <span className="text-xs text-white/40 font-mono">{item.time || '--:--'}</span>
                            </div>
                            <div className="text-xs text-white/70 mt-1">{item.content || ''}</div>
                          </div>
                        ))}
                        {(portrait?.study?.sessions || []).length === 0 && (
                          <div className="text-white/30 text-sm py-6 text-center">今天还没有学习记录</div>
                        )}
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <h4 className="text-sm font-semibold text-white/80 mb-3">持续化状态</h4>
                      <div className="space-y-2 max-h-56 overflow-y-auto custom-scrollbar pr-1">
                        {(portrait?.persistent_statuses || []).map((item, idx) => (
                          <div key={`${item.name || 'status'}-${idx}`} className="bg-black/20 rounded-lg border border-white/10 p-3">
                            <div className="flex items-center justify-between">
                              <span className="text-emerald-300">{item.name || '状态'}</span>
                              <span className="text-xs text-white/40 font-mono">
                                {item.expires_at ? `到期 ${new Date(item.expires_at * 1000).toLocaleDateString()}` : '长期'}
                              </span>
                            </div>
                            <div className="text-xs text-white/70 mt-1">{item.description || ''}</div>
                          </div>
                        ))}
                        {(portrait?.persistent_statuses || []).length === 0 && (
                          <div className="text-white/30 text-sm py-6 text-center">暂无持续化状态</div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex items-center gap-2 mb-3 text-emerald-300">
                        <CheckCircle2 size={16} />
                        <h4 className="text-sm font-semibold">体重管理</h4>
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="number"
                          min={20}
                          max={300}
                          step={0.1}
                          value={weightInput}
                          onChange={(e) => setWeightInput(e.target.value)}
                          placeholder="输入 kg"
                          className="w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder:text-white/30"
                        />
                        <button
                          onClick={handleSaveWeight}
                          disabled={weightLoading}
                          className="px-3 py-2 text-xs rounded-lg bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 border border-emerald-500/20 disabled:opacity-50 whitespace-nowrap"
                        >
                          保存
                        </button>
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex items-center gap-2 mb-3 text-emerald-300">
                        <Droplets size={16} />
                        <h4 className="text-sm font-semibold">快捷喝水</h4>
                      </div>
                      <div className="grid grid-cols-3 gap-2 mb-3">
                        {[1, 2, 3].map((unit) => (
                          <button
                            key={unit}
                            onClick={() => handleQuickDrink(unit)}
                            disabled={drinkLoading}
                            className="px-2 py-2 text-xs rounded-lg bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25 border border-cyan-500/20 disabled:opacity-50"
                          >
                            +{unit * 250}ml
                          </button>
                        ))}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="number"
                          min={1}
                          max={10}
                          value={drinkUnits}
                          onChange={(e) => setDrinkUnits(Number(e.target.value || 1))}
                          className="w-20 bg-black/30 border border-white/15 rounded-lg px-2 py-2 text-sm text-white"
                        />
                        <button
                          onClick={() => handleQuickDrink(drinkUnits)}
                          disabled={drinkLoading}
                          className="flex-1 px-3 py-2 text-xs rounded-lg bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 border border-emerald-500/20 disabled:opacity-50"
                        >
                          记录 {drinkUnits * 250}ml
                        </button>
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex items-center gap-2 mb-3 text-emerald-300">
                        <Brain size={16} />
                        <h4 className="text-sm font-semibold">学习记录</h4>
                      </div>
                      <div className="space-y-2">
                        <input
                          value={studySubject}
                          onChange={(e) => setStudySubject(e.target.value)}
                          placeholder="科目，例如：线代 / 英语 / 前端"
                          className="w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder:text-white/30"
                        />
                        <input
                          type="number"
                          min={1}
                          max={720}
                          value={studyDuration}
                          onChange={(e) => setStudyDuration(Number(e.target.value || 45))}
                          className="w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white"
                        />
                        <input
                          value={studyNote}
                          onChange={(e) => setStudyNote(e.target.value)}
                          placeholder="备注（可选）"
                          className="w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder:text-white/30"
                        />
                        <button
                          onClick={handleStartStudy}
                          disabled={studyLoading}
                          className="w-full px-3 py-2 text-xs rounded-lg bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 border border-indigo-500/20 disabled:opacity-50"
                        >
                          开始学习并进入低打扰
                        </button>
                        <button
                          onClick={handleFinishStudy}
                          disabled={studyLoading}
                          className="w-full px-3 py-2 text-xs rounded-lg bg-white/10 text-white/80 hover:bg-white/20 border border-white/20 disabled:opacity-50"
                        >
                          结束学习并恢复普通模式
                        </button>
                      </div>
                    </div>

                    {portraitMessage && (
                      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-xs text-emerald-200 flex items-center gap-2">
                        <CheckCircle2 size={14} />
                        <span>{portraitMessage}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'schedule' && (
            <motion.div 
              key="schedule"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full overflow-y-auto custom-scrollbar"
            >
              {loadingSchedule ? (
                <div className="flex items-center justify-center h-40 text-white/30 animate-pulse">Loading schedule...</div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div className="space-y-4">
                    <div className="bg-white/5 rounded-xl p-6 border border-white/5">
                      <h3 className="text-lg font-semibold text-emerald-300 mb-4 flex items-center gap-2">
                        <Clock size={18} />
                        Dynamic Active Care
                      </h3>
                      <div className="text-sm text-white/70 leading-relaxed bg-black/20 border border-white/10 rounded-lg p-4">
                        当前采用动态检查与上下文驱动策略，不再依赖固定时段 `schedule` 文件。实际触发会结合你今天记录到的作息、最近互动、低打扰状态和节流规则实时调整。
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-xs text-white/40 mb-1">今日起床</div>
                          <div className="font-mono text-emerald-200">{portrait?.schedule?.wakeup || '未记录'}</div>
                        </div>
                        <div className="bg-black/20 rounded-lg border border-white/10 p-3">
                          <div className="text-xs text-white/40 mb-1">最近睡觉</div>
                          <div className="font-mono text-emerald-200">{portrait?.schedule?.sleep || '未记录'}</div>
                        </div>
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-xl p-6 border border-white/5 h-fit">
                      <h3 className="text-lg font-semibold text-white/80 mb-4">Dynamic Signals</h3>
                      <div className="space-y-4">
                        <div className="flex justify-between items-center py-2 border-b border-white/5">
                          <span className="text-white/60">作息来源</span>
                          <span className="font-mono text-emerald-400">daily portrait</span>
                        </div>
                        <div className="flex justify-between items-center py-2 border-b border-white/5">
                          <span className="text-white/60">调度模式</span>
                          <span className="font-mono">context-driven</span>
                        </div>
                        <div className="flex justify-between items-center py-2 border-b border-white/5">
                          <span className="text-white/60">偏好模式</span>
                          <span className="font-mono">{portrait?.mode?.preference_mode || 'normal'}</span>
                        </div>
                        <div className="flex justify-between items-center py-2 border-b border-white/5">
                          <span className="text-white/60">低打扰</span>
                          <span className="font-mono">{portrait?.mode?.reduced_mode_active ? 'true' : 'false'}</span>
                        </div>
                        <div className="flex justify-between items-center py-2 border-b border-white/5">
                          <span className="text-white/60">低打扰原因</span>
                          <span className="font-mono">{portrait?.mode?.reduced_mode_reason || 'none'}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="bg-white/5 rounded-xl p-6 border border-white/5 h-fit">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold text-white/80">Active Care Runtime</h3>
                        <button
                          onClick={fetchActiveCareStatus}
                          className="text-xs px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-white/70 transition-colors"
                        >
                          Refresh
                        </button>
                      </div>
                      {loadingActiveCare ? (
                        <div className="text-white/30 text-sm animate-pulse">Loading runtime status...</div>
                      ) : activeCare ? (
                        <div className="space-y-4">
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Running</span>
                            <span className="font-mono">{activeCare.running ? 'true' : 'false'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Next Check</span>
                            <span className="font-mono">{Number.isFinite(activeCare.next_decision_in_seconds) ? `${activeCare.next_decision_in_seconds}s` : '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Next Check At</span>
                            <span className="font-mono">{activeCare.next_decision_at || '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Last Intent</span>
                            <span className="font-mono">{activeCare.last_decision_intent || '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Last Phase</span>
                            <span className="font-mono">{activeCare.last_check_phase || '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Skip Reason</span>
                            <span className="font-mono">{activeCare.last_skip_reason || '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Computed Sleep Seconds</span>
                            <span className="font-mono">{Number.isFinite(activeCare.last_computed_sleep_seconds) ? `${activeCare.last_computed_sleep_seconds}s` : '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Last Check Start</span>
                            <span className="font-mono">{activeCare.last_check_started_at || '—'}</span>
                          </div>
                          <div className="flex justify-between items-center py-2 border-b border-white/5">
                            <span className="text-white/60">Last Check End</span>
                            <span className="font-mono">{activeCare.last_check_finished_at || '—'}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="text-white/30 text-sm">Active Care is offline or status unavailable.</div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'diary' && (
            <motion.div
              key="diary"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full flex flex-col"
            >
              {/* Date Navigation */}
              <div className="flex items-center justify-between mb-4 md:mb-6 bg-white/5 p-3 md:p-4 rounded-xl border border-white/5">
                <button 
                  onClick={() => handleDateChange(-1)}
                  className="p-2 hover:bg-white/10 rounded-lg transition-colors text-white/60 hover:text-white"
                >
                  <ChevronLeft size={20} />
                </button>
                <div className="flex flex-col items-center text-center">
                  <span className="text-lg md:text-2xl font-light font-display text-emerald-300">
                    {diaryDate.toLocaleDateString('en-US', { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })}
                  </span>
                  <span className="text-[10px] md:text-xs text-white/40 font-mono mt-1 truncate max-w-[150px] md:max-w-none">
                    {getDiaryPath(diaryDate)}
                  </span>
                </div>
                <button 
                  onClick={() => handleDateChange(1)}
                  className="p-2 hover:bg-white/10 rounded-lg transition-colors text-white/60 hover:text-white"
                >
                  <ChevronRight size={20} />
                </button>
              </div>

              {/* Diary Entries */}
              <div className="flex-1 overflow-y-auto custom-scrollbar space-y-6">
                {loadingDiary ? (
                  <div className="text-center py-20 text-white/30 animate-pulse">Checking for memories...</div>
                ) : diaryEntries.length > 0 ? (
                  diaryEntries.map((entry, idx) => (
                    <div key={idx} className="bg-black/20 border border-white/5 rounded-xl overflow-hidden">
                      <div className="bg-white/5 px-4 py-2 border-b border-white/5 flex items-center gap-2">
                        <Book size={16} className="text-emerald-500/60" />
                        <span className="font-mono text-[10px] md:text-sm text-white/60 truncate">{entry.filename}</span>
                      </div>
                      <div className="p-4 md:p-6 prose prose-invert prose-emerald max-w-none prose-sm md:prose-base">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {entry.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center h-64 text-white/20 border-2 border-dashed border-white/5 rounded-xl">
                    <Book size={48} className="mb-4 opacity-20" />
                    <p>No diary entries found for this day.</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {activeTab === 'files' && (
            <motion.div
              key="files"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full flex flex-col"
            >
              {/* Breadcrumbs & Actions */}
              <div className="flex items-center gap-2 mb-4 text-sm font-mono text-white/50 bg-black/20 p-2 rounded-lg overflow-x-auto no-scrollbar whitespace-nowrap">
                <button onClick={() => { setCurrentPath(''); fetchFiles(''); }} className="hover:text-emerald-400 transition-colors shrink-0">
                  ROOT
                </button>
                {currentPath.split('/').filter(Boolean).map((part, i, arr) => (
                  <React.Fragment key={i}>
                    <ChevronRight size={14} className="shrink-0" />
                    <button 
                      onClick={() => {
                        const newPath = arr.slice(0, i + 1).join('/');
                        setCurrentPath(newPath);
                        fetchFiles(newPath);
                      }}
                      className="hover:text-emerald-400 transition-colors shrink-0"
                    >
                      {part}
                    </button>
                  </React.Fragment>
                ))}
              </div>

              <div className="flex-1 flex gap-4 overflow-hidden">
                {/* File List */}
                <div className={`${viewingFile ? 'w-1/3 hidden md:block' : 'w-full'} overflow-y-auto custom-scrollbar bg-white/5 rounded-xl border border-white/5`}>
                  {currentPath && (
                    <button 
                      onClick={goUp}
                      className="w-full flex items-center gap-3 p-3 hover:bg-white/5 text-white/50 hover:text-white transition-colors border-b border-white/5"
                    >
                      <ChevronLeft size={16} />
                      <span>..</span>
                    </button>
                  )}
                  {loadingFiles ? (
                    <div className="p-4 text-center text-white/30 animate-pulse">Loading...</div>
                  ) : files.map((file, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleFileClick(file)}
                      className={`w-full flex items-center gap-3 p-3 hover:bg-white/5 transition-colors border-b border-white/5 last:border-0 ${
                        viewingFile === file.name ? 'bg-emerald-500/10 text-emerald-300' : 'text-white/70'
                      }`}
                    >
                      {file.type === 'dir' ? (
                        <Folder size={18} className="text-yellow-500/80" />
                      ) : (
                        <FileText size={18} className="text-blue-400/80" />
                      )}
                      <span className="truncate">{file.name}</span>
                      <div className="ml-auto text-xs text-white/20 font-mono">
                        {file.type === 'dir' ? (
                          file.count !== undefined && file.count !== null ? `${file.count} items` : 'DIR'
                        ) : (
                          file.size !== undefined && file.size !== null && file.size > 0 ? `${Math.ceil(file.size / 1024)}KB` : 
                          (file.size === 0 ? '0KB' : '')
                        )}
                      </div>
                    </button>
                  ))}
                  {files.length === 0 && !loadingFiles && (
                    <div className="p-8 text-center text-white/20">Empty directory</div>
                  )}
                </div>

                {/* File Preview */}
                {viewingFile && (
                  <div className="flex-1 bg-black/40 rounded-xl border border-white/10 overflow-hidden flex flex-col">
                    <div className="p-3 border-b border-white/10 flex justify-between items-center bg-white/5">
                      <div className="flex items-center gap-2 overflow-hidden">
                        <FileText size={14} className="text-emerald-500/60 shrink-0" />
                        <span className="font-mono text-xs md:text-sm text-emerald-400 truncate">{viewingFile}</span>
                      </div>
                      <button 
                        onClick={() => { setViewingFile(null); setFileContent(null); }} 
                        className="p-1 hover:bg-white/10 rounded-lg text-white/40 hover:text-white transition-colors"
                      >
                        <X size={18} />
                      </button>
                    </div>
                    <div className="flex-1 overflow-auto p-4 custom-scrollbar">
                      {(() => {
                        if (!fileContent) return null;
                        
                        // JSONL Pretty Print
                        if (viewingFile?.endsWith('.jsonl')) {
                           try {
                             const lines = fileContent.trim().split('\n').filter(l => l.trim());
                             const objects = lines.map(line => {
                               try {
                                 return JSON.parse(line);
                               } catch (e) {
                                 return { _raw_error: true, content: line };
                               }
                             });

                             return (
                               <div className="space-y-4">
                                 {/* Explanation for device_context */}
                                 {viewingFile.includes('device_context') && (
                                    <div className="bg-emerald-500/10 border border-emerald-500/20 p-3 rounded-lg mb-4">
                                        <div className="flex items-center gap-2 mb-1">
                                            <AlertCircle size={14} className="text-emerald-400" />
                                            <h4 className="text-emerald-400 font-semibold text-xs">设备上下文日志 (Device Context Log)</h4>
                                        </div>
                                        <p className="text-emerald-300/70 text-[10px] leading-relaxed">
                                            此文件记录设备的实时状态（如电量、网络环境、当前运行的应用、是否睡眠等）。<br/>
                                            <span className="opacity-80">作用：</span>AI 通过分析这些数据来判断您当前的情境，从而决定是否触发“主动关怀”消息（例如在您空闲时聊天，或在您忙碌时保持安静）。
                                        </p>
                                    </div>
                                 )}

                                 {objects.map((obj, i) => (
                                   <div key={i} className="bg-white/5 p-3 rounded-lg border border-white/5 hover:border-white/10 transition-colors">
                                      <div className="text-[10px] text-white/30 mb-2 font-mono flex justify-between uppercase tracking-wider">
                                        <span>Record #{i + 1}</span>
                                        <span className="text-emerald-500/50">
                                            {obj.timestamp ? new Date(obj.timestamp * 1000).toLocaleTimeString() : 
                                             (obj.server_timestamp ? new Date(obj.server_timestamp).toLocaleTimeString() : '')}
                                        </span>
                                      </div>
                                      <pre className={`text-xs font-mono whitespace-pre-wrap overflow-x-auto ${obj._raw_error ? 'text-red-400' : 'text-emerald-300/90'}`}>
                                        {obj._raw_error ? obj.content : JSON.stringify(obj, null, 2)}
                                      </pre>
                                   </div>
                                 ))}
                               </div>
                             );
                           } catch (e) {}
                        }
                        
                        // JSON Pretty Print
                        if (viewingFile?.endsWith('.json')) {
                           try {
                             const obj = JSON.parse(fileContent);
                             return (
                               <pre className="text-xs font-mono text-emerald-300/90 whitespace-pre-wrap">
                                 {JSON.stringify(obj, null, 2)}
                               </pre>
                             );
                           } catch (e) {}
                        }

                        // Default
                        return (
                          <pre className="text-xs font-mono text-white/80 whitespace-pre-wrap">
                            {fileContent}
                          </pre>
                        );
                      })()}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
