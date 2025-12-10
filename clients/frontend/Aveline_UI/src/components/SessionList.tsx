import React, { useEffect, useState } from 'react';
import { api } from '../api/apiService';
import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface Session {
  id: string;
  title: string;
  updated_at: number;
}

interface SessionListProps {
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
}

export const SessionList: React.FC<SessionListProps> = ({ 
  currentSessionId, 
  onSelectSession, 
  onCreateSession 
}) => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isCreating, setIsCreating] = useState(false);

  const fetchSessions = async () => {
    try {
      const res = await api.getSessions();
      if (res.status === 'success') {
        setSessions(res.data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateClick = async () => {
      if (isCreating) return;
      setIsCreating(true);
      try {
          await onCreateSession();
      } catch (e) {
          console.error("Failed to create session:", e);
          alert("Failed to create new topic. Please check backend logs.");
      } finally {
          setIsCreating(false);
      }
  };

  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  // Update list when currentSessionId changes (implies potential new session created elsewhere)
  useEffect(() => {
      fetchSessions();
  }, [currentSessionId]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!id || id === 'null') {
        console.error("Invalid session ID for deletion");
        return;
    }
    if (window.confirm('Are you sure you want to delete this conversation?')) {
        try {
            await api.deleteSession(id);
        } catch (err) {
            console.error("Delete session failed", err);
        }
        fetchSessions();
        if (currentSessionId === id) {
            onCreateSession(); 
        }
    }
  };

  const validSessions = sessions.filter(s => s && s.id && s.id !== 'null');

  return (
    <div className="flex flex-col h-full w-full bg-transparent border-r-0 border-white/5">
      <div className="p-4 border-b border-white/5">
        <button 
          onClick={handleCreateClick}
          disabled={isCreating}
          className="w-full flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 text-white/90 border border-white/10 hover:border-white/20 rounded-lg py-3 px-4 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isCreating ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
              <Plus size={16} />
          )}
          <span className="font-mono text-sm font-bold">{isCreating ? 'CREATING...' : 'NEW TOPIC'}</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
        {validSessions.length === 0 && (
            <div className="text-center text-white/30 text-xs py-10 font-mono">NO HISTORY</div>
        )}
        
        <AnimatePresence>
        {validSessions.map(session => (
          <motion.div 
            key={session.id}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, height: 0 }}
            onClick={() => onSelectSession(session.id)}
            className={`group relative flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all border border-transparent ${
              currentSessionId === session.id 
                ? 'bg-white/10 text-white shadow-lg border-white/10' 
                : 'text-white/50 hover:bg-white/5 hover:text-white/80'
            }`}
          >
            <MessageSquare size={14} className={currentSessionId === session.id ? 'text-emerald-400' : 'opacity-30'} />
            <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate font-mono">{session.title}</div>
                <div className="text-[10px] opacity-40 font-mono flex justify-between">
                    <span>{new Date(session.updated_at * 1000).toLocaleDateString()}</span>
                    <span>{new Date(session.updated_at * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                </div>
            </div>
            
            <button 
                onClick={(e) => handleDelete(e, session.id)}
                className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/20 hover:text-red-400 rounded transition-all"
            >
                <Trash2 size={12} />
            </button>
          </motion.div>
        ))}
        </AnimatePresence>
      </div>
    </div>
  );
};
