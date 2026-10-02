import { useEffect } from 'react';

export function useMobileNativeSync() {
  useEffect(() => {
    const savedUrl = localStorage.getItem('AVELINE_API_URL');
    if (savedUrl && (window as any).aveline_native?.setBackendUrl) {
      (window as any).aveline_native.setBackendUrl(savedUrl);
    }

    const fetchVitalSigns = () => {
      if ((window as any).aveline_native?.fetchVitalSigns) {
        (window as any).aveline_native.fetchVitalSigns();
      } else if ((window as any).aveline_native?.fetchHealthData) {
        (window as any).aveline_native.fetchHealthData();
      }
    };

    const fetchBodyMetrics = () => {
      if ((window as any).aveline_native?.fetchBodyMetrics) {
        (window as any).aveline_native.fetchBodyMetrics();
      }
    };

    const initialTimer = setTimeout(() => {
      fetchBodyMetrics();
      setTimeout(fetchVitalSigns, 2000);
    }, 5000);

    const interval = setInterval(fetchVitalSigns, 10 * 60 * 1000);
    const metricsInterval = setInterval(fetchBodyMetrics, 6 * 60 * 60 * 1000);

    return () => {
      clearTimeout(initialTimer);
      clearInterval(interval);
      clearInterval(metricsInterval);
    };
  }, []);
}
