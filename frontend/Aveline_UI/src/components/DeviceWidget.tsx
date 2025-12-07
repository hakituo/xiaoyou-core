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
    <div className="flex items-center gap-3 bg-[#1a1a1a] border border-white/10 rounded-full py-1.5 px-4 shadow-[0_4px_10px_rgba(0,0,0,0.3)]">
      <div className="flex items-center gap-4 text-[10px] font-mono leading-tight text-white/60">
        <div className="flex items-center gap-2">
          <Cpu size={10} /> <span>CPU {cpu}%</span>
        </div>
        <div className="flex items-center gap-2">
          <Zap size={10} /> <span>GPU {gpu}%</span>
        </div>
        <div className="flex items-center gap-2">
          <Activity size={10} /> <span>MEM {memory}%</span>
        </div>
      </div>
    </div>
  );
});

DeviceWidget.displayName = 'DeviceWidget';

export default DeviceWidget;
