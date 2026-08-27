import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Square, Play, Trash2, FileText, ExternalLink, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { cn } from '../utils/common';
import { unwrapRetractionText } from '../utils/text';
import { Message, StudyData } from '../types';
import { getBaseUrl } from '../api/apiService';

const StudyDataView = ({ data }: { data: StudyData }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  
  // 提取高光行内容
  const highlightedContent = React.useMemo(() => {
    if (!data.highlightLines || data.highlightLines.length === 0 || !data.content) return null;
    const lines = data.content.split('\n');
    return data.highlightLines
      .map(lineIdx => {
        // highlightLines 是从1开始的行号
        const content = lines[lineIdx - 1];
        return content !== undefined ? { line: lineIdx, content } : null;
      })
      .filter(item => item !== null) as { line: number; content: string }[];
  }, [data.content, data.highlightLines]);

  // 自动滚动到高光区域 (如果有)
  useEffect(() => {
    if (highlightedContent && highlightedContent.length > 0) {
      // 简单延迟滚动，确保渲染完成
      setTimeout(() => {
         // 这里我们不需要复杂的滚动，因为我们把高光内容置顶显示了
         // 如果需要滚动到全文中的位置，会比较复杂，暂且忽略
      }, 100);
    }
  }, [highlightedContent]);

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-3 overflow-hidden rounded-xl border border-emerald-500/30 bg-emerald-500/5 backdrop-blur-md flex flex-col"
    >
      <div className="flex items-center justify-between px-4 py-2 bg-emerald-500/10 border-b border-emerald-500/20">
        <div className="flex items-center gap-2">
          <FileText size={14} className="text-emerald-400" />
          <span className="text-xs font-medium text-emerald-200 tracking-wide uppercase">{data.title || '学习资料'}</span>
        </div>
        <div className="flex items-center gap-1.5 opacity-50">
          <ExternalLink size={10} className="text-emerald-300" />
          <span className="text-[10px] font-mono text-emerald-300/70">{data.filePath}</span>
        </div>
      </div>

      {/* 高光重点区域 - 置顶显示 */}
      {highlightedContent && highlightedContent.length > 0 && (
        <div className="bg-emerald-500/10 border-b border-emerald-500/20 relative">
           <div className="absolute top-0 left-0 bottom-0 w-1 bg-yellow-400/70 shadow-[0_0_10px_rgba(250,204,21,0.5)]"></div>
           <div className="px-4 py-2">
             <div className="flex items-center gap-2 mb-2">
               <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
               <span className="text-[10px] text-yellow-200/80 font-bold uppercase tracking-wider">重点标记 (Line {data.highlightLines?.join(', ')})</span>
             </div>
             <div className="space-y-1">
               {highlightedContent.map((item, idx) => (
                 <div key={idx} className="flex gap-3 text-sm font-mono text-emerald-100 bg-black/20 p-1.5 rounded border border-emerald-500/10">
                   <span className="text-emerald-500/40 select-none text-[10px] w-6 text-right pt-1">{item.line}</span>
                   <div className="flex-1 overflow-x-auto prose prose-invert prose-sm prose-p:my-0 max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
                        {item.content}
                      </ReactMarkdown>
                   </div>
                 </div>
               ))}
             </div>
           </div>
        </div>
      )}

      {/* 全文内容 */}
      <div 
        ref={containerRef}
        className="p-4 overflow-x-auto max-h-[300px] scrollbar-thin scrollbar-thumb-emerald-500/20 scrollbar-track-transparent bg-black/10"
      >
        <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-headings:text-emerald-100 prose-code:text-emerald-300 opacity-80 hover:opacity-100 transition-opacity">
          <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
            {data.content}
          </ReactMarkdown>
        </div>
      </div>
    </motion.div>
  );
};

const MessageBubble = React.memo(({ 
  message, 
  playingMsgId, 
  onToggleTTS,
  onDelete,
  onRegenerate,
  colors,
  loadingAudio,
  displayMode,
  timestamp,
  studyMode,
  isRegenerating
}: {
  message: Message;
  playingMsgId: number | string | null;
  onToggleTTS: (id: number | string) => void;
  onDelete?: (id: number | string) => void;
  onRegenerate?: (id: number | string) => void;
  colors?: [string, string, string, string];
  loadingAudio?: boolean;
  displayMode?: 'text_and_tts' | 'tts_only';
  timestamp?: number | null;
  studyMode?: boolean;
  isRegenerating?: boolean;
}) => {
  const [displayedText, setDisplayedText] = useState(message.text);
  const [showTTS, setShowTTS] = useState(false);
  const [showTranscription, setShowTranscription] = useState(false);
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (studyMode) {
      setDisplayedText(message.text);
      return;
    }

    const ts = timestamp || (typeof message.id === 'number' ? message.id : parseInt(message.id.toString().split('-')[0]));
    const isNew = (ts && Date.now() - ts < 2000);

    if (isNew && !message.isUser) {
      const speed = 30; // ms per char
      const timer = setInterval(() => {
        setDisplayedText((current) => {
          if (current === message.text) {
            clearInterval(timer);
            return current;
          }
          
          if (message.text.startsWith(current)) {
            return message.text.substring(0, current.length + 1);
          } else {
            clearInterval(timer);
            return message.text;
          }
        });
      }, speed);
      return () => clearInterval(timer);
    } else {
      setDisplayedText(message.text);
    }
  }, [message.id, message.text, message.isUser, message.timestamp, studyMode, timestamp]);

  if (message.messageType === 'retraction') {
    return (
      <div className="flex items-center justify-center py-4 opacity-80 animate-in fade-in zoom-in-95 duration-500 w-full">
        <div className="h-px bg-gradient-to-r from-transparent via-white/20 to-transparent w-16 mx-3"></div>
        <span className="text-[12px] text-white/30 font-light tracking-[0.12em] text-center whitespace-pre-wrap break-words max-w-[70%]">
          {unwrapRetractionText(displayedText)}
        </span>
        <div className="h-px bg-gradient-to-r from-transparent via-white/20 to-transparent w-16 mx-3"></div>
      </div>
    );
  }

  const voiceLike =
    !message.isUser &&
    message.messageType !== 'reaction' &&
    (message.messageType === 'voice' || displayMode === 'tts_only');

  const isStudyAI = studyMode && !message.isUser && message.messageType !== 'reaction';

  return (
    <div 
      className={cn(
        "flex flex-col overflow-hidden transition-all group relative",
        isStudyAI 
          ? "w-full max-w-full bg-transparent border-none shadow-none backdrop-blur-none px-1" 
          : "max-w-[75%] shadow-lg border backdrop-blur-xl",
        message.isUser
          ? "glass-card !bg-white/5 !border-white/10 text-gray-100 rounded-2xl rounded-br-sm hover:!bg-white/10"
          : message.messageType === 'reaction'
            ? "glass-card !bg-purple-900/20 !border-purple-500/20 text-purple-100 rounded-2xl rounded-bl-sm shadow-[0_0_15px_rgba(168,85,247,0.1)]"
            : isStudyAI
              ? "text-gray-100"
              : "glass-card !bg-black/60 !border-white/10 text-gray-200 rounded-2xl rounded-bl-sm shadow-[0_4px_20px_rgba(0,0,0,0.2)]"
      )}
    >
      <div 
        onContextMenu={(e) => {
          if (voiceLike) {
            e.preventDefault();
            setShowTranscription((v) => !v);
          }
        }}
        onTouchStart={() => {
          if (!voiceLike) return;
          if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = setTimeout(() => {
            setShowTranscription((v) => !v);
          }, 550);
        }}
        onTouchEnd={() => {
          if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }}
        onTouchMove={() => {
          if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }}
        onClick={() => {
            if (voiceLike) {
              onToggleTTS(message.id);
              return;
            }
            if (!message.isUser) setShowTTS(!showTTS);
        }}
        className={cn(
          "px-5 py-3 text-[15px] leading-relaxed select-none",
          !message.isUser && "cursor-pointer",
          message.messageType === 'reaction' && "italic"
      )}>
        {voiceLike ? (
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-3 text-white/70">
                    <div className="p-2.5 bg-white/10 rounded-full hover:bg-white/20 transition-colors">
                        {loadingAudio && playingMsgId === message.id ? (
                            <Loader2 size={18} className="animate-spin" />
                        ) : playingMsgId === message.id ? (
                            <Square size={18} fill="currentColor" />
                        ) : (
                            <Play size={18} fill="currentColor" />
                        )}
                    </div>
                    <div className="flex flex-col flex-1">
                        <div className="flex items-center justify-between">
                            <span className="text-sm font-medium italic opacity-80">
                                {playingMsgId === message.id ? (loadingAudio ? '正在加载...' : '正在播放...') : '语音消息'}
                            </span>
                        </div>
                        {/* 模拟音波条 */}
                        <div className="flex items-center gap-[3px] h-6 mt-1 overflow-hidden">
                            {Array.from({ length: 24 }).map((_, i) => (
                                <motion.div
                                    key={i}
                                    className="w-[3px] bg-white/20 rounded-full"
                                    animate={playingMsgId === message.id && !loadingAudio ? { 
                                        height: [6, Math.random() * 16 + 4, 6],
                                        backgroundColor: ["rgba(255,255,255,0.2)", "rgba(255,255,255,0.5)", "rgba(255,255,255,0.2)"]
                                    } : { height: 6 }}
                                    transition={{
                                        duration: 0.6,
                                        repeat: Infinity,
                                        delay: i * 0.05,
                                    }}
                                />
                            ))}
                        </div>
                    </div>
                </div>

                {showTranscription ? (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="mt-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-xs text-white/70 leading-relaxed select-text"
                  >
                    {displayedText || '（无文字内容）'}
                  </motion.div>
                ) : null}
            </div>
        ) : (
            <div className={cn(
                "prose prose-invert max-w-none break-words",
                isStudyAI 
                  ? "prose-p:leading-7 prose-headings:font-bold prose-headings:text-white prose-headings:mb-3 prose-headings:mt-6 prose-strong:text-white prose-ul:my-4 prose-li:my-1" 
                  : "prose-p:my-1 prose-pre:bg-gray-800 prose-pre:p-2 prose-pre:rounded-lg prose-code:text-pink-300 prose-headings:text-gray-100 prose-a:text-blue-400"
            )}>
                <ReactMarkdown 
                    remarkPlugins={[remarkMath, remarkGfm]} 
                    rehypePlugins={[rehypeKatex]}
                >
                    {displayedText}
                </ReactMarkdown>
            </div>
        )}
        {message.imageStatus === 'generating' && !message.imageUrl && !message.imageBase64 ? (
            <div className="mt-3 flex items-center gap-2 text-white/60 text-sm">
                <Loader2 size={16} className="animate-spin" />
                <span>图片生成中...</span>
            </div>
        ) : null}
        {message.imageStatus === 'error' && message.imageError ? (
            <div className="mt-3 text-sm text-red-200/80">
                {message.imageError}
            </div>
        ) : null}
        {message.imageUrl ? (
             <img 
                src={message.imageUrl.startsWith('http') || message.imageUrl.startsWith('data:') || message.imageUrl.startsWith('blob:') ? message.imageUrl : `${getBaseUrl()}${message.imageUrl.startsWith('/') ? '' : '/'}${message.imageUrl}`} 
                alt="generated" 
                className="mt-3 rounded-lg max-w-full shadow-md" 
             />
        ) : message.imageBase64 ? (
             <img src={message.imageBase64} alt="generated" className="mt-3 rounded-lg max-w-full shadow-md" />
        ) : null}
        {message.studyData && <StudyDataView data={message.studyData} />}
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

      {!message.isUser && !showTTS && onRegenerate && (
        <div className="absolute bottom-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          <button 
            onClick={() => onRegenerate(message.id)}
            disabled={isRegenerating}
            className={cn(
              "p-1.5 rounded-full backdrop-blur-sm transition-all flex-shrink-0",
              isRegenerating 
                ? "bg-white/5 text-white/30 cursor-not-allowed" 
                : "bg-black/40 hover:bg-blue-500/20 text-white/50 hover:text-blue-200"
            )}
            aria-label="重新生成"
            title="重新生成"
          >
            <RefreshCw size={10} className={isRegenerating ? "animate-spin" : ""} />
          </button>
          {onDelete && (
            <button 
              onClick={() => onDelete(message.id)}
              className="p-1.5 rounded-full bg-black/40 backdrop-blur-sm hover:bg-red-500/20 text-white/50 hover:text-red-200 transition-all flex-shrink-0"
              aria-label="删除消息"
              title="删除消息"
            >
              <Trash2 size={10} />
            </button>
          )}
        </div>
      )}
    </div>
  );
});

MessageBubble.displayName = 'MessageBubble';

export default MessageBubble;
