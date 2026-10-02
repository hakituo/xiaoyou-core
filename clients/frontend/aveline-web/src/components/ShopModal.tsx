import React, { useState, useEffect } from 'react';
import { ShoppingBag, Coins, Utensils, Coffee, Cookie, AlertCircle, CheckCircle2, PlusCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../api/apiService';

interface ShopModalProps {
  onClose: () => void;
  coins: number;
  level: number;
  onBuy: (item: any) => boolean; // Kept for compatibility, but we might just use it to trigger refresh
  onAddCoins?: (amount: number) => void;
}

interface FoodItem {
  id: string;
  name: string;
  description: string;
  price: number;
  type: 'meal' | 'snack' | 'drink' | 'ingredient';
  icon: string;
  nutrition: {
    hunger: number;
    thirst: number;
    energy: number;
    health: number;
  };
  min_level: number;
}

const CATEGORIES = [
  { id: 'all', label: 'All', icon: ShoppingBag },
  { id: 'meal', label: 'Meals', icon: Utensils },
  { id: 'snack', label: 'Snacks', icon: Cookie },
  { id: 'drink', label: 'Drinks', icon: Coffee },
];

const ShopModal: React.FC<ShopModalProps> = ({ onClose, coins, level, onBuy, onAddCoins }) => {
  const [activeTab, setActiveTab] = useState('all');
  const [menu, setMenu] = useState<FoodItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buying, setBuying] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    fetchMenu();
  }, []);

  const fetchMenu = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get('/api/v1/food/menu');
      if (Array.isArray(data)) {
        setMenu(data);
      } else {
        setError('Data format error');
      }
    } catch (err: any) {
      console.error('Failed to fetch menu:', err);
      setError(err.message || 'Connection error');
    } finally {
      setLoading(false);
    }
  };

  const handleBuy = async (item: FoodItem) => {
    setBuying(item.id);
    setMessage(null);

    try {
      const data = await api.post(`/api/v1/food/eat/${item.id}?eater=user`);
      
      if (data && data.success) {
        setMessage({ text: data.message, type: 'success' });
        // Notify parent to refresh/play sound
        onBuy(item);
      } else if (data) {
        setMessage({ text: data.message, type: 'error' });
      }
    } catch (err: any) {
      setMessage({ text: err.message || 'Purchase failed', type: 'error' });
    } finally {
      setBuying(null);
      setTimeout(() => setMessage(null), 2000);
    }
  };

  const filteredItems = activeTab === 'all' 
    ? menu 
    : menu.filter(item => item.type === activeTab);

  return (
    <div className="fixed inset-0 flex items-center justify-center z-[70] p-4 pointer-events-auto">
      <div 
        className="absolute inset-0 bg-black/20 backdrop-blur-sm" 
        onClick={onClose}
      />
      <motion.div 
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="bg-white/90 dark:bg-slate-800/90 w-full max-w-sm rounded-2xl shadow-2xl border border-white/20 overflow-hidden flex flex-col max-h-[500px]"
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-700/50 flex justify-between items-center bg-slate-900/50">
          <div className="flex items-center gap-2 text-slate-100 font-bold">
            <Utensils size={20} className="text-rose-400" />
            <span>Food Court</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 bg-yellow-500/20 border border-yellow-500/30 rounded-full">
            <span className="text-yellow-400 font-mono font-bold">🪙 {coins}</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex p-2 gap-1 bg-slate-900/30 overflow-x-auto no-scrollbar">
          {CATEGORIES.map(cat => (
            <button
              key={cat.id}
              onClick={() => setActiveTab(cat.id)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
              style={{ 
                backgroundColor: activeTab === cat.id ? '#f43f5e' : 'transparent',
                color: activeTab === cat.id ? 'white' : '#94a3b8'
              }}
            >
              <cat.icon size={16} />
              {cat.label}
            </button>
          ))}
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-4 relative">
           {/* Message Toast */}
           <AnimatePresence>
            {message && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className={`absolute top-2 left-2 right-2 z-50 px-3 py-2 rounded-lg shadow-lg backdrop-blur-md border ${
                        message.type === 'success' 
                            ? 'bg-emerald-500/90 border-emerald-500/50 text-white' 
                            : 'bg-red-500/90 border-red-500/50 text-white'
                    } text-xs font-bold flex items-center gap-2 justify-center`}
                >
                    {message.type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                    {message.text}
                </motion.div>
            )}
           </AnimatePresence>

           {loading ? (
             <div className="flex flex-col items-center justify-center py-10 space-y-2">
                <div className="w-8 h-8 border-2 border-rose-500/20 border-t-rose-500 rounded-full animate-spin" />
                <div className="text-slate-500 text-xs">Loading...</div>
             </div>
           ) : error ? (
             <div className="flex flex-col items-center justify-center py-10 space-y-2">
                <AlertCircle size={32} className="text-red-400/50" />
                <div className="text-red-400/70 text-xs text-center px-4">{error}</div>
                <button onClick={fetchMenu} className="text-[10px] text-rose-400 hover:underline">Retry</button>
             </div>
           ) : filteredItems.length === 0 ? (
             <div className="flex flex-col items-center justify-center py-10 space-y-2 text-slate-500">
                <ShoppingBag size={32} className="opacity-20" />
                <div className="text-xs">Empty</div>
             </div>
           ) : (
             <div className="grid grid-cols-3 gap-3">
              {filteredItems.map((item) => {
                const isLocked = false;
                const canAfford = true;
                
                return (
                  <button
                    key={item.id}
                    onClick={() => handleBuy(item)}
                    disabled={isLocked || !canAfford || buying === item.id}
                    className={`flex flex-col items-center p-3 rounded-xl border transition-all active:scale-95 group relative ${
                      isLocked 
                        ? 'bg-slate-800/50 border-slate-700/50 opacity-60 cursor-not-allowed' 
                        : !canAfford
                          ? 'bg-slate-700/30 border-slate-600/30 opacity-60 cursor-not-allowed'
                          : 'bg-slate-700/30 hover:bg-slate-700/70 border-slate-600/30 cursor-pointer'
                    }`}
                  >
                    {isLocked && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/40 rounded-xl z-10 backdrop-blur-[1px]">
                        <span className="text-[10px] font-bold text-rose-400">LV.{item.min_level}</span>
                        <span className="text-[8px] text-white/60 uppercase">Locked</span>
                      </div>
                    )}
                    <div className="text-3xl mb-2 group-hover:scale-110 transition-transform">
                      {item.icon}
                    </div>
                    <div className="text-[10px] font-bold text-slate-200 text-center line-clamp-1 w-full">
                      {item.name}
                    </div>
                    <div className={`text-[10px] font-mono ${canAfford ? 'text-yellow-500' : 'text-red-400'}`}>
                      🪙 {item.price}
                    </div>
                  </button>
                );
              })}
             </div>
           )}
        </div>
      </motion.div>
    </div>
  );
};

export default ShopModal;
