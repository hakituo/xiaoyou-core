import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, useDragControls } from 'framer-motion';
import { Message } from '../types';
import ShopModal from './ShopModal';
import SettingsModal from './SettingsModal';
import PetStatsPanel from './PetStatsPanel';

// Hooks
import { usePetVoice } from './pet/usePetVoice';
import { usePetDrag } from './pet/usePetDrag';
import { usePetMovement } from './pet/usePetMovement';
import { useFileDrop } from './pet/useFileDrop';

// Components
import { PetBubble } from './pet/PetBubble';
import { PetControls } from './pet/PetControls';
import { PetInput } from './pet/PetInput';
import { PetContextMenu } from './pet/PetContextMenu';
import { PetAvatar } from './pet/PetAvatar';

export interface DesktopPetProps {
    emotion: string;
    isTyping: boolean;
    lastMessage: Message | null;
    lifeStatus?: any;
    onClose: () => void;
    onInteract: () => void;
    onUpdateSettings?: (settings: any) => void;
    onCall?: () => void;
    onSendMessage: (text: string) => void;
    onPlayTTS: (text: string) => void;
}

type PetAction = 'idle' | 'feed' | 'drink' | 'play' | 'sleep' | 'pet' | 'trash';

type PetState = {
    version: 1;
    coins: number;
    hunger: number;
    thirst: number;
    energy: number;
    moodScore: number;
    level: number;
    xp: number;
    inventory: Record<string, number>;
    lastTickMs: number;
};

type PetSettings = {
    version: 1;
    general: {
        volume: number;
        scale: number;
        opacity: number;
    };
    cloud: any;
};

const PET_STATE_KEY = 'xiaoyou_pet_state_v1';
const PET_SETTINGS_KEY = 'xiaoyou_pet_settings_v1';

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));

const readJson = <T,>(key: string): T | null => {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return null;
        return JSON.parse(raw) as T;
    } catch {
        return null;
    }
};

const DesktopPet: React.FC<DesktopPetProps> = ({
    emotion,
    isTyping,
    lastMessage,
    lifeStatus,
    onClose,
    onInteract,
    onUpdateSettings,
    onCall,
    onSendMessage,
    onPlayTTS
}) => {
    const dragControls = useDragControls();
    const audioContextRef = useRef<AudioContext | null>(null);

    // UI State
    const [showBubble, setShowBubble] = useState(false);
    const [contextMenu, setContextMenu] = useState<{ visible: boolean; x: number; y: number } | null>(null);
    const [isHovering, setIsHovering] = useState(false);
    const [bubbleText, setBubbleText] = useState<string | null>(null);
    const [petAction, setPetAction] = useState<PetAction>('idle');

    // Modals State
    const [showShop, setShowShop] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [showStats, setShowStats] = useState(false);

    // Input State
    const [showInput, setShowInput] = useState(false);
    const [inputValue, setInputValue] = useState("");

    // Electron check
    const isElectron = typeof window !== 'undefined' &&
        navigator.userAgent.toLowerCase().includes('electron');

    const ipcRenderer = isElectron && (window as any).require
        ? (window as any).require('electron').ipcRenderer
        : null;
    
    // Pywebview check
    const isPywebview = typeof window !== 'undefined' && (window as any).pywebview;

    const openQuickSettings = useCallback(() => {
        const native = (window as any)?.aveline_native;
        if (native && typeof native.openQuickSettings === 'function') {
            native.openQuickSettings();
            return true;
        }
        return false;
    }, []);

    const [petState, setPetState] = useState<PetState>(() => {
        const now = Date.now();
        const saved = readJson<PetState>(PET_STATE_KEY);
        if (saved && saved.version === 1) {
            return { ...saved, lastTickMs: saved.lastTickMs || now };
        }
        return {
            version: 1,
            coins: 200,
            hunger: 80,
            thirst: 80,
            energy: 90,
            moodScore: 85,
            level: 1,
            xp: 0,
            inventory: {},
            lastTickMs: now,
        };
    });

    const [petSettings, setPetSettings] = useState<PetSettings>(() => {
        const saved = readJson<PetSettings>(PET_SETTINGS_KEY);
        if (saved && saved.version === 1) return saved;
        return {
            version: 1,
            general: { volume: 80, scale: 100, opacity: 100 },
            cloud: {
                stt: { provider: 'local', api_key: '', base_url: '', model: '' },
                tts: { provider: 'local', api_key: '', base_url: '', model: '' },
                image: { provider: 'local', api_key: '', base_url: '', model: '' }
            }
        };
    });

    // --- Logic Hooks ---

    const isInteracting = !!contextMenu || showInput || showShop || showSettings || showStats;

    const playTone = useCallback((frequency: number, durationMs: number) => {
        try {
            if (!audioContextRef.current) {
                const AudioContextCtor = (window as any).AudioContext || (window as any).webkitAudioContext;
                if (!AudioContextCtor) return;
                audioContextRef.current = new AudioContextCtor();
            }
            const ctx = audioContextRef.current;
            if (!ctx) return;

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            const volume = clamp((petSettings.general.volume ?? 80) / 100, 0, 1);
            const now = ctx.currentTime;

            osc.type = 'sine';
            osc.frequency.setValueAtTime(frequency, now);

            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.06 * volume, now + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + durationMs / 1000);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start(now);
            osc.stop(now + durationMs / 1000);
        } catch {
        }
    }, [petSettings.general.volume]);

    const triggerAction = useCallback((action: PetAction) => {
        setPetAction(action);
        window.setTimeout(() => setPetAction('idle'), 900);
    }, []);

    const showPetBubble = useCallback((text: string, autoHideMs = 3500) => {
        setBubbleText(text);
        setShowBubble(true);
        window.setTimeout(() => {
            setShowBubble(false);
            setBubbleText(null);
        }, autoHideMs);
    }, []);

    // Voice
    const handleTranscription = (text: string) => {
        if (showInput) {
            setInputValue(prev => prev + (prev ? ' ' : '') + text);
        } else {
            onSendMessage(text);
        }
    };
    
    // Handle returning to main mode
    const handleReturnToMain = () => {
        if ((window as any).exitPetMode) {
            (window as any).exitPetMode();
        } else {
            onClose();
        }
    };

    const {
        isRecording,
        isProcessing,
        toggleRecording
    } = usePetVoice({ onTranscription: handleTranscription });

    // XP and Level Up Logic
    useEffect(() => {
        // Level up threshold: 100 * level
        const threshold = petState.level * 100;
        if (petState.xp >= threshold) {
             setPetState(prev => ({
                 ...prev,
                 level: prev.level + 1,
                 xp: prev.xp - threshold
             }));
             playTone(523, 100);
             setTimeout(() => playTone(659, 100), 100);
             setTimeout(() => playTone(784, 200), 200);
             showPetBubble(`SYSTEM UPGRADE: Level ${petState.level + 1} Reached!`);
        }
    }, [petState.xp, petState.level, playTone, showPetBubble]);

    // Handle Interaction (XP Gain)
    const handleDragInteract = useCallback(() => {
        if (petAction !== 'idle') return;
        
        setPetState(prev => ({
            ...prev,
            moodScore: Math.min(100, prev.moodScore + 2),
            xp: prev.xp + 5 // Gain XP
        }));
        
        triggerAction('pet');
        playTone(523.25, 120);
        showPetBubble('摸摸~');
        onInteract();
    }, [petAction, onInteract, triggerAction, playTone, showPetBubble]);

    const {
        isDragging,
        handlePointerDown,
        handlePointerUp
    } = usePetDrag({
        isElectron,
        ipcRenderer,
        dragControls,
        onInteract: handleDragInteract 
    });

    usePetMovement(isElectron, ipcRenderer, isDragging, isInteracting);

    const handleFileTrash = useCallback((count: number) => {
        setPetState(prev => {
            const coins = prev.coins + count * 10;
            const moodScore = clamp(prev.moodScore + Math.min(8, count), 0, 100);
            return { ...prev, coins, moodScore };
        });
        triggerAction('trash');
        playTone(196, 180);
        showPetBubble(`清理完成 +${count * 10} 🪙`);
    }, [playTone, showPetBubble, triggerAction]);

    const {
        isDragOver,
        handleDragOver,
        handleDragLeave,
        handleDrop
    } = useFileDrop({ isElectron, onFileTrash: handleFileTrash });
    
    // Right click handler
    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        setContextMenu({ visible: true, x: e.clientX, y: e.clientY });
    };

    const effectiveStats = useMemo(() => {
        if (lifeStatus) return lifeStatus;
        return {
            life: {
                energy: petState.energy,
                hunger: petState.hunger,
                thirst: petState.thirst,
                mood_score: petState.moodScore,
            },
            bio: {}
        };
    }, [lifeStatus, petState.energy, petState.hunger, petState.moodScore, petState.thirst]);

    const performFeed = useCallback(() => {
        setPetState(prev => {
            const cost = 20;
            if (prev.coins < cost) return prev;
            return {
                ...prev,
                coins: prev.coins - cost,
                hunger: clamp(prev.hunger + 18, 0, 100),
                moodScore: clamp(prev.moodScore + 6, 0, 100)
            };
        });
        triggerAction('feed');
        playTone(392, 140);
        showPetBubble('投喂成功');
    }, [playTone, showPetBubble, triggerAction]);

    const performDrink = useCallback(() => {
        setPetState(prev => {
            const cost = 10;
            if (prev.coins < cost) return prev;
            return {
                ...prev,
                coins: prev.coins - cost,
                thirst: clamp(prev.thirst + 22, 0, 100),
                moodScore: clamp(prev.moodScore + 4, 0, 100)
            };
        });
        triggerAction('drink');
        playTone(440, 120);
        showPetBubble('咕嘟咕嘟~');
    }, [playTone, showPetBubble, triggerAction]);

    const performPlay = useCallback(() => {
        setPetState(prev => ({
            ...prev,
            energy: clamp(prev.energy - 6, 0, 100),
            moodScore: clamp(prev.moodScore + 10, 0, 100),
            hunger: clamp(prev.hunger - 2, 0, 100),
            thirst: clamp(prev.thirst - 2, 0, 100),
        }));
        triggerAction('play');
        playTone(659.25, 120);
        showPetBubble('一起玩!');
    }, [playTone, showPetBubble, triggerAction]);

    const performSleep = useCallback(() => {
        setPetState(prev => ({
            ...prev,
            energy: clamp(prev.energy + 20, 0, 100),
            moodScore: clamp(prev.moodScore + 2, 0, 100)
        }));
        triggerAction('sleep');
        playTone(261.63, 200);
        showPetBubble('晚安~');
    }, [playTone, showPetBubble, triggerAction]);

    const handleBuy = useCallback((item: { id: string; name: string; price: number; icon: string }) => {
        // Transaction is handled by ShopModal calling the API.
        // We just handle the UI feedback here.
        playTone(740, 90);
        showPetBubble(`已购买 ${item.name}`);
        
        // Trigger dynamic LLM response for purchase
        const purchaseEvent = `[SYSTEM_EVENT:PURCHASE] 用户刚刚在食物商店为你购买了食物：${item.name} (${item.icon})。请根据当前的上下文和你现在的心情，对这次购买做出拟人化的、符合你性格的反应。如果是美味的食物，可以表现得开心一点。`;
        onSendMessage(purchaseEvent);
        
        return true;
    }, [playTone, showPetBubble, onSendMessage]);

    const handleAddCoins = useCallback((amount: number) => {
        setPetState(prev => ({ ...prev, coins: prev.coins + amount }));
        playTone(659.25, 100);
        showPetBubble(`获得 ${amount} 🪙`);
    }, [playTone, showPetBubble]);

    useEffect(() => {
        try {
            localStorage.setItem(PET_STATE_KEY, JSON.stringify(petState));
        } catch {
        }
    }, [petState]);

    useEffect(() => {
        try {
            localStorage.setItem(PET_SETTINGS_KEY, JSON.stringify(petSettings));
        } catch {
        }
    }, [petSettings]);

    useEffect(() => {
        const interval = window.setInterval(() => {
            const now = Date.now();
            setPetState(prev => {
                const dtMin = Math.max(0, (now - prev.lastTickMs) / 60000);
                if (dtMin < 0.02) return prev;
                const hunger = clamp(prev.hunger - dtMin * 1.2, 0, 100);
                const thirst = clamp(prev.thirst - dtMin * 1.6, 0, 100);
                const energy = clamp(prev.energy - dtMin * 0.9, 0, 100);
                const moodPenalty = (hunger < 25 ? 0.4 : 0) + (thirst < 25 ? 0.6 : 0) + (energy < 25 ? 0.3 : 0);
                const moodScore = clamp(prev.moodScore - dtMin * moodPenalty, 0, 100);
                return { ...prev, hunger, thirst, energy, moodScore, lastTickMs: now };
            });
        }, 4000);
        return () => window.clearInterval(interval);
    }, []);

    const avatarScale = clamp((petSettings.general.scale ?? 100) / 100, 0.5, 1.5);
    const avatarOpacity = clamp((petSettings.general.opacity ?? 100) / 100, 0.2, 1);
    const controlsVisible = isHovering || showInput || isRecording || isProcessing;
    const bubbleMessage = bubbleText ?? lastMessage?.text ?? '...';
    const shouldShowBubble = showBubble || !!bubbleText || (isHovering && !!lastMessage);

    return (
        <>
            <motion.div
                className="fixed inset-0 pointer-events-none z-50 flex items-center justify-center"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
            >
                <div 
                    className="relative w-64 h-64 pointer-events-auto"
                    style={{ opacity: avatarOpacity }}
                    onContextMenu={handleContextMenu}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onPointerDown={(e) => {
                        handlePointerDown(e);
                        // Hide bubble on interaction
                        if (showBubble) setShowBubble(false);
                    }}
                    onPointerUp={handlePointerUp}
                    onPointerLeave={handlePointerUp}
                >
                    <PetControls
                        showInput={showInput}
                        onToggleInput={() => setShowInput(v => !v)}
                        isRecording={isRecording}
                        isProcessing={isProcessing}
                        onToggleRecording={toggleRecording}
                        onClose={onClose}
                        visible={controlsVisible}
                    />
                    <PetAvatar 
                        emotion={emotion} 
                        status={isTyping ? 'thinking' : 'idle'}
                        isDragging={isDragging}
                        scale={avatarScale}
                        action={petAction}
                        isDragOver={isDragOver}
                        onPointerDown={handlePointerDown}
                        onPointerUp={handlePointerUp}
                        onContextMenu={handleContextMenu}
                        onMouseEnter={() => setIsHovering(true)}
                        onMouseLeave={() => setIsHovering(false)}
                    />
                    
                    {/* Bubble */}
                    {shouldShowBubble && (
                         <PetBubble 
                            message={bubbleMessage} 
                            visible={shouldShowBubble}
                            onPlayTTS={onPlayTTS}
                         />
                    )}
                </div>

                {/* Context Menu */}
                {contextMenu && (
                    <PetContextMenu 
                        x={contextMenu.x}
                        y={contextMenu.y}
                        onClose={() => setContextMenu(null)}
                        onChat={() => setShowInput(true)}
                        onDashboard={handleReturnToMain}
                        onCall={() => onCall && onCall()}
                        onStats={() => setShowStats(true)}
                        onFeed={performFeed}
                        onDrink={performDrink}
                        onPlay={performPlay}
                        onSleep={performSleep}
                        onShop={() => setShowShop(true)}
                        onSettings={() => {
                            if (!openQuickSettings()) {
                                setShowSettings(true);
                            }
                        }}
                    />
                )}
                
                {/* Input Field Overlay */}
                {showInput && (
                    <PetInput 
                        value={inputValue}
                        onChange={setInputValue}
                        onSend={() => {
                            if (inputValue.trim()) {
                                onSendMessage(inputValue);
                                setInputValue("");
                                setShowInput(false);
                            }
                        }}
                        onClose={() => setShowInput(false)}
                    />
                )}
                
                {/* Stats Panel Overlay */}
                {showStats && (
                    <PetStatsPanel 
                        stats={effectiveStats}
                        emotion={emotion as any}
                        onClose={() => setShowStats(false)}
                    />
                )}

                {showShop && (
                    <ShopModal
                        coins={petState.coins}
                        level={petState.level}
                        onBuy={handleBuy}
                        onAddCoins={handleAddCoins}
                        onClose={() => setShowShop(false)}
                    />
                )}

                {showSettings && (
                    <SettingsModal
                        initialSettings={petSettings}
                        onUpdateSettings={(s) => setPetSettings((prev) => ({ ...prev, ...s, version: 1 }))}
                        onClose={() => setShowSettings(false)}
                    />
                )}
                
            </motion.div>
        </>
    );
};

export default DesktopPet;
