import React from 'react';
import { api } from '../api/apiService';
import { Message } from '../types';

interface MemoryPanelProps {
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  onToggleTTS: (id: number) => void;
  onDelete: (id: number) => void;
  storageKey: string;
}

const MemoryPanel = React.memo(({ messages, setMessages, onToggleTTS, onDelete, storageKey }: MemoryPanelProps) => {
  return (
    <div className="flex-1 p-8">
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="flex items-center justify-between">
          <div className="text-white/80 text-sm">聊天记录共 {messages.length} 条</div>
          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                try { await api.clearMemory(); } catch {}
                try { localStorage.removeItem(storageKey); } catch {}
                setMessages([{ id: Date.now(), isUser: false, text: "系统就绪。Aveline 核心已加载。" }]);
              }}
              className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-xs"
            >清空历史</button>
            <button
              onClick={() => {
                try {
                  const data = JSON.stringify(messages);
                  const blob = new Blob([data], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url; a.download = 'aveline_messages.json'; a.click();
                  URL.revokeObjectURL(url);
                } catch {}
              }}
              className="px-3 py-1 rounded-md bg-white text-black text-xs hover:bg-gray-200"
            >导出</button>
          </div>
        </div>
        <div className="space-y-2">
          {messages.map(m => (
            <div key={m.id} className="flex items-center justify-between bg-[#18181b] border border-white/10 rounded-md px-3 py-2">
              <div className="text-xs text-white/80 truncate max-w-[70%]">
                {m.isUser ? '用户' : 'Aveline'}: {m.text}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigator.clipboard && navigator.clipboard.writeText(m.text)}
                  className="px-2 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-[10px]"
                >复制</button>
                <button
                  onClick={() => onDelete(m.id)}
                  className="px-2 py-1 rounded-md bg-red-500/20 hover:bg-red-500/40 text-red-200 text-[10px]"
                >删除</button>
                {!m.isUser && (
                  <button
                    onClick={() => onToggleTTS(m.id)}
                    className="px-2 py-1 rounded-md bg-white text-black text-[10px] hover:bg-gray-200"
                  >播放</button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

export default MemoryPanel;
