import React from 'react';
import { motion } from 'framer-motion';

const TypingIndicator = () => {
  return (
    <div className="flex justify-start">
      <div className="max-w-[25%] p-4 bg-[#18181b]/80 border border-white/5 rounded-[24px] rounded-bl-sm flex items-center justify-center gap-1">
        {Array.from({ length: 3 }).map((_, i) => (
          <motion.div
            key={i}
            className="w-2 h-2 rounded-full bg-white/60"
            animate={{ opacity: [0.5, 1, 0.5], scale: [1, 1.1, 1] }}
            transition={{
                duration: 1.4,
                repeat: Infinity,
                delay: i * 0.3,
                ease: "easeInOut"
            }}
          />
        ))}
      </div>
    </div>
  );
};

export default TypingIndicator;
