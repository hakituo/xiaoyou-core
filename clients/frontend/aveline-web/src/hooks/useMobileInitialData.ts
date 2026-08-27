import { useEffect } from 'react';
import { api } from '../api/apiService';

type MobileInitialDataOptions = {
  setVoices: (voices: any[]) => void;
  setSelectedVoiceId: (id: string) => void;
  setPersona: (persona: any) => void;
  setLifeStatus: (status: any) => void;
};

export function useMobileInitialData({
  setVoices,
  setSelectedVoiceId,
  setPersona,
  setLifeStatus,
}: MobileInitialDataOptions) {
  useEffect(() => {
    api.listVoices({ silent: true }).then((res: any) => {
      const list = res?.data?.voices || [];
      setVoices(list);
      if (list.length > 0) setSelectedVoiceId(String(list[0].id));
    }).catch(() => {});

    api.getCurrentPersona().then((res: any) => {
      if (res?.data) {
        setPersona(res.data);
      }
    }).catch(() => {});

    const fetchLifeStatus = () => {
      api.getLifeStatus({ silent: true }).then((res: any) => {
        if (res?.status === 'success' && res.data) {
          setLifeStatus(res.data);
        }
      }).catch(() => {});
    };

    fetchLifeStatus();
    const statusInterval = setInterval(fetchLifeStatus, 5000);

    return () => {
      clearInterval(statusInterval);
    };
  }, [setVoices, setSelectedVoiceId, setPersona, setLifeStatus]);
}
