import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, ChevronLeft, FileText, Folder, RefreshCw, X } from 'lucide-react';
import { api } from '../api/apiService';
import { EmotionType } from '../types';
import { EMOTIONS } from '../utils/emotion';

type DailyDataEntry = {
  name: string;
  type: 'dir' | 'file';
  size?: number | null;
  count?: number | null;
  mtime?: number | null;
  ext?: string | null;
};

type DailyDataListResponse = {
  status: 'success' | 'error';
  path?: string;
  items?: DailyDataEntry[];
  detail?: string;
};

type DailyDataReadResponse = {
  status: 'success' | 'error';
  path?: string;
  type?: 'json' | 'text';
  content?: string;
  truncated?: boolean;
  detail?: string;
};

type HealthResponse = {
  status?: string;
  services?: Record<string, { status?: string; details?: any }>;
};

const normalizePath = (p: string) => p.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');

const joinPath = (base: string, name: string) => {
  const b = normalizePath(base);
  const n = normalizePath(name);
  if (!b) return n;
  if (!n) return b;
  return `${b}/${n}`;
};

const parentPath = (p: string) => {
  const parts = normalizePath(p).split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
};

export default function DailyDataWidget({
  emotion,
  sidebarOpen,
}: {
  emotion: EmotionType;
  sidebarOpen: boolean;
}) {
  const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
  const [path, setPath] = useState('schedule');
  const [items, setItems] = useState<DailyDataEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [acsStatus, setAcsStatus] = useState<'healthy' | 'unhealthy' | 'unknown'>('unknown');

  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerPath, setViewerPath] = useState<string | null>(null);
  const [viewerContent, setViewerContent] = useState<string>('');
  const [viewerTruncated, setViewerTruncated] = useState(false);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerError, setViewerError] = useState<string | null>(null);

  const refreshTimerRef = useRef<number | null>(null);
  const healthTimerRef = useRef<number | null>(null);
  const [isCollapsed, setIsCollapsed] = useState(true);

  const pathLabel = useMemo(() => {
    const p = normalizePath(path);
    return p || '/';
  }, [path]);

  const fetchList = async (p: string, silent = true) => {
    setLoading(true);
    setError(null);
    try {
      const res = (await api.dailyDataList({ path: p, limit: 60, silent })) as DailyDataListResponse;
      if (res?.status !== 'success' || !Array.isArray(res.items)) {
        setItems([]);
        setError(res?.detail || '无法读取目录');
        return;
      }
      setItems(res.items);
    } catch (e: any) {
      setItems([]);
      setError(e?.message || '无法读取目录');
    } finally {
      setLoading(false);
    }
  };

  const fetchHealth = async (silent = true) => {
    try {
      const res = (await api.getHealth({ silent })) as HealthResponse;
      const svc = res?.services?.active_care_service;
      const st = typeof svc?.status === 'string' ? svc.status : 'unknown';
      if (st === 'healthy') setAcsStatus('healthy');
      else if (st === 'unhealthy' || st === 'error') setAcsStatus('unhealthy');
      else setAcsStatus('unknown');
    } catch {
      setAcsStatus('unknown');
    }
  };

  const openFile = async (p: string) => {
    setViewerOpen(true);
    setViewerPath(p);
    setViewerLoading(true);
    setViewerError(null);
    setViewerContent('');
    setViewerTruncated(false);
    try {
      const res = (await api.dailyDataRead({ path: p, maxChars: 200000, silent: true })) as DailyDataReadResponse;
      if (res?.status !== 'success' || typeof res.content !== 'string') {
        setViewerError(res?.detail || '无法读取文件');
        return;
      }
      setViewerContent(res.content);
      setViewerTruncated(!!res.truncated);
    } catch (e: any) {
      setViewerError(e?.message || '无法读取文件');
    } finally {
      setViewerLoading(false);
    }
  };

  useEffect(() => {
    fetchList(path, true);
    if (refreshTimerRef.current) window.clearInterval(refreshTimerRef.current);
    refreshTimerRef.current = window.setInterval(() => fetchList(path, true), 12000);
    return () => {
      if (refreshTimerRef.current) window.clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    };
  }, [path]);

  useEffect(() => {
    fetchHealth(true);
    if (healthTimerRef.current) window.clearInterval(healthTimerRef.current);
    healthTimerRef.current = window.setInterval(() => fetchHealth(true), 15000);
    return () => {
      if (healthTimerRef.current) window.clearInterval(healthTimerRef.current);
      healthTimerRef.current = null;
    };
  }, []);

  const statusColorClass =
    acsStatus === 'healthy' ? 'bg-emerald-400' : acsStatus === 'unhealthy' ? 'bg-rose-400' : 'bg-white/30';

  const onClickContainer = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  if (!sidebarOpen) {
    return (
      <div
        className="glass-panel flex items-center justify-center p-3 rounded-xl mb-2 hover:bg-white/10 transition-colors"
        onClick={onClickContainer}
        title="Daily Data"
      >
        <div className="relative flex items-center justify-center w-8 h-8 rounded-full bg-white/5">
          <FileText className="text-white/60" size={18} />
          <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black/40">
            <div className={`w-full h-full rounded-full ${statusColorClass}`} />
          </div>
          <div className="absolute inset-0 rounded-full opacity-15 animate-pulse" style={{ backgroundColor: emoConfig.colors[0], filter: 'blur(10px)' }} />
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className={`glass-panel relative flex flex-col gap-2 p-3 rounded-xl transition-all mb-2 hover:bg-white/10 cursor-pointer ${isCollapsed ? 'pb-2' : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          setIsCollapsed(!isCollapsed);
        }}
      >
        <div className="absolute inset-0 rounded-xl opacity-10 pointer-events-none" style={{ backgroundColor: emoConfig.colors[1], filter: 'blur(14px)' }} />

        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="relative flex items-center justify-center w-8 h-8 rounded-full bg-white/5 border border-white/10">
              <FileText size={16} className="text-white/70" />
              <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black/40">
                <div className={`w-full h-full rounded-full ${statusColorClass}`} />
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-white/40 uppercase tracking-widest font-bold">Daily Data</span>
              <span className="text-xs font-mono text-white/70 truncate max-w-[8rem]">{pathLabel}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {!isCollapsed && (
              <button
                className="w-7 h-7 rounded-lg glass-panel flex items-center justify-center hover:bg-white/20 transition-all duration-300 hover:scale-105 active:scale-95"
                onClick={(e) => {
                  e.stopPropagation();
                  fetchList(path, false);
                  fetchHealth(false);
                }}
                title="Refresh"
              >
                <RefreshCw size={12} className={loading ? 'text-white/60 animate-spin' : 'text-white/60'} />
              </button>
            )}
            <ChevronLeft size={14} className={`text-white/30 transition-transform duration-300 ${isCollapsed ? '-rotate-90' : 'rotate-90'}`} />
          </div>
        </div>

        {!isCollapsed && (
          <>
            <div className="relative flex items-center justify-between text-[10px] text-white/40 font-mono">
              <div className="flex items-center gap-2">
                <Activity size={12} className="text-white/30" />
                <span>ACS</span>
                <span className="text-white/50">{acsStatus}</span>
              </div>
              <div className="text-white/40">{loading ? 'sync...' : 'ok'}</div>
            </div>

            {error && <div className="relative text-[10px] text-rose-300/80 font-mono px-1">{error}</div>}

            <div className="glass-panel rounded-lg overflow-hidden">
              <div className="max-h-40 overflow-auto">
                <button
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors ${normalizePath(path) ? 'hover:bg-white/5 text-white/70' : 'text-white/25 cursor-not-allowed'}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!normalizePath(path)) return;
                    setPath(parentPath(path));
                  }}
                  title="Parent"
                >
                  <ChevronLeft size={14} className="text-white/40" />
                  <span className="font-mono">..</span>
                </button>

                {items.map((it) => {
                  const isDir = it.type === 'dir';
                  const full = joinPath(path, it.name);
                  return (
                    <button
                      key={`${it.type}:${it.name}`}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs text-white/80 hover:bg-white/5 transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (isDir) setPath(full);
                        else openFile(full);
                      }}
                      title={it.name}
                    >
                      {isDir ? <Folder size={14} className="text-emerald-300/70" /> : <FileText size={14} className="text-white/50" />}
                      <span className="truncate flex-1">{it.name}</span>
                      {isDir ? (
                        <span className="text-[10px] text-white/30 font-mono">
                          {it.count !== undefined && it.count !== null ? `${it.count} items` : 'DIR'}
                        </span>
                      ) : (
                        <span className="text-[10px] text-white/30 font-mono">
                          {it.size !== undefined && it.size !== null && it.size > 0 ? `${Math.ceil(it.size / 1024)}KB` : (it.ext || 'FILE').toUpperCase()}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {viewerOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => {
            setViewerOpen(false);
            setViewerPath(null);
            setViewerContent('');
            setViewerError(null);
            setViewerTruncated(false);
          }}
        >
          <div
            className="glass-card rounded-2xl p-5 w-[92vw] max-w-3xl shadow-2xl relative overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="absolute inset-0 bg-black/40 -z-10" />
            <div className="flex items-start justify-between gap-4 mb-3">
              <div className="flex flex-col min-w-0">
                <div className="text-[10px] text-white/40 uppercase tracking-widest font-bold text-glow">Daily Data Viewer</div>
                <div className="text-xs font-mono text-white/80 truncate">{viewerPath || ''}</div>
                {viewerTruncated && <div className="text-[10px] text-yellow-300/80 font-mono">内容已截断</div>}
              </div>
              <button
                className="w-9 h-9 rounded-xl glass-panel flex items-center justify-center hover:bg-white/20 transition-all duration-300 hover:scale-105 active:scale-95"
                onClick={() => {
                  setViewerOpen(false);
                  setViewerPath(null);
                  setViewerContent('');
                  setViewerError(null);
                  setViewerTruncated(false);
                }}
                title="Close"
              >
                <X size={16} className="text-white/60" />
              </button>
            </div>

            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="max-h-[65vh] overflow-auto p-4">
                {viewerLoading && <div className="text-xs text-white/50 font-mono">加载中...</div>}
                {viewerError && <div className="text-xs text-rose-300/80 font-mono">{viewerError}</div>}
                {!viewerLoading && !viewerError && (
                  <pre className="text-xs text-white/80 font-mono whitespace-pre-wrap break-words">{viewerContent || '（空文件）'}</pre>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

