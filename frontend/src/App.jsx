import { useEffect, useState } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { AnimatePresence, MotionConfig, motion } from 'framer-motion';
import Sidebar from './components/layout/Sidebar';
import TopBar from './components/layout/TopBar';
import MapMissing from './components/layout/MapMissing';
import { LiveProvider } from './hooks/live';
import { ToastProvider } from './hooks/toast';
import { NetworkProvider } from './hooks/network';
import { ConfirmProvider } from './hooks/confirm';
import { api } from './api/client';
import LiveMapPage from './pages/LiveMapPage';
import DispatchPage from './pages/DispatchPage';
import OrdersPage from './pages/OrdersPage';
import FleetPage from './pages/FleetPage';
import AnalyticsPage from './pages/AnalyticsPage';
import LabPage from './pages/LabPage';

function useHealth() {
  const [health, setHealth] = useState(null);
  const check = () => api.get('/health').then(setHealth).catch((e) => setHealth({ ready: false, error: null, offline: e.message }));
  useEffect(() => {
    check();
    const t = setInterval(() => { if (!health?.ready) check(); }, 3000);
    return () => clearInterval(t);
  }, [health?.ready]); // eslint-disable-line react-hooks/exhaustive-deps
  return [health, check];
}

export default function App() {
  const location = useLocation();
  const [health, recheck] = useHealth();
  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <ConfirmProvider>
          {health?.error ? <MapMissing error={health.error} onRetry={recheck} /> : (
            <LiveProvider>
              <NetworkProvider>
                <div className="flex h-full">
                  <Sidebar />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <TopBar />
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.main key={location.pathname} className="relative min-h-0 flex-1 overflow-hidden"
                        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                        transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}>
                        <Routes location={location}>
                          <Route path="/" element={<LiveMapPage />} />
                          <Route path="/dispatch" element={<DispatchPage />} />
                          <Route path="/orders" element={<OrdersPage />} />
                          <Route path="/fleet" element={<FleetPage />} />
                          <Route path="/analytics" element={<AnalyticsPage />} />
                          <Route path="/lab" element={<LabPage />} />
                        </Routes>
                      </motion.main>
                    </AnimatePresence>
                  </div>
                </div>
              </NetworkProvider>
            </LiveProvider>
          )}
        </ConfirmProvider>
      </ToastProvider>
    </MotionConfig>
  );
}
