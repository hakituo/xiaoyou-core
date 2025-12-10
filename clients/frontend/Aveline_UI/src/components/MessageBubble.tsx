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
  const [showTTS, setShowTTS] = useState(false);

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
        "max-w-[75%] shadow-lg border backdrop-blur-xl flex flex-col overflow-hidden transition-all group relative",
        message.isUser
          ? "bg-[#18181b]/60 border-white/5 text-gray-100 rounded-2xl rounded-br-sm"
          : message.messageType === 'reaction'
            ? "bg-purple-900/30 border-purple-500/30 text-purple-100 rounded-2xl rounded-bl-sm"
            : "bg-[#18181b]/80 border-white/5 text-gray-200 rounded-2xl rounded-bl-sm"
      )}
    >
      <div 
        onClick={() => {
            if (message.messageType === 'voice' && !message.isUser) {
                onToggleTTS(message.id);
            } else if (!message.isUser) {
                setShowTTS(!showTTS);
            }
        }}
        className={cn(
          "px-5 py-3 text-[15px] leading-relaxed whitespace-pre-wrap",
          !message.isUser && "cursor-pointer",
          message.messageType === 'reaction' && "italic"
      )}>
        {message.messageType === 'voice' && !message.isUser ? (
            <div className="flex items-center gap-2 text-white/70">
                <div className="p-2 bg-white/10 rounded-full">
                     {loadingAudio && playingMsgId === message.id ? (
                        <Loader2 size={16} className="animate-spin" />
                     ) : playingMsgId === message.id ? (
                        <Square size={16} fill="currentColor" />
                     ) : (
                        <Play size={16} fill="currentColor" />
                     )}
                </div>
                <div className="flex flex-col">
                    <span className="text-sm font-medium italic">Voice Message {playingMsgId === message.id ? '(Playing)' : '(Click to play)'}</span>
                    {/* Show text only when playing or if already played (simple implementation: just show if playing) 
                        User requirement: "必须得播放音频才知道他说的什么" -> imply showing text while playing is acceptable or maybe preferred for accessibility?
                        Or maybe strictly hidden. The prompt says "content hidden UNTIL playback". 
                        So let's reveal it if it is playing or has been played. 
                        For now, let's just show it if playingMsgId === message.id. 
                    */}
                    {(playingMsgId === message.id) && (
                         <span className="text-xs text-white/50 mt-1 animate-in fade-in">{displayedText}</span>
                    )}
                </div>
            </div>
        ) : (
            displayedText
        )}
        {message.imageBase64 && (<img src={message.imageBase64} alt="generated" className="mt-3 rounded-lg max-w-full" />)}
      </div>

      {message.isUser && onDelete && (
         <div className="absolute bottom-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button 
                onClick={() => onDelete(message.id)}
                className="p-1 rounded-full bg-black/40 backdrop-blur-sm hover:bg-white/20 text-white/70"
                aria-label="删除消息"
            >
                <Trash2 size={10} />
            </button>
         </div>
      )}

      {!message.isUser && showTTS && (
        <div 
          className="px-4 py-2 bg-black/20 border-t border-white/5 flex items-center gap-3"
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
