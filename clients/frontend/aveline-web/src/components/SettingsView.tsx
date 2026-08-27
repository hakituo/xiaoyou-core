import React, { useState, useEffect } from 'react';
import { 
  Settings, User, Monitor, Cpu, Volume2, Shield, 
  Palette, Database, Globe, Bell, Keyboard, Check, Cloud, HardDrive, Brain
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../api/apiService';
import { CustomSelect } from './ui/CustomSelect';

interface SettingsTabProps {
  icon: React.ElementType;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

const SettingsTab = ({ icon: Icon, label, isActive, onClick }: SettingsTabProps) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 group ${
      isActive 
        ? 'bg-white/10 text-white shadow-[0_0_15px_rgba(255,255,255,0.05)] border border-white/10' 
        : 'text-white/40 hover:text-white/80 hover:bg-white/5'
    }`}
  >
    <Icon size={18} className={`transition-colors ${isActive ? 'text-primary-400' : 'group-hover:text-white'}`} />
    <span className="font-medium tracking-wide text-sm">{label}</span>
  </button>
);

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <h3 className="text-lg font-medium text-white/90 mb-4 flex items-center gap-2">
    {children}
  </h3>
);

const SettingItem = ({ label, description, children }: { label: string, description?: string, children: React.ReactNode }) => (
  <div className="group bg-black/20 hover:bg-black/30 border border-white/5 rounded-xl p-4 transition-all duration-300">
    <div className="flex items-center justify-between">
      <div className="space-y-1">
        <div className="text-sm font-medium text-white/80">{label}</div>
        {description && <div className="text-xs text-white/40 group-hover:text-white/60 transition-colors">{description}</div>}
      </div>
      <div>{children}</div>
    </div>
  </div>
);

const Toggle = ({ checked, onChange }: { checked: boolean, onChange: (v: boolean) => void }) => (
  <button
    onClick={() => onChange(!checked)}
    className={`w-12 h-6 rounded-full relative transition-colors duration-300 ${
      checked ? 'bg-primary-600' : 'bg-white/10'
    }`}
  >
    <div className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full shadow-md transition-transform duration-300 ${
      checked ? 'translate-x-6' : 'translate-x-0'
    }`} />
  </button>
);

export default function SettingsView({ 
  onClose,
  onRequestConfirm
}: { 
  onClose: () => void;
  onRequestConfirm?: (opts: {
    title: string;
    message: string;
    onConfirm: () => void;
    onCancel: () => void;
    confirmText?: string;
    cancelText?: string;
    type?: 'danger' | 'info' | 'warning';
    showCancel?: boolean;
  }) => void;
}) {
  const [activeTab, setActiveTab] = useState('general');

  // Sample states for demo
  const [autoUpdate, setAutoUpdate] = useState(true);
  const [darkMode, setDarkMode] = useState(true);
  const [soundEffects, setSoundEffects] = useState(true);
  const [streamResponse, setStreamResponse] = useState(true);
  
  // Network settings
  const [apiUrl, setApiUrl] = useState(() => {
    const stored = localStorage.getItem('AVELINE_API_URL');
    if (stored) return stored;
    // Default from config if not stored
    const hostname = window.location.hostname;
    const isDevServer = ['5173', '3000'].includes(window.location.port);
    return isDevServer ? `http://${hostname}:8000` : window.location.origin;
  });
  const [accessToken, setAccessToken] = useState(() => {
    return localStorage.getItem('XIAOYOU_ACCESS_TOKEN') || '';
  });
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');

  // Model Settings State
  const [modelList, setModelList] = useState<any[]>([]);
  const [currentModel, setCurrentModel] = useState<any>(null);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    if (activeTab === 'model') {
      fetchModels();
    }
  }, [activeTab]);

  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      const res = await api.getModels();
      // Ensure compatibility if backend doesn't return category yet (though I just added it)
      const list = (res.available || []).map((m: any) => ({
        ...m,
        category: m.category || (m.path?.startsWith('cloud:') ? 'cloud' : 'local')
      }));
      setModelList(list);
      setCurrentModel(res.current);
    } catch (e) {
      console.error("Failed to fetch models", e);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleSwitchModel = async (model: any) => {
    try {
      // 解析模型路径，支持两种格式：
      // 1. cloud:provider:model（传统格式）
      // 2. cloud:provider:key_alias:model（多API key格式）
      let provider = 'local';
      if (model.category === 'cloud' && model.path) {
        const parts = model.path.split(':');
        if (parts.length >= 2) {
          provider = parts[1]; // 提取provider
        }
      } else if (model.category !== 'cloud') {
        provider = 'local';
      }
      
      await api.switchModel(model.name, provider);
      await fetchModels();
    } catch (e: any) {
      if (onRequestConfirm) {
        onRequestConfirm({
          title: '切换模型失败',
          message: "错误: " + (e.message || e),
          type: 'danger',
          showCancel: false,
          confirmText: '确定',
          onConfirm: () => {},
          onCancel: () => {}
        });
      }
    }
  };

  const handleSaveApiUrl = () => {
    localStorage.setItem('AVELINE_API_URL', apiUrl.replace(/\/$/, ''));
    localStorage.setItem('XIAOYOU_ACCESS_TOKEN', accessToken);
    setTestStatus('success');
    setTimeout(() => setTestStatus('idle'), 2000);
    
    // Sync to Native Android if available
    if ((window as any).aveline_native?.setBackendUrl) {
      (window as any).aveline_native.setBackendUrl(apiUrl.replace(/\/$/, ''));
    }

    // Reload to apply new URL
    const msg = 'API 地址已更新，需要刷新页面以应用更改。是否立即刷新？';
    if (onRequestConfirm) {
        onRequestConfirm({
            title: '配置已保存',
            message: msg,
            type: 'warning',
            confirmText: '立即刷新',
            cancelText: '稍后',
            onConfirm: () => window.location.reload(),
            onCancel: () => {}
        });
    }
  };

  const requestUsageStats = () => {
    if ((window as any).aveline_native?.openUsageAccessSettings) {
      (window as any).aveline_native.openUsageAccessSettings();
    } else {
      if (onRequestConfirm) {
        onRequestConfirm({
            title: '功能不可用',
            message: "此功能仅在 Android 原生应用中可用",
            type: 'info',
            showCancel: false,
            confirmText: '我知道了',
            onConfirm: () => {},
            onCancel: () => {}
        });
      }
    }
  };


  const testConnection = async () => {
    setTestStatus('testing');
    try {
      const response = await fetch(`${apiUrl}/health`, { method: 'GET' });
      if (response.ok) {
        setTestStatus('success');
      } else {
        setTestStatus('error');
      }
    } catch (err) {
      setTestStatus('error');
    }
    setTimeout(() => setTestStatus('idle'), 3000);
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'general':
        return (
          <div className="space-y-6">
            <SectionTitle><Monitor size={20} /> 通用设置</SectionTitle>
            <div className="space-y-3">
              <SettingItem label="自动检查更新" description="启动时自动检查新版本">
                <Toggle checked={autoUpdate} onChange={setAutoUpdate} />
              </SettingItem>
              <SettingItem label="开机自启动" description="系统启动时自动运行 Aveline">
                <Toggle checked={false} onChange={() => {}} />
              </SettingItem>
              <SettingItem label="语言" description="界面显示语言">
                <div className="w-40">
                  <CustomSelect
                    value="简体中文"
                    onChange={() => {}}
                    options={[
                      { value: '简体中文', label: '简体中文' },
                      { value: 'English', label: 'English' },
                      { value: '日本語', label: '日本語' }
                    ]}
                    className="w-full"
                  />
                </div>
              </SettingItem>
              <SettingItem label="应用使用情况访问" description="允许 Aveline 读取您的应用使用时间数据（用于数字健康分析）">
                <button
                  onClick={requestUsageStats}
                  className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white transition-colors"
                >
                  授权访问
                </button>
              </SettingItem>
            </div>
          </div>
        );
      case 'appearance':
        return (
          <div className="space-y-6">
            <SectionTitle><Palette size={20} /> 外观与个性化</SectionTitle>
            <div className="space-y-3">
              <SettingItem label="深色模式" description="使用深色主题以保护视力">
                <Toggle checked={darkMode} onChange={setDarkMode} />
              </SettingItem>
              <SettingItem label="界面缩放" description="调整界面元素的大小">
                <input type="range" className="accent-primary-500 w-32" />
              </SettingItem>
              <SettingItem label="背景模糊强度" description="调整窗口背景的模糊程度">
                <input type="range" className="accent-primary-500 w-32" />
              </SettingItem>
            </div>
          </div>
        );
      case 'network':
        return (
          <div className="space-y-6">
            <SectionTitle><Globe size={20} /> 网络连接</SectionTitle>
            <div className="space-y-4">
              <div className="bg-black/20 border border-white/5 rounded-xl p-5 space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-white/80">后端 API 地址</label>
                  <div className="flex gap-2">
                    <input 
                      type="text" 
                      value={apiUrl}
                      onChange={(e) => setApiUrl(e.target.value)}
                      placeholder="http://192.168.1.100:8000"
                      className="flex-1 bg-black/40 border border-white/10 rounded-lg px-4 py-2 text-sm text-white outline-none focus:border-primary-500 transition-colors"
                    />
                    <button 
                      onClick={testConnection}
                      disabled={testStatus === 'testing'}
                      className={`px-4 py-2 rounded-lg text-xs font-medium transition-all ${
                        testStatus === 'success' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                        testStatus === 'error' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                        'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                      }`}
                    >
                      {testStatus === 'testing' ? '测试中...' : 
                       testStatus === 'success' ? '连接成功' : 
                       testStatus === 'error' ? '连接失败' : '测试连接'}
                    </button>
                  </div>
                  <p className="text-xs text-white/40">
                    输入 Aveline Core 后端服务的完整地址（包含协议和端口）。移动端使用时，请确保手机与服务器在同一局域网内。
                  </p>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-white/80">访问令牌 (Access Token)</label>
                  <input 
                    type="password" 
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    placeholder="请输入安全令牌"
                    className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2 text-sm text-white outline-none focus:border-primary-500 transition-colors"
                  />
                  <p className="text-xs text-white/40">
                    如果后端开启了安全校验，请在此输入对应的令牌。默认令牌通常在 .env 文件中配置。
                  </p>
                </div>
                
                <div className="pt-2">
                  <button 
                    onClick={handleSaveApiUrl}
                    className="w-full bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium py-2.5 rounded-lg transition-all shadow-lg shadow-primary-900/20"
                  >
                    保存并应用配置
                  </button>
                </div>
              </div>

              <div className="bg-primary-500/5 border border-primary-500/10 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <div className="p-2 bg-primary-500/10 rounded-lg text-primary-400">
                    <Shield size={16} />
                  </div>
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-primary-300">连接提示</div>
                    <p className="text-xs text-primary-400/70 leading-relaxed">
                      如果是本地运行，通常地址为 <code className="bg-black/30 px-1 rounded">http://localhost:8000</code>。<br/>
                      如果是局域网访问，请使用服务器的内网 IP 地址。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      case 'model':
        const localModels = modelList.filter(m => m.category !== 'cloud');
        const cloudModels = modelList.filter(m => m.category === 'cloud');
        const isCurrent = (m: any) => {
           if (!currentModel) return false;
           // Check match by name or path
           if (currentModel.model === m.name) return true;
           if (currentModel.path === m.path) return true;
           // 支持新的模型路径格式 cloud:provider:key_alias:model
           if (m.path && currentModel.path) {
             // 解析两个路径进行比较
             const mParts = m.path.split(':');
             const cParts = currentModel.path.split(':');
             
             // 如果都是cloud路径，比较provider和model
             if (mParts[0] === 'cloud' && cParts[0] === 'cloud') {
               const mProvider = mParts[1] || '';
               const cProvider = cParts[1] || '';
               const mModel = mParts.length >= 4 ? mParts[3] : mParts[2] || '';
               const cModel = cParts.length >= 4 ? cParts[3] : cParts[2] || '';
               
               // 如果provider相同，检查model是否匹配
               if (mProvider === cProvider) {
                 if (mModel === cModel) return true;
                 // 检查当前model是否是路径的一部分
                 if (mModel && cModel && mModel.includes(cModel)) return true;
               }
             }
           }
           // Check if current.model is part of cloud path (e.g. cloud:siliconflow:deepseek-ai/DeepSeek-V3.2)
           if (m.path && m.path.includes(currentModel.model)) return true;
           return false;
        };

        return (
          <div className="space-y-6">
            <SectionTitle><Cpu size={20} /> 模型配置</SectionTitle>
            <div className="space-y-4">
              
              {/* DeepSeek Thinking Mode Toggle */}
              {(() => {
                const deepseekV3 = cloudModels.find(m => m.name === 'DeepSeek-V3.2');
                const deepseekR1 = cloudModels.find(m => m.name === 'DeepSeek-R1');
                const isDeepSeekActive = currentModel && (currentModel.model === 'deepseek-chat' || currentModel.model === 'deepseek-reasoner');
                const isThinkingMode = currentModel?.model === 'deepseek-reasoner';

                if (deepseekV3 && deepseekR1) {
                  return (
                    <div className={`transition-all duration-300 mb-2 ${isDeepSeekActive ? 'opacity-100' : 'opacity-60 hover:opacity-100'}`}>
                      <div className={`group border rounded-xl p-4 transition-all duration-300 ${
                        isDeepSeekActive 
                          ? 'bg-gradient-to-r from-primary-900/40 to-black/40 border-primary-500/30' 
                          : 'bg-black/20 border-white/5'
                      }`}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <div className={`p-2.5 rounded-lg transition-colors ${
                              isThinkingMode 
                                ? 'bg-primary-500 text-white shadow-lg shadow-primary-500/20' 
                                : 'bg-white/5 text-white/40 group-hover:bg-white/10 group-hover:text-white/60'
                            }`}>
                              <Brain size={24} />
                            </div>
                            <div className="space-y-1">
                              <div className={`font-medium transition-colors ${isDeepSeekActive ? 'text-white' : 'text-white/70'}`}>
                                深度思考模式 (Deep Thinking)
                              </div>
                              <div className="text-xs text-white/40">
                                {isThinkingMode 
                                  ? '正在使用 DeepSeek-R1 模型进行深度推理与思考' 
                                  : '启用后将切换至 DeepSeek-R1 模型以获得更强的逻辑推理能力'}
                              </div>
                            </div>
                          </div>
                          <Toggle 
                            checked={isThinkingMode} 
                            onChange={(checked) => {
                              const target = checked ? deepseekR1 : deepseekV3;
                              if (target) handleSwitchModel(target);
                            }} 
                          />
                        </div>
                      </div>
                    </div>
                  );
                }
                return null;
              })()}

              {/* Cloud Models */}
              <div className="space-y-2">
                <div className="text-xs font-semibold text-white/40 uppercase tracking-wider flex items-center gap-2">
                  <Cloud size={12} /> 云端模型 (Cloud)
                </div>
                {loadingModels ? (
                    <div className="text-xs text-white/30 px-2">加载中...</div>
                ) : (
                    <div className="grid grid-cols-1 gap-2">
                    {cloudModels.map(model => (
                        <button
                        key={model.name}
                        onClick={() => handleSwitchModel(model)}
                        className={`flex items-center justify-between p-3 rounded-xl border transition-all text-left ${
                            isCurrent(model) 
                            ? 'bg-primary-500/20 border-primary-500/50 text-white' 
                            : 'bg-black/20 border-white/5 text-white/60 hover:bg-black/40 hover:text-white'
                        }`}
                        >
                        <div className="flex flex-col items-start overflow-hidden">
                            <span className="font-medium text-sm truncate w-full">{model.name}</span>
                            <span className="text-[10px] opacity-40 truncate w-full">{model.id}</span>
                        </div>
                        {isCurrent(model) && <Check size={16} className="text-primary-400 shrink-0 ml-2" />}
                        </button>
                    ))}
                    {cloudModels.length === 0 && <div className="text-xs text-white/20 px-2">未检测到云端模型 (请配置 API Key)</div>}
                    </div>
                )}
              </div>

              {/* Local Models */}
              <div className="space-y-2 pt-2">
                 <div className="text-xs font-semibold text-white/40 uppercase tracking-wider flex items-center gap-2">
                  <HardDrive size={12} /> 本地模型 (Local)
                </div>
                {loadingModels ? (
                    <div className="text-xs text-white/30 px-2">加载中...</div>
                ) : (
                    <div className="grid grid-cols-1 gap-2">
                    {localModels.map(model => (
                        <button
                        key={model.name}
                        onClick={() => handleSwitchModel(model)}
                        className={`flex items-center justify-between p-3 rounded-xl border transition-all text-left ${
                            isCurrent(model) 
                            ? 'bg-primary-500/20 border-primary-500/50 text-white' 
                            : 'bg-black/20 border-white/5 text-white/60 hover:bg-black/40 hover:text-white'
                        }`}
                        >
                        <div className="flex flex-col items-start overflow-hidden">
                            <span className="font-medium text-sm truncate w-full">{model.name}</span>
                            <span className="text-[10px] opacity-40 truncate w-full">{model.path}</span>
                        </div>
                        {isCurrent(model) && <Check size={16} className="text-primary-400 shrink-0 ml-2" />}
                        </button>
                    ))}
                    {localModels.length === 0 && <div className="text-xs text-white/20 px-2">未检测到本地模型</div>}
                    </div>
                )}
              </div>

              <SettingItem label="流式响应" description="像打字机一样逐步显示回复">
                <Toggle checked={streamResponse} onChange={setStreamResponse} />
              </SettingItem>
              <SettingItem label="上下文长度限制" description="调整模型记忆的对话长度">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-white/60">4K</span>
                  <input type="range" className="accent-primary-500 w-24" />
                  <span className="text-xs text-white/60">32K</span>
                </div>
              </SettingItem>
            </div>
          </div>
        );
      case 'voice':
        return (
          <div className="space-y-6">
            <SectionTitle><Volume2 size={20} /> 语音与音效</SectionTitle>
            <div className="space-y-3">
              <SettingItem label="界面音效" description="点击按钮时的反馈音效">
                <Toggle checked={soundEffects} onChange={setSoundEffects} />
              </SettingItem>
              <SettingItem label="TTS 语音合成" description="启用语音回复">
                <Toggle checked={true} onChange={() => {}} />
              </SettingItem>
            </div>
          </div>
        );
      default:
        return <div className="text-white/40 text-center py-20">该模块正在开发中...</div>;
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-5xl h-[80vh] bg-[#0a0a0f]/90 backdrop-blur-2xl border border-white/10 rounded-2xl shadow-2xl flex overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Sidebar */}
        <div className="w-64 bg-black/20 border-r border-white/5 p-4 flex flex-col">
          <div className="mb-8 px-2 pt-2">
            <h2 className="text-xl font-light tracking-widest text-white font-[Cinzel]">SETTINGS</h2>
            <div className="text-[10px] text-white/30 uppercase tracking-[0.2em] mt-1">System Configuration</div>
          </div>
          
          <div className="flex-1 space-y-1 overflow-y-auto no-scrollbar">
            <div className="px-3 py-2 text-xs font-semibold text-white/30 uppercase tracking-wider mb-1">System</div>
            <SettingsTab icon={Monitor} label="通用" isActive={activeTab === 'general'} onClick={() => setActiveTab('general')} />
            <SettingsTab icon={Palette} label="外观" isActive={activeTab === 'appearance'} onClick={() => setActiveTab('appearance')} />
            <SettingsTab icon={Volume2} label="语音" isActive={activeTab === 'voice'} onClick={() => setActiveTab('voice')} />
            <SettingsTab icon={Globe} label="网络" isActive={activeTab === 'network'} onClick={() => setActiveTab('network')} />
            
            <div className="px-3 py-2 text-xs font-semibold text-white/30 uppercase tracking-wider mt-6 mb-1">Intelligence</div>
            <SettingsTab icon={Cpu} label="模型" isActive={activeTab === 'model'} onClick={() => setActiveTab('model')} />
            <SettingsTab icon={User} label="人格" isActive={activeTab === 'persona'} onClick={() => setActiveTab('persona')} />
            <SettingsTab icon={Database} label="记忆" isActive={activeTab === 'memory'} onClick={() => setActiveTab('memory')} />
            
            <div className="px-3 py-2 text-xs font-semibold text-white/30 uppercase tracking-wider mt-6 mb-1">About</div>
            <SettingsTab icon={Shield} label="隐私" isActive={activeTab === 'privacy'} onClick={() => setActiveTab('privacy')} />
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 bg-white/5 p-8 overflow-y-auto custom-scrollbar">
          <div className="max-w-3xl mx-auto">
            {renderContent()}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
