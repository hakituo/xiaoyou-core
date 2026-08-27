// 专注番茄钟会话类型定义（与后端 observation schema 对齐）

export type PresenceState = 'present' | 'away' | 'camera_blocked' | 'unknown';
export type ActivityState = 'focused' | 'possibly_distracted' | 'unknown';
export type SessionStatus = 'created' | 'active' | 'paused' | 'finished';
export type FocusMode = 'gentle' | 'strict';

// 前端端侧检测产出的单条观察（不上传任何图片/音频）
export interface Observation {
  sequence: number;
  observed_at: number;        // 该帧被观察到的 unix 秒（本地时钟）
  presence: PresenceState;
  activity: ActivityState;
  confidence: number;         // 0~1
  signals: string[];          // e.g. ['head_away','phone_visible']
  page_visible: boolean;      // 标签页是否可见
  client_ts: number;
}

export interface FocusSession {
  session_id: string;
  user_id: string;
  subject: string;
  planned_minutes: number;
  mode: FocusMode;
  monitoring: boolean;
  created_at: number;
  started_at: number;
  finished_at: number;
  status: SessionStatus;
  reminders_muted: boolean;
  accumulated_active_seconds: number;
  last_resume_at: number;
  paused_at: number;
  sec_focused: number;
  sec_possibly_distracted: number;
  sec_away: number;
  sec_unknown: number;
  interruption_count: number;
  longest_focus_streak_sec: number;
  nudge_events: Array<{ at: number; reason: string; mode: string; message: string; recovered?: boolean | null }>;
  observations: Observation[];
  last_presence: PresenceState;
  last_activity: ActivityState;
  last_confidence: number;
  last_observed_at: number;
  self_rating?: number | null;
  note?: string | null;
  summary_text?: string | null;
  _summary_metrics?: Record<string, number>;
}

export interface FocusSummary extends FocusSession {}
export interface FocusHistoryItem extends FocusSession {}
