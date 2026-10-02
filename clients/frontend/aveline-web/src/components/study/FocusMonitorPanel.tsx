// 专注番茄钟监控面板（阶段2 MVP）
// 组合 useFocusSession（后端权威会话） + useCameraMonitor（端侧 MediaPipe 检测）。
// 隐私：原始画面不保存、不上传；仅结构化观察经心跳上报。
import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Camera, CameraOff, Play, Pause, Square, ShieldCheck, Eye, AlertTriangle, Clock, Brain, RefreshCw } from 'lucide-react';
import { useFocusSession } from '../../hooks/useFocusSession';
import { useCameraMonitor } from '../../hooks/useCameraMonitor';
import type { FocusMode } from '../../types/focusSession';

function fmt(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

const STATUS_LABEL: Record<string, string> = {
  present: '在镜头内',
  away: '离开了',
  camera_blocked: '镜头遮挡',
  unknown: '信号弱',
};
const ACTIVITY_LABEL: Record<string, string> = {
  focused: '专注中',
  possibly_distracted: '可能走神',
  unknown: '—',
};

export const FocusMonitorPanel: React.FC = () => {
  const fs = useFocusSession();
  const [subject, setSubject] = useState('');
  const [planned, setPlanned] = useState(25);
  const [mode, setMode] = useState<FocusMode>('gentle');
  const [muted, setMuted] = useState(false);

  // 挂载时先拉取当前会话：若已有 active/paused 会话（如刷新后残留），直接复用而非新建
  useEffect(() => {
    fs.refreshCurrent();
  }, [fs.refreshCurrent]);

  // 摄像头监控接入：把端侧观察喂给会话 hook
  const cam = useCameraMonitor({
    enabled: !!fs.session && fs.session.monitoring,
    onObservation: (obs) => fs.pushObservation(obs),
    onError: (msg) => console.warn('[camera]', msg),
  });

  // 静音状态同步到后端（通过 reminders_muted 字段；这里本地先存，结束/暂停时无需额外接口，由前端静音开关控制是否调用 requestNudge）
  useEffect(() => {
    if (fs.session) {
      fs.session.reminders_muted = muted;
    }
  }, [muted, fs.session]);

  const handleStart = async () => {
    const sess = await fs.startSession({
      subject: subject.trim() || '未命名学习任务',
      planned_minutes: planned,
      mode,
      monitoring: true,
    });
    // 会话创建成功后自动开启摄像头监控（用户首次需授权浏览器权限）
    if (sess && sess.monitoring) {
      await cam.start();
    }
  };

  const handlePause = async () => {
    cam.stop();
    await fs.pause();
  };

  const handleResume = async () => {
    await fs.resume();
    if (fs.session?.monitoring) cam.start();
  };

  const handleFinish = async () => {
    cam.stop();
    await fs.finish();
  };

  const handleNudge = async () => {
    if (muted) return;
    await fs.requestNudge();
  };

  // ---- 未开始：配置页 ----
  if (!fs.session) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 overflow-y-auto custom-scrollbar">
        <div className="w-full max-w-md glass-card rounded-2xl p-6 space-y-4 border border-emerald-500/20">
          <h2 className="text-xl font-bold text-white/90 flex items-center gap-2">
            <Brain size={20} className="text-emerald-400" /> 专注番茄钟
          </h2>
          <p className="text-xs text-white/50">
            开启摄像头后，浏览器会在本地检测你是否在座位、是否走神。原始画面不会保存或上传，仅上报结构化状态。
          </p>
          <label className="block text-xs text-white/60">学习事项</label>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="例如：复习高等数学第3章"
            className="w-full bg-white/5 rounded-lg px-3 py-2 text-sm text-white/90 outline-none border border-white/10 focus:border-emerald-500/40"
          />
          <div className="flex items-center gap-3">
            <label className="text-xs text-white/60">计划时长</label>
            <input
              type="number"
              min={1}
              max={240}
              value={planned}
              onChange={(e) => setPlanned(Math.max(1, Number(e.target.value) || 25))}
              className="w-20 bg-white/5 rounded-lg px-2 py-1 text-sm text-white/90 outline-none border border-white/10"
            />
            <span className="text-xs text-white/40">分钟</span>
          </div>
          <div className="flex gap-2">
            {(['gentle', 'strict'] as FocusMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium border transition ${
                  mode === m
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                    : 'bg-white/5 text-white/60 border-transparent'
                }`}
              >
                {m === 'gentle' ? '温柔陪伴' : '严格督学'}
              </button>
            ))}
          </div>
          <button
            onClick={handleStart}
            disabled={fs.loading}
            className="w-full py-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-white font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Play size={18} /> {fs.loading ? '启动中…' : '开始学习'}
          </button>
          <button
            onClick={() => fs.refreshCurrent()}
            className="w-full py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 border border-white/10 flex items-center justify-center gap-2"
          >
            <RefreshCw size={15} /> 我之前有未结束的会话？恢复上次
          </button>
          {fs.error && <p className="text-xs text-red-400">{fs.error}</p>}
          <div className="flex items-center gap-1.5 text-[11px] text-white/40">
            <ShieldCheck size={13} /> 原始画面不上传、不保存；仅本地检测 + 结构化状态上报。
          </div>
        </div>
      </div>
    );
  }

  // ---- 进行中 / 暂停：监控页 ----
  const sess = fs.session;
  const isActive = sess.status === 'active';
  const indicatorColor = sess.last_presence === 'present'
    ? 'bg-emerald-500'
    : sess.last_presence === 'away'
    ? 'bg-red-500'
    : 'bg-amber-500';

  return (
    <div className="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto custom-scrollbar">
      {/* 状态条 */}
      <div className="glass-card rounded-xl p-4 border border-white/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-3 h-3 rounded-full ${indicatorColor} ${isActive ? 'animate-pulse' : ''}`} />
            <span className="text-sm text-white/80">{sess.subject}</span>
          </div>
          <span className="text-xs text-white/40">
            {isActive ? '专注中' : sess.status === 'paused' ? '已暂停' : sess.status}
          </span>
        </div>
        <div className="mt-3 flex gap-6">
          <div>
            <div className="text-2xl font-bold text-white/90 tabular-nums">{fmt(fs.remainingSec)}</div>
            <div className="text-[11px] text-white/40">剩余</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-emerald-300 tabular-nums">{fmt(fs.elapsedSec)}</div>
            <div className="text-[11px] text-white/40">已专注</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-white/90 tabular-nums">{fs.focusRate.toFixed(0)}%</div>
            <div className="text-[11px] text-white/40">专注率</div>
          </div>
        </div>
        {/* 摄像头预览 */}
        <div className="mt-3 relative rounded-lg overflow-hidden bg-black/40 aspect-video">
          <video ref={cam.videoRef} className="w-full h-full object-cover scale-x-[-1]" muted playsInline />
          <div className="absolute top-2 right-2 flex items-center gap-1 bg-black/50 rounded-full px-2 py-1">
            <span className={`w-2 h-2 rounded-full ${cam.previewOn ? 'bg-red-500 animate-pulse' : 'bg-white/30'}`} />
            <span className="text-[10px] text-white/80">{cam.previewOn ? '监控中' : '未开启'}</span>
          </div>
          {!cam.previewOn && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-white/40 gap-2">
              {cam.permission === 'denied' || cam.permission === 'inuse' ? (
                <>
                  <CameraOff size={28} />
                  <span className="text-xs">{cam.error || '摄像头不可用'}</span>
                </>
              ) : (
                <>
                  <Camera size={28} />
                  <span className="text-xs">摄像头未开启（仍可计时）</span>
                  <span className="text-[10px] text-white/40">点击下方「开启摄像头」授权</span>
                </>
              )}
            </div>
          )}
        </div>
        {/* 当前观察 */}
        <div className="mt-2 flex items-center gap-2 text-xs text-white/60">
          <Eye size={13} />
          <span>{STATUS_LABEL[sess.last_presence] || sess.last_presence}</span>
          <span className="text-white/30">·</span>
          <span>{ACTIVITY_LABEL[sess.last_activity] || sess.last_activity}</span>
          {sess.last_confidence > 0 && (
            <span className="text-white/30">· 置信度 {sess.last_confidence.toFixed(2)}</span>
          )}
        </div>
      </div>

      {/* 控制按钮 */}
      <div className="flex gap-2 flex-wrap">
        {isActive ? (
          <button onClick={handlePause} className="flex-1 min-w-[80px] py-2.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center justify-center gap-2">
            <Pause size={16} /> 暂停
          </button>
        ) : sess.status === 'paused' ? (
          <button onClick={handleResume} className="flex-1 min-w-[80px] py-2.5 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center justify-center gap-2">
            <Play size={16} /> 恢复
          </button>
        ) : null}
        {!cam.previewOn && (
          <button onClick={() => cam.start()} className="flex-1 min-w-[80px] py-2.5 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-500/30 flex items-center justify-center gap-2">
            <Camera size={16} /> 开启摄像头
          </button>
        )}
        <button onClick={handleNudge} disabled={muted} className="flex-1 min-w-[80px] py-2.5 rounded-lg bg-white/5 text-white/70 border border-white/10 flex items-center justify-center gap-2 disabled:opacity-40">
          <AlertTriangle size={16} /> 让我探个班
        </button>
        <button onClick={handleFinish} className="flex-1 min-w-[80px] py-2.5 rounded-lg bg-red-500/20 text-red-300 border border-red-500/30 flex items-center justify-center gap-2">
          <Square size={16} /> 结束
        </button>
      </div>

      {/* 静音提醒 */}
      <button
        onClick={() => setMuted((m) => !m)}
        className="text-xs text-white/50 hover:text-white/80 self-start flex items-center gap-1"
      >
        <Clock size={13} /> {muted ? '已关闭陪伴消息' : '陪伴消息开启中（点此关闭）'}
      </button>

      <div className="flex items-center gap-1.5 text-[11px] text-white/40">
        <ShieldCheck size={13} /> 原始画面不上传、不保存；离开/走神仅由本地模型判断，误判不追责。
      </div>
    </div>
  );
};
