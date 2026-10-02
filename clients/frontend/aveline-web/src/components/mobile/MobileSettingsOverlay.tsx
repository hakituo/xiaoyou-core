import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, Save, Trash2 } from 'lucide-react';
import { CustomSelect } from '../ui/CustomSelect';

type MobileSettingsOverlayProps = {
  show: boolean;
  serverUrl: string;
  onServerUrlChange: (value: string) => void;
  onClose: () => void;
  onSaveUrl: () => void;
  onTestConnection: () => void;
  testStatus: 'idle' | 'testing' | 'success' | 'error';
  hasNative: boolean;
  residentEnabled: boolean;
  onToggleResident: () => void;
  onOpenNativeSettings: () => void;
  onOpenUsageSettings: () => void;
  onOpenNotificationSettings: () => void;
  onRequestHealthPermissions: () => void;
  voices: any[];
  selectedVoiceId: string;
  onVoiceChange: (value: string) => void;
  responseLength: string;
  onResponseLengthChange: (value: string) => void;
  onClearHistory: () => void;
  triggerHaptic: () => void;
};

export function MobileSettingsOverlay({
  show,
  serverUrl,
  onServerUrlChange,
  onClose,
  onSaveUrl,
  onTestConnection,
  testStatus,
  hasNative,
  residentEnabled,
  onToggleResident,
  onOpenNativeSettings,
  onOpenUsageSettings,
  onOpenNotificationSettings,
  onRequestHealthPermissions,
  voices,
  selectedVoiceId,
  onVoiceChange,
  responseLength,
  onResponseLengthChange,
  onClearHistory,
  triggerHaptic,
}: MobileSettingsOverlayProps) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="absolute inset-0 z-[100] bg-zinc-950/98 backdrop-blur-xl flex flex-col"
        >
          <div className="flex items-center px-4 pb-4 pt-[calc(env(safe-area-inset-top)+16px)] border-b border-white/5">
            <button onClick={() => { onClose(); triggerHaptic(); }} className="p-2 -ml-2 hover:bg-white/5 rounded-full text-white/40">
              <ArrowLeft size={24} />
            </button>
            <h2 className="ml-2 font-bold text-lg">System Settings</h2>
          </div>
          <div className="p-6 space-y-8 overflow-y-auto flex-1">
            <div className="space-y-3">
              <label className="text-[10px] text-emerald-500/60 uppercase font-bold tracking-[0.2em]">Server Connection</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={serverUrl}
                  onChange={(e) => onServerUrlChange(e.target.value)}
                  className="flex-1 bg-white/5 border border-white/10 rounded-2xl p-4 text-sm outline-none focus:border-emerald-500/30 focus:bg-white/10 transition-all placeholder-white/20"
                  placeholder="http://192.168.1.X:8000"
                />
                <button onClick={onSaveUrl} className="p-4 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-2xl hover:bg-emerald-500/20 transition-all active:scale-95">
                  <Save size={20} />
                </button>
              </div>
              <button
                onClick={onTestConnection}
                disabled={testStatus === 'testing'}
                className={`w-full py-3 rounded-2xl text-xs font-medium transition-all border ${
                  testStatus === 'success'
                    ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                    : testStatus === 'error'
                    ? 'bg-rose-500/10 border-rose-500/20 text-rose-300'
                    : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10'
                }`}
              >
                {testStatus === 'testing'
                  ? '测试中...'
                  : testStatus === 'success'
                  ? '连接成功'
                  : testStatus === 'error'
                  ? '连接失败'
                  : '测试连接'}
              </button>
              <p className="text-xs text-white/30 px-1">
                注意：请使用电脑的局域网 IP (如 192.168.x.x)，并确保防火墙允许 8000 端口。
              </p>

              {hasNative && (
                <div className="space-y-3">
                  <label className="text-[10px] text-emerald-500/60 uppercase font-bold tracking-[0.2em]">Device Capabilities</label>
                  <button
                    onClick={onOpenNativeSettings}
                    className="w-full py-4 bg-white/5 border border-white/10 rounded-2xl text-sm font-medium hover:bg-white/10 transition-colors"
                  >
                    打开系统权限与自检 (App Info)
                  </button>
                  <button
                    onClick={onOpenUsageSettings}
                    className="w-full py-4 bg-white/5 border border-white/10 rounded-2xl text-sm font-medium hover:bg-white/10 transition-colors"
                  >
                    授予应用使用情况权限 (Usage Access)
                  </button>
                  <button
                    onClick={onOpenNotificationSettings}
                    className="w-full py-4 bg-white/5 border border-white/10 rounded-2xl text-sm font-medium hover:bg-white/10 transition-colors"
                  >
                    授予通知读取权限 (Notification Access)
                  </button>
                  <button
                    onClick={onRequestHealthPermissions}
                    className="w-full py-4 bg-white/5 border border-white/10 rounded-2xl text-sm font-medium hover:bg-white/10 transition-colors"
                  >
                    连接健康数据 (Health Connect)
                  </button>
                  <button
                    onClick={onToggleResident}
                    className={`w-full py-4 rounded-2xl text-sm font-medium transition-colors border ${residentEnabled ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/15' : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10'}`}
                  >
                    {residentEnabled ? '后台常驻：已开启（点击关闭）' : '后台常驻：未开启（点击开启）'}
                  </button>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <label className="text-[10px] text-emerald-500/60 uppercase font-bold tracking-[0.2em]">Voice Synthesis</label>
              <div className="relative">
                <CustomSelect
                  value={selectedVoiceId}
                  onChange={onVoiceChange}
                  options={voices.map(v => ({ value: v.id, label: v.name }))}
                  placeholder="Select Voice"
                  className="w-full"
                />
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-[10px] text-emerald-500/60 uppercase font-bold tracking-[0.2em]">Interaction Style</label>
              <div className="flex bg-white/5 rounded-2xl p-1.5 border border-white/10">
                {['short', 'normal', 'long'].map((len) => (
                  <button
                    key={len}
                    onClick={() => { onResponseLengthChange(len); triggerHaptic(); }}
                    className={`flex-1 py-3 text-xs rounded-xl capitalize font-medium transition-all ${
                      responseLength === len
                      ? 'bg-white/10 text-emerald-400 shadow-lg'
                      : 'text-white/30 hover:text-white/60'
                    }`}
                  >
                    {len}
                  </button>
                ))}
              </div>
            </div>

            <div className="pt-6 border-t border-white/5">
              <button
                onClick={() => { onClearHistory(); triggerHaptic(); }}
                className="w-full py-4 text-rose-400 bg-rose-500/5 border border-rose-500/10 rounded-2xl text-sm font-medium hover:bg-rose-500/10 transition-colors flex items-center justify-center gap-2 active:scale-98"
              >
                <Trash2 size={18} />
                Wipe All Memories
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
