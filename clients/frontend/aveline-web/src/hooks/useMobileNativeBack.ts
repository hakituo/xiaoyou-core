import { useEffect } from 'react';

type MobileNativeBackOptions = {
  showSettings: boolean;
  showSidebar: boolean;
  activeTab: string;
  setShowSettings: (value: boolean) => void;
  setShowSidebar: (value: boolean) => void;
  setActiveTab: (value: string) => void;
};

export function useMobileNativeBack({
  showSettings,
  showSidebar,
  activeTab,
  setShowSettings,
  setShowSidebar,
  setActiveTab,
}: MobileNativeBackOptions) {
  useEffect(() => {
    (window as any).handleNativeBack = () => {
      if (showSettings) {
        setShowSettings(false);
        return true;
      }

      if (showSidebar) {
        setShowSidebar(false);
        return true;
      }

      if (activeTab !== 'Chat') {
        setActiveTab('Chat');
        return true;
      }

      return false;
    };

    return () => {
      delete (window as any).handleNativeBack;
    };
  }, [showSidebar, activeTab, showSettings, setShowSettings, setShowSidebar, setActiveTab]);
}
