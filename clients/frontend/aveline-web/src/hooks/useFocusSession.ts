// 专注会话状态管理 hook（前端只负责体验与上报，计时以后端为准）。
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/apiService';
import type { FocusSession, Observation } from '../types/focusSession';

const HEARTBEAT_MS = 15000;      // 心跳/观察批上报周期
const POLL_MS = 5000;            // 拉取当前状态周期（用于倒计时重算）

export function useFocusSession() {
  const [session, setSession] = useState<FocusSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const obsBufferRef = useRef<Observation[]>([]);
  const heartbeatRef = useRef<number | null>(null);
  const pollRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  // 用 ref 镜像最新会话状态，供卸载时判断是否需要暂停（避免把 pause 放进 effect deps 导致每次渲染都触发）
  const sessionRef = useRef<FocusSession | null>(null);
  const pauseRef = useRef<() => Promise<void>>(async () => {});

  // 倒计时重算：始终基于后端 started_at / accumulated / last_resume_at
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const flushObservations = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id || obsBufferRef.current.length === 0) return;
    const batch = obsBufferRef.current.splice(0, obsBufferRef.current.length);
    try {
      await api.focusObservations(id, batch, { silent: true });
    } catch (e) {
      // 上报失败则放回 buffer 末尾（最多保留 200 条，避免无限增长）
      obsBufferRef.current = [...obsBufferRef.current, ...batch].slice(-200);
    }
  }, []);

  const refreshCurrent = useCallback(async () => {
    try {
      const res = await api.focusCurrent({ silent: true });
      if (res?.data) {
        setSession(res.data);
        sessionIdRef.current = res.data.session_id;
      } else {
        setSession(null);
        sessionIdRef.current = null;
      }
    } catch (e) {
      /* 网络抖动忽略，下一轮重试 */
    }
  }, []);

  // 启动心跳 + 周期拉取（抽出来复用，避免重复建 interval）
  const startTimers = useCallback(() => {
    if (heartbeatRef.current == null) {
      heartbeatRef.current = window.setInterval(flushObservations, HEARTBEAT_MS);
    }
    if (pollRef.current == null) {
      pollRef.current = window.setInterval(refreshCurrent, POLL_MS);
    }
  }, [flushObservations, refreshCurrent]);

  const startSession = useCallback(
    async (payload: { subject: string; planned_minutes: number; mode: string; monitoring: boolean }) => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.focusStart(payload);
        const sess: FocusSession = res.data;
        setSession(sess);
        sessionIdRef.current = sess.session_id;
        startTimers();
        return sess;
      } catch (e: any) {
        // 409：该用户已存在 active/paused 会话（如刷新后残留）→ 直接复用并展示，
        // 不自动恢复，让用户显式选择「恢复/结束」，避免"以为开了新的却仍在计旧会话"。
        if (e?.response?.status === 409) {
          try {
            const cur = await api.focusCurrent({ silent: true });
            if (cur?.data) {
              const existing: FocusSession = cur.data;
              setSession(existing);
              sessionIdRef.current = existing.session_id;
              startTimers();
              return existing;
            }
          } catch {
            /* 兜底失败则落到下方错误提示 */
          }
        }
        setError(e?.response?.data?.message || e?.message || '开始会话失败');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [flushObservations, refreshCurrent, startTimers],
  );

  const pause = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    await flushObservations();
    const res = await api.focusPause(id);
    setSession(res.data);
  }, [flushObservations]);

  const resume = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    const res = await api.focusResume(id);
    setSession(res.data);
  }, []);

  const finish = useCallback(
    async (payload?: { self_rating?: number; note?: string }) => {
      const id = sessionIdRef.current;
      if (!id) return null;
      await flushObservations();
      const res = await api.focusFinish(id, payload);
      const summary = res.data;
      setSession(null);
      sessionIdRef.current = null;
      stopTimers();
      return summary;
    },
    [flushObservations],
  );

  const requestNudge = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    const res = await api.focusNudge(id);
    return res?.data;
  }, []);

  const stopTimers = useCallback(() => {
    if (heartbeatRef.current != null) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    if (pollRef.current != null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // 收集来自摄像头的观察
  const pushObservation = useCallback((obs: Observation) => {
    obsBufferRef.current.push(obs);
    if (obsBufferRef.current.length >= 5) {
      flushObservations();
    }
  }, [flushObservations]);

  // 每次渲染同步最新会话状态到 ref（供卸载判断用）
  useEffect(() => {
    sessionRef.current = session;
    pauseRef.current = pause;
  });

  // 离开专注会话（切走 Study 标签页 / 关闭面板）：若仍在 active，则暂停后端会话，
  // 避免"退出后还在后台计时"。已 paused/finished 的不重复操作。
  useEffect(() => {
    return () => {
      if (sessionRef.current && sessionRef.current.status === 'active') {
        pauseRef.current();
      }
      stopTimers();
    };
  }, [stopTimers]);

  // 派生：剩余/已过秒数（基于后端时间戳重算）
  const nowSec = Math.floor(Date.now() / 1000) + tick;
  let elapsed = 0;
  let remaining = 0;
  if (session) {
    const planned = session.planned_minutes * 60;
    if (session.status === 'active' && session.last_resume_at > 0) {
      elapsed = session.accumulated_active_seconds + Math.max(0, nowSec - session.last_resume_at);
    } else {
      elapsed = session.accumulated_active_seconds;
    }
    remaining = Math.max(0, planned - elapsed);
  }

  const focusRate = session
    ? (session.sec_focused / Math.max(1, session.sec_focused + session.sec_possibly_distracted + session.sec_away)) * 100
    : 0;

  return {
    session,
    loading,
    error,
    startSession,
    pause,
    resume,
    finish,
    requestNudge,
    pushObservation,
    refreshCurrent,
    elapsedSec: Math.floor(elapsed),
    remainingSec: Math.floor(remaining),
    focusRate,
  };
}
