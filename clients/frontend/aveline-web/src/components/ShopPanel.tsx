import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ShoppingBag, Utensils, Coffee, Cookie, AlertCircle, CheckCircle2, Search, Sparkles, Coins } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAvelineStore } from '../store/useStore';
import api from '../api/apiService';

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


type FoodLayout = 'grid' | 'list' | 'compact';

type ShopPanelProps = { platform?: 'web' | 'mobile' };
const ShopPanel: React.FC<ShopPanelProps> = ({ platform = 'web' }) => {
  const [activeTab, setActiveTab] = useState('all');
  const [query, setQuery] = useState('');
  const layout: FoodLayout = platform === 'mobile' ? 'list' : 'grid';
  const [menu, setMenu] = useState<FoodItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buying, setBuying] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const clearMessageTimerRef = useRef<number | null>(null);

  const { lifeStatus } = useAvelineStore();
  
  const coins = lifeStatus?.coins || 0;
  const level = lifeStatus?.level || 1;

  useEffect(() => {
    fetchMenu();
  }, []);

  useEffect(() => {
    return () => {
      if (clearMessageTimerRef.current) window.clearTimeout(clearMessageTimerRef.current);
    };
  }, []);

  const fetchMenu = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get('/api/v1/food/menu');
      if (Array.isArray(data)) {
        setMenu(data);
      } else {
        console.error('Invalid menu data format:', data);
        setError('Menu data format error');
      }
    } catch (err: any) {
      console.error('Failed to fetch menu:', err);
      setError(err.message || 'Failed to connect to server');
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
      } else if (data) {
        setMessage({ text: data.message, type: 'error' });
      }
    } catch (err: any) {
      setMessage({ text: err.message || 'Purchase failed', type: 'error' });
    } finally {
      setBuying(null);
      if (clearMessageTimerRef.current) window.clearTimeout(clearMessageTimerRef.current);
      clearMessageTimerRef.current = window.setTimeout(() => setMessage(null), 3000);
    }
  };

  const filteredItems = useMemo(() => {
    const byType = activeTab === 'all' ? menu : menu.filter((item) => item.type === activeTab);
    const q = query.trim().toLowerCase();
    if (!q) return byType;
    return byType.filter((item) => {
      const text = `${item.name} ${item.description}`.toLowerCase();
      return text.includes(q);
    });
  }, [activeTab, menu, query]);

  const content = (
    <>
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 space-y-4">
          <div className="w-10 h-10 border-4 border-rose-500/20 border-t-rose-500 rounded-full animate-spin" />
          <div className="text-white/40">Loading menu...</div>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-20 space-y-4 bg-red-500/5 rounded-3xl border border-red-500/10">
          <AlertCircle size={48} className="text-red-400" />
          <div className="text-red-200 font-medium">{error}</div>
          <button
            onClick={fetchMenu}
            className="px-6 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-xl transition-colors"
          >
            Retry
          </button>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 space-y-4 bg-white/5 rounded-3xl border border-white/10">
          <ShoppingBag size={48} className="text-white/10" />
          <div className="text-white/40">No items found.</div>
        </div>
      ) : layout === 'grid' ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-6">
          {filteredItems.map((item) => {
            const isLocked = false;
            const canAfford = true;

            return (
              <button
                key={item.id}
                onClick={() => handleBuy(item)}
                disabled={isLocked || !canAfford || buying === item.id}
                className={`flex flex-col items-center p-4 md:p-6 rounded-2xl bg-white/5 border border-white/5 transition-all duration-200 group relative overflow-hidden ${
                  isLocked
                    ? 'opacity-40 grayscale cursor-not-allowed'
                    : !canAfford
                      ? 'opacity-60 cursor-not-allowed'
                      : 'hover:bg-white/10 hover:border-white/20 hover:-translate-y-0.5 hover:shadow-xl cursor-pointer'
                }`}
              >
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.12),transparent_55%)] opacity-0 group-hover:opacity-100 transition-opacity" />

                {isLocked && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/40 z-20 backdrop-blur-[2px]">
                    <div className="bg-rose-500 text-white text-[10px] font-bold px-2 py-0.5 rounded mb-1">LV.{item.min_level}</div>
                    <div className="text-[10px] text-white/60 font-bold uppercase tracking-wider">Locked</div>
                  </div>
                )}

                <div className="text-5xl md:text-6xl mb-4 group-hover:scale-110 transition-transform duration-200 drop-shadow-lg">
                  {item.icon}
                </div>
                <div className="text-[15px] font-semibold text-white/90 mb-1 text-center leading-tight">
                  {item.name}
                </div>
                <div className="text-xs text-white/40 mb-3 text-center line-clamp-2 min-h-[32px]">
                  {item.description}
                </div>

                <div className="flex flex-wrap justify-center gap-1.5 mb-3">
                  {item.nutrition.hunger > 0 && (
                    <span className="text-[10px] bg-orange-500/15 text-orange-200 px-2 py-0.5 rounded-full border border-orange-500/20">
                      Hunger -{item.nutrition.hunger}
                    </span>
                  )}
                  {item.nutrition.energy > 0 && (
                    <span className="text-[10px] bg-yellow-500/15 text-yellow-200 px-2 py-0.5 rounded-full border border-yellow-500/20">
                      Energy +{item.nutrition.energy}
                    </span>
                  )}
                  {item.nutrition.health > 0 && (
                    <span className="text-[10px] bg-emerald-500/15 text-emerald-200 px-2 py-0.5 rounded-full border border-emerald-500/20">
                      Health +{item.nutrition.health}
                    </span>
                  )}
                </div>

                <div
                  className={`px-3 py-1 rounded-full font-mono text-sm border ${
                    canAfford
                      ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/20'
                      : 'bg-red-500/15 text-red-300 border-red-500/20'
                  }`}
                >
                  {item.price}
                </div>
              </button>
            );
          })}
        </div>
      ) : layout === 'list' ? (
        <div className="space-y-3">
          {filteredItems.map((item) => {
            const isLocked = false;
            const canAfford = true;
            const disabled = isLocked || !canAfford || buying === item.id;

            return (
              <button
                key={item.id}
                onClick={() => handleBuy(item)}
                disabled={disabled}
                className={`w-full glass-card rounded-2xl p-4 border border-white/10 transition-all duration-200 text-left ${
                  disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-white/10 hover:border-white/20'
                }`}
              >
                <div className="flex items-start gap-4">
                  <div className="shrink-0 w-14 h-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-4xl">
                    {item.icon}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                          <div className="text-base font-semibold text-white/90 truncate">{item.name}</div>
                          {isLocked && (
                            <div className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-200 border border-rose-500/25">
                              LV.{item.min_level}
                            </div>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-white/40 line-clamp-2">{item.description}</div>
                      </div>

                      <div className="shrink-0 flex flex-col items-end gap-2">
                        <div
                          className={`px-3 py-1 rounded-full font-mono text-xs border ${
                            canAfford
                              ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/20'
                              : 'bg-red-500/15 text-red-300 border-red-500/20'
                          }`}
                        >
                          {item.price}
                        </div>
                        <div className="text-[10px] text-white/25 font-mono">
                          {buying === item.id ? 'EATING…' : canAfford ? 'TAP TO EAT' : 'INSUFFICIENT'}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {item.nutrition.hunger > 0 && (
                        <span className="text-[10px] bg-orange-500/15 text-orange-200 px-2 py-0.5 rounded-full border border-orange-500/20">
                          Hunger -{item.nutrition.hunger}
                        </span>
                      )}
                      {item.nutrition.thirst > 0 && (
                        <span className="text-[10px] bg-sky-500/15 text-sky-200 px-2 py-0.5 rounded-full border border-sky-500/20">
                          Thirst -{item.nutrition.thirst}
                        </span>
                      )}
                      {item.nutrition.energy > 0 && (
                        <span className="text-[10px] bg-yellow-500/15 text-yellow-200 px-2 py-0.5 rounded-full border border-yellow-500/20">
                          Energy +{item.nutrition.energy}
                        </span>
                      )}
                      {item.nutrition.health > 0 && (
                        <span className="text-[10px] bg-emerald-500/15 text-emerald-200 px-2 py-0.5 rounded-full border border-emerald-500/20">
                          Health +{item.nutrition.health}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="glass-card rounded-2xl border border-white/10 overflow-hidden">
          <div className="divide-y divide-white/5">
            {filteredItems.map((item) => {
              const isLocked = false;
              const canAfford = true;
              const disabled = isLocked || !canAfford || buying === item.id;

              return (
                <button
                  key={item.id}
                  onClick={() => handleBuy(item)}
                  disabled={disabled}
                  className={`w-full px-4 py-3 flex items-center gap-3 text-left transition-colors ${
                    disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-white/5'
                  }`}
                >
                  <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-2xl shrink-0">
                    {item.icon}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="text-sm font-medium text-white/85 truncate">{item.name}</div>
                      {isLocked && (
                        <div className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-200 border border-rose-500/25 shrink-0">
                          LV.{item.min_level}
                        </div>
                      )}
                    </div>
                    <div className="text-[11px] text-white/35 truncate">{item.description}</div>
                  </div>
                  <div
                    className={`px-2.5 py-1 rounded-full font-mono text-[11px] border shrink-0 ${
                      canAfford
                        ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/20'
                        : 'bg-red-500/15 text-red-300 border-red-500/20'
                    }`}
                  >
                    {item.price}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </>
  );

  return (
    <div className="flex-1 p-4 md:p-8 overflow-y-auto custom-scrollbar h-full">
      <div className="max-w-7xl mx-auto space-y-4">
        <div className="relative p-2">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
                  <Utensils className="text-white/70" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-white/95 tracking-wide">Food Court</h2>
                  <div className="flex items-center gap-2 mt-1">
                     <span className="text-white/45 text-xs">Feed your companion.</span>
                     <div className="h-3 w-[1px] bg-white/10"></div>
                     <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1">
                           <Coins size={10} className="text-yellow-300" />
                           <span className="font-mono font-bold text-yellow-200 text-xs">{coins}</span>
                        </div>
                        <div className="flex items-center gap-1">
                           <Sparkles size={10} className="text-emerald-300" />
                           <span className="font-mono font-bold text-emerald-200 text-xs">LV.{level}</span>
                        </div>
                     </div>
                  </div>
                </div>
              </div>

              <div className="w-[180px] hidden md:block">
                 <div className="glass-panel border border-white/10 rounded-xl px-3 py-1.5 flex items-center gap-2">
                   <Search size={14} className="text-white/35" />
                   <input
                     value={query}
                     onChange={(e) => setQuery(e.target.value)}
                     placeholder="Search food..."
                     className="bg-transparent outline-none text-xs text-white/80 placeholder:text-white/25 w-full"
                   />
                 </div>
               </div>
            </div>

            {/* Mobile Search */}
            <div className="md:hidden">
                 <div className="bg-black/20 border border-white/5 rounded-xl px-3 py-2 flex items-center gap-2">
                   <Search size={14} className="text-white/35" />
                   <input
                     value={query}
                     onChange={(e) => setQuery(e.target.value)}
                     placeholder="Search food..."
                     className="bg-transparent outline-none text-xs text-white/80 placeholder:text-white/25 w-full"
                   />
                 </div>
            </div>

            <div className="flex overflow-x-auto no-scrollbar pb-2 -mx-4 px-4 md:mx-0 md:px-0">
                <div className="flex items-center gap-2">
                  {CATEGORIES.map((cat) => (
                    <button
                      key={cat.id}
                      onClick={() => setActiveTab(cat.id)}
                      className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-medium transition-all duration-200 whitespace-nowrap border ${
                        activeTab === cat.id
                          ? 'bg-white/10 text-white border-white/15 shadow-sm'
                          : 'bg-white/5 text-white/45 border-transparent hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <cat.icon size={14} />
                      {cat.label}
                    </button>
                  ))}
                </div>
            </div>
          </div>
        </div>

        {/* Message Toast */}

        <AnimatePresence>
            {message && (
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -20 }}
                    className={`fixed top-[calc(env(safe-area-inset-top)+16px)] left-1/2 -translate-x-1/2 z-50 px-6 py-3 rounded-full shadow-2xl backdrop-blur-sm border ${
                        message.type === 'success' 
                            ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-200' 
                            : 'bg-red-500/20 border-red-500/50 text-red-200'
                    } font-bold flex items-center gap-2`}
                >
                    {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                    {message.text}
                </motion.div>
            )}
        </AnimatePresence>



        {content}
      </div>
    </div>
  );
};

export default ShopPanel;
