import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmText?: string;
  cancelText?: string;
  type?: 'danger' | 'info' | 'warning';
  showCancel?: boolean;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  onConfirm,
  onCancel,
  confirmText = "Confirm",
  cancelText = "Cancel",
  type = 'danger',
  showCancel = true
}) => {
  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center px-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onCancel}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            className="relative w-full max-w-sm bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="p-6 text-center">
              <div className={`w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4 ${
                type === 'danger' ? 'bg-rose-500/10' : 
                type === 'warning' ? 'bg-amber-500/10' : 'bg-blue-500/10'
              }`}>
                <AlertTriangle className={
                  type === 'danger' ? 'text-rose-500' : 
                  type === 'warning' ? 'text-amber-500' : 'text-blue-500'
                } size={24} />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">{title}</h3>
              <p className="text-sm text-white/60 mb-6 leading-relaxed">
                {message}
              </p>
              
              <div className="flex gap-3">
                {showCancel && (
                  <button
                    onClick={onCancel}
                    className="flex-1 py-3 px-4 rounded-xl bg-white/5 hover:bg-white/10 text-white/60 font-medium text-sm transition-colors"
                  >
                    {cancelText}
                  </button>
                )}
                <button
                  onClick={onConfirm}
                  className={`flex-1 py-3 px-4 rounded-xl text-white font-bold text-sm transition-colors shadow-lg ${
                    type === 'danger' ? 'bg-rose-500 hover:bg-rose-600 shadow-rose-500/20' : 
                    type === 'warning' ? 'bg-amber-500 hover:bg-amber-600 shadow-amber-500/20 text-black' : 
                    'bg-blue-500 hover:bg-blue-600 shadow-blue-500/20'
                  }`}
                >
                  {confirmText}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
