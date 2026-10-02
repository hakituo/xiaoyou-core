import React from 'react';
import { Cpu, Zap, Activity } from 'lucide-react';
import { EmotionType } from '../types';

const DeviceWidget = React.memo(({ 
  cpu, 
  gpu, 
  memory,
  colors,
  emotion 
}: { 
  cpu: number; 
  gpu: number; 
  memory: number;
  colors: [string, string, string, string];
  emotion: EmotionType 
}) => {
  return (
    <div className="flex items-center gap-3 bg-transparent py-1.5 transition-all duration-300 cursor-default">
      <div className="flex items-center gap-4 text-[10px] font-mono leading-tight">
        <div className="flex items-center gap-2 group/cpu">
          <Cpu size={10} className="text-white/30 group-hover/cpu:text-emerald-400 transition-colors duration-300" /> 
          <span className="text-white/40 group-hover/cpu:text-emerald-400/80 transition-colors duration-300">CPU {cpu}%</span>
        </div>
        <div className="flex items-center gap-2 group/gpu">
          <Zap size={10} className="text-white/30 group-hover/gpu:text-amber-400 transition-colors duration-300" /> 
          <span className="text-white/40 group-hover/gpu:text-amber-400/80 transition-colors duration-300">GPU {gpu}%</span>
        </div>
        <div className="flex items-center gap-2 group/mem">
          <Activity size={10} className="text-white/30 group-hover/mem:text-blue-400 transition-colors duration-300" /> 
          <span className="text-white/40 group-hover/mem:text-blue-400/80 transition-colors duration-300">MEM {memory}%</span>
        </div>
      </div>
    </div>
  );
});

DeviceWidget.displayName = 'DeviceWidget';

export default DeviceWidget;
