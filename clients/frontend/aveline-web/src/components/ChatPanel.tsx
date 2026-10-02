import React, { useRef, useEffect, useMemo } from 'react';
import { Message } from '../types';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';
import { Sparkles } from 'lucide-react';
import { formatChatTime, unwrapRetractionText } from '../utils/text';

interface ChatPanelProps {
  messages: Message[];
  isTyping: boolean;
  showTypingIndicator?: boolean;
  playingMsgId: number | string | null;
  loadingAudio: boolean;
  currentColors: [string, string, string, string];
  replyDisplayMode?: 'text_and_tts' | 'tts_only';
  onToggleTTS: (id: number | string) => void;
  onDelete?: (id: number | string) => void;
  onRegenerate?: (id: number | string) => void;
  onSuggestionClick?: (text: string) => void;
  studyMode?: boolean;
  onLoadMore?: () => Promise<void> | void;
  hasMoreHistory?: boolean;
  isLoadingHistory?: boolean;
  regeneratingMsgId?: number | string | null;
}

const ChatPanel = ({ messages, isTyping, showTypingIndicator, playingMsgId, loadingAudio, currentColors, replyDisplayMode, onToggleTTS, onDelete, onRegenerate, onSuggestionClick, studyMode, onLoadMore, hasMoreHistory, isLoadingHistory, regeneratingMsgId }: ChatPanelProps) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const loadingMoreRef = useRef(false);
  const typingVisible = false; // 禁用 TypingIndicator，因为流式输出已经显示实时文字了
  const renderCenteredNarration = (key: React.Key, text: string) => (
    <div key={key} className="flex items-center justify-center py-4 opacity-80 animate-in fade-in zoom-in-95 duration-500">
      <div className="h-px bg-gradient-to-r from-transparent via-white/20 to-transparent w-16 mx-3"></div>
      <span className="text-[12px] text-white/30 font-light tracking-[0.12em] text-center whitespace-pre-wrap break-words max-w-[70%]">
        {unwrapRetractionText(text)}
      </span>
      <div className="h-px bg-gradient-to-r from-transparent via-white/20 to-transparent w-16 mx-3"></div>
    </div>
  );
  const messageItems = useMemo(() => {
    let prevTs: number | null = null;
    return messages.map((msg) => {
      let ts: number | null = null;
      if (msg.timestamp) {
          ts = msg.timestamp;
      } else if (typeof msg.id === 'number') {
          ts = msg.id;
      } else if (typeof msg.id === 'string') {
          // Handle "timestamp-index" format from segmentation
          const part = msg.id.split('-')[0];
          const parsed = Number(part);
          if (!Number.isNaN(parsed)) ts = parsed;
      }
      
      // Handle legacy/small timestamps
      if (ts !== null && ts < 1e12) ts = ts * 1000;

      // Show time if:
      // 1. It's the first message
      // 2. Time difference > 3 minutes (reduced from 5)
      const showTime = ts !== null && (prevTs === null || ts - prevTs > 3 * 60 * 1000);
      if (ts !== null) prevTs = ts;
        const isNarrationLike =
          msg.messageType === 'retraction' ||
          (!msg.isUser && (msg.text.includes("新话题已开启") || msg.text.includes("系统就绪")));
        return { msg, ts, showTime: isNarrationLike ? false : showTime };
    });
  }, [messages]);
  
  // Check if it's a new topic state (Simplified for Single Session)
  const isNewTopic = messages.length === 0;

  // 添加调试快捷键
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        (window as any).__DEBUG_MESSAGES = !(window as any).__DEBUG_MESSAGES;
        // 强制重新渲染
        window.dispatchEvent(new Event('resize'));
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (!autoScrollRef.current && !lastMsg?.isUser) return;
    bottomRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [messages, isTyping]);

  // Handle keyboard/viewport resize
  useEffect(() => {
    const handleResize = () => {
      // Use 'auto' behavior for instant adjustment when keyboard toggles
      bottomRef.current?.scrollIntoView({ behavior: 'auto' });
    };

    window.addEventListener('resize', handleResize);
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', handleResize);
      window.visualViewport.addEventListener('scroll', handleResize);
    }

    return () => {
      window.removeEventListener('resize', handleResize);
      if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', handleResize);
        window.visualViewport.removeEventListener('scroll', handleResize);
      }
    };
  }, []);

  useEffect(() => {
    const handleKeyboardResize = () => {
      autoScrollRef.current = true;
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'auto' });
      });
    };
    window.addEventListener('keyboard:resize', handleKeyboardResize as EventListener);
    return () => {
      window.removeEventListener('keyboard:resize', handleKeyboardResize as EventListener);
    };
  }, []);

  if (isNewTopic) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-white/50 space-y-8">
            <div className="flex flex-col items-center space-y-4 opacity-50">
                <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center border border-white/10">
                    <Sparkles size={24} className="text-white/60" />
                </div>
                <p className="text-sm font-mono tracking-widest uppercase">Start Chatting</p>
            </div>
        </div>
      );
  }

  return (
    <>
      {/* 调试面板 - 按 Ctrl+Shift+D 切换 */}
      {typeof window !== 'undefined' && (window as any).__DEBUG_MESSAGES && (
        <div style={{
          position: 'fixed',
          top: 0,
          right: 0,
          width: '400px',
          height: '100vh',
          background: 'rgba(0,0,0,0.9)',
          color: 'white',
          padding: '10px',
          overflow: 'auto',
          zIndex: 9999,
          fontSize: '12px',
          fontFamily: 'monospace'
        }}>
          <h3>Debug: Messages ({messages.length})</h3>
          {messages.slice(-10).map((msg, idx) => (
            <div key={idx} style={{
              border: '1px solid #333',
              margin: '5px 0',
              padding: '5px',
              background: msg.text?.trim() ? '#111' : '#500'
            }}>
              <div>ID: {String(msg.id)}</div>
              <div>Text: "{msg.text}" (len: {msg.text?.length || 0})</div>
              <div>Type: {msg.messageType || 'text'}</div>
              <div>IsUser: {msg.isUser ? 'Y' : 'N'}</div>
              {!msg.text?.trim() && !msg.isUser && <div style={{color: 'red'}}>⚠️ EMPTY BUBBLE</div>}
            </div>
          ))}
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={() => {
          const el = scrollRef.current;
          if (!el) return;
        const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
        autoScrollRef.current = distance < 120;
        if (el.scrollTop < 80 && onLoadMore && hasMoreHistory && !isLoadingHistory && !loadingMoreRef.current) {
          loadingMoreRef.current = true;
          const prevHeight = el.scrollHeight;
          const prevTop = el.scrollTop;
          Promise.resolve(onLoadMore()).finally(() => {
            const nextEl = scrollRef.current;
            if (nextEl) {
              const nextHeight = nextEl.scrollHeight;
              nextEl.scrollTop = nextHeight - prevHeight + prevTop;
            }
            loadingMoreRef.current = false;
          });
        }
      }}
      className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent"
    >
       {(isLoadingHistory || hasMoreHistory) && (
         <div className="flex items-center justify-center text-[10px] text-white/40 uppercase tracking-widest">
           {isLoadingHistory ? '加载中...' : '上拉加载更多'}
         </div>
       )}
       {messageItems.map(({ msg, ts, showTime }) => {
         // 过滤掉空气泡
         if (!msg.isUser && !msg.text?.trim() && msg.messageType !== 'retraction' && !msg.imageUrl && !msg.imageBase64 && !msg.audioBase64) {
           console.log(`[ChatPanel] Skipping empty bubble: id=${msg.id}`);
           return null;
         }
         
         // 系统提示改为和动作描写一致的居中显示
         const isSystemMsg = !msg.isUser && (msg.text.includes("新话题已开启") || msg.text.includes("系统就绪"));
         
         if (isSystemMsg) {
             return renderCenteredNarration(msg.id, msg.text);
         }

         return (
         <React.Fragment key={msg.id}>
          {showTime && ts !== null && (
             <div className="flex justify-center mb-6 mt-2">
               <span className="text-[12px] text-white/30 font-light tracking-[0.12em]">
                 {formatChatTime(ts)}
               </span>
             </div>
           )}
           <div className={`flex ${msg.isUser ? 'justify-end' : msg.messageType === 'retraction' ? 'justify-center w-full my-2' : 'justify-start'}`}>
              <MessageBubble 
                message={msg} 
                playingMsgId={playingMsgId} 
                onToggleTTS={onToggleTTS} 
                onDelete={onDelete}
                onRegenerate={onRegenerate}
                colors={currentColors}
                loadingAudio={loadingAudio}
                displayMode={replyDisplayMode}
                timestamp={ts}
                studyMode={studyMode}
                isRegenerating={regeneratingMsgId === msg.id}
              />
           </div>
         </React.Fragment>
       )})}
       {typingVisible && (
         <div className="flex justify-start">
            <TypingIndicator />
         </div>
       )}
       <div ref={bottomRef} />
    </div>
    </>
  );
};

export default ChatPanel;
