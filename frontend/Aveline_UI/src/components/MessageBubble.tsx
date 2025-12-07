import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Square, Play, Trash2 } from 'lucide-react';
import { cn } from '../utils/common';
import { Message } from '../types';

const MessageBubble = React.memo(({ 
  message, 
  playingMsgId, 
  onToggleTTS,
  onDelete,
  colors,
  loadingAudio
}: {
  message: Message;
  playingMsgId: number | null;
  onToggleTTS: (id: number) => void;
  onDelete?: (id: number) => void;
  colors?: [string, string, string, string];
  loadingAudio?: boolean;
}) => {
  const [displayedText, setDisplayedText] = useState(message.text);

  useEffect(() => {
    // Simple heuristic: if message is newer than 2 seconds, animate it.
    // Otherwise show instantly (handles page reloads/history).
    const isNew = Date.now() - message.id < 2000;
    
    if (isNew && !message.isUser) {
      setDisplayedText('');
      let i = 0;
      const speed = 30; // ms per char
      const timer = setInterval(() => {
        if (i < message.text.length) {
          setDisplayedText(message.text.substring(0, i + 1));
          i++;
        } else {
          clearInterval(timer);
        }
      }, speed);
      return () => clearInterval(timer);
    } else {
      setDisplayedText(message.text);
    }
  }, [message.id, message.text, message.isUser]);

  return (
    <div 
      className={cn(
        "max-w-[75%] shadow-lg border backdrop-blur-xl flex flex-col overflow-hidden transition-all group",
        message.isUser
          ? "bg-white/10 border-white/10 text-white rounded-[24px] rounded-br-sm"
          : message.messageType === 'reaction'
            ? "bg-purple-900/30 border-purple-500/30 text-purple-100 rounded-[24px] rounded-bl-sm"
            : "bg-[#18181b]/80 border-white/5 text-gray-200 rounded-[24px] rounded-bl-sm"
      )}
    >
      <div className={cn(
        "p-5 text-[15px] leading-relaxed whitespace-pre-wrap",
        message.messageType === 'reaction' && "italic"
      )}>
        {displayedText}
        {message.imageBase64 && (<img src={message.imageBase64} alt="generated" className="mt-3 rounded-lg max-w-full" />)}
      </div>

      {message.isUser && onDelete && (
         <div className="px-3 py-1 flex justify-end opacity-0 group-hover:opacity-50 hover:!opacity-100 transition-opacity border-t border-white/5">
            <button 
                onClick={() => onDelete(message.id)}
                className="p-1 rounded-full hover:bg-white/20 text-white/70"
                aria-label="删除消息"
            >
                <Trash2 size={12} />
            </button>
         </div>
      )}

      {!message.isUser && (
        <div 
          className="px-5 py-3 bg-black/20 border-t border-white/5 flex items-center gap-3"
          style={{ borderLeft: `2px solid ${colors ? colors[0] : 'transparent'}` }}
        >
          <button 
            onClick={() => onToggleTTS(message.id)}
            className="p-1.5 rounded-full bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition-all flex-shrink-0"
            aria-label={playingMsgId === message.id ? "停止播放" : "播放语音"}
          >
            {loadingAudio && playingMsgId === message.id ? (
              <Loader2 size={12} className="animate-spin" />
            ) : playingMsgId === message.id && !loadingAudio ? (
              <Square size={12} fill="currentColor" />
            ) : (
              <Play size={12} fill="currentColor" />
            )}
          </button>

          <div className="flex-1 h-4 flex items-center gap-[2px] opacity-50">
            {loadingAudio && playingMsgId === message.id ? (
              <Loader2 size={14} className="animate-spin" />
            ) : playingMsgId === message.id && !loadingAudio ? (
              // 播放时的动态声音波
              Array.from({ length: 12 }).map((_, i) => (
                <motion.div
                  key={i}
                  className="w-[2px] bg-current rounded-full"
                  animate={{ height: [4, 12, 4] }}
                  transition={{
                      duration: 0.5,
                      repeat: Infinity,
                      delay: i * 0.1,
                      ease: "easeInOut"
                  }}
                />
              ))
            ) : (
              // 静止时的优雅直线
              Array.from({ length: 12 }).map((_, i) => (
                <div
                  key={i}
                  className="w-[2px] h-[2px] bg-current rounded-full"
                />
              ))
            )}
          </div>

          {onDelete && (
             <button 
                onClick={() => onDelete(message.id)}
                className="p-1.5 rounded-full bg-white/5 hover:bg-red-500/20 text-white/40 hover:text-red-200 transition-all flex-shrink-0"
                aria-label="删除消息"
             >
                <Trash2 size={12} />
             </button>
          )}
        </div>
      )}
    </div>
  );
});

MessageBubble.displayName = 'MessageBubble';

export default MessageBubble;
