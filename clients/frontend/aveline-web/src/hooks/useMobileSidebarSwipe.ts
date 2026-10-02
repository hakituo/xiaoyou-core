import { useCallback, useRef } from 'react';
import type { TouchEvent } from 'react';

type MobileSidebarSwipeOptions = {
  showSidebar: boolean;
  showSettings: boolean;
  onOpenSidebar: () => void;
  onCloseSidebar: () => void;
};

export function useMobileSidebarSwipe({
  showSidebar,
  showSettings,
  onOpenSidebar,
  onCloseSidebar,
}: MobileSidebarSwipeOptions) {
  const swipeStartXRef = useRef<number | null>(null);
  const swipeStartYRef = useRef<number | null>(null);
  const swipeEdgeActiveRef = useRef(false);
  const sidebarSwipeStartXRef = useRef<number | null>(null);
  const sidebarSwipeStartYRef = useRef<number | null>(null);

  const onAppTouchStart = useCallback((e: TouchEvent) => {
    if (showSidebar || showSettings) return;
    const t = e.touches?.[0];
    if (!t) return;
    swipeStartXRef.current = t.clientX;
    swipeStartYRef.current = t.clientY;
    swipeEdgeActiveRef.current = true;
  }, [showSidebar, showSettings]);

  const onAppTouchMove = useCallback((e: TouchEvent) => {
    if (showSidebar || showSettings) return;
    if (!swipeEdgeActiveRef.current) return;
    const t = e.touches?.[0];
    if (!t) return;
    const startX = swipeStartXRef.current;
    const startY = swipeStartYRef.current;
    if (startX == null || startY == null) return;
    const dx = t.clientX - startX;
    const dy = t.clientY - startY;
    if (dx > 70 && Math.abs(dy) < 40) {
      swipeEdgeActiveRef.current = false;
      swipeStartXRef.current = null;
      swipeStartYRef.current = null;
      onOpenSidebar();
    }
  }, [showSidebar, showSettings, onOpenSidebar]);

  const onAppTouchEnd = useCallback(() => {
    swipeEdgeActiveRef.current = false;
    swipeStartXRef.current = null;
    swipeStartYRef.current = null;
  }, []);

  const onSidebarTouchStart = useCallback((e: TouchEvent) => {
    const t = e.touches?.[0];
    if (!t) return;
    sidebarSwipeStartXRef.current = t.clientX;
    sidebarSwipeStartYRef.current = t.clientY;
  }, []);

  const onSidebarTouchMove = useCallback((e: TouchEvent) => {
    const t = e.touches?.[0];
    if (!t) return;
    const startX = sidebarSwipeStartXRef.current;
    const startY = sidebarSwipeStartYRef.current;
    if (startX == null || startY == null) return;
    const dx = t.clientX - startX;
    const dy = t.clientY - startY;
    if (dx < -70 && Math.abs(dy) < 40) {
      sidebarSwipeStartXRef.current = null;
      sidebarSwipeStartYRef.current = null;
      onCloseSidebar();
    }
  }, [onCloseSidebar]);

  const onSidebarTouchEnd = useCallback(() => {
    sidebarSwipeStartXRef.current = null;
    sidebarSwipeStartYRef.current = null;
  }, []);

  return {
    onAppTouchStart,
    onAppTouchMove,
    onAppTouchEnd,
    onSidebarTouchStart,
    onSidebarTouchMove,
    onSidebarTouchEnd,
  };
}
