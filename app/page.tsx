'use client';

import { useEffect, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import PriceDisplay from '@/components/PriceDisplay';
import SignalCard from '@/components/SignalCard';
import StatsGrid from '@/components/StatsGrid';
import ConnectionStatus from '@/components/ConnectionStatus';
import LogViewer from '@/components/LogViewer';
import TradeModeToggle from '@/components/TradeModeToggle';
import { api } from '@/lib/api';
import type { BotStatus, ChartData } from '@/lib/types';

// Dynamic import for Chart (client-only, uses Canvas)
const Chart = dynamic(() => import('@/components/Chart'), { ssr: false });

export default function DashboardPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, candlesRes] = await Promise.all([
        api.getBotStatus(),
        api.getCandles(),
      ]);
      setStatus(statusRes);
      setChartData(candlesRes);
    } catch {
      // Bot server not available
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 1000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleStartStop = async () => {
    try {
      if (status?.running) {
        await api.stopBot();
      } else {
        await api.startBot();
      }
      await fetchData();
    } catch (e) {
      console.error('Bot control error:', e);
    }
  };

  const handleModeToggle = async (newMode: string) => {
    try {
      await api.saveSettings({ trading_mode: newMode });
      await fetchData();
    } catch (e) {
      console.error('Mode toggle error:', e);
    }
  };

  const priceInfo = status?.price || {} as Record<string, unknown>;
  const mode = status?.mode || 'paper';

  return (
    <>
      <TradeModeToggle mode={mode} onToggle={handleModeToggle} />
      <div className="page-container">
        {loading ? (
          <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
            Loading dashboard...
          </div>
        ) : (
          <>
            <div className="dashboard-grid">
              <div className="dashboard-left">
                {/* Chart */}
                <Chart data={chartData} />

                {/* Stats Grid */}
                <StatsGrid
                  todayPnl={status?.today_pnl || 0}
                  totalTrades={status?.today_trades || 0}
                  winRate={status?.win_rate || 0}
                  wins={status?.wins || 0}
                  losses={status?.losses || 0}
                  mode={mode}
                />
              </div>

              <div className="dashboard-right">
                {/* Price Display */}
                <PriceDisplay
                  price={(priceInfo as { price?: number }).price || 0}
                  change={(priceInfo as { change?: number }).change || 0}
                  changePct={(priceInfo as { change_pct?: number }).change_pct || 0}
                  connected={(priceInfo as { connected?: boolean }).connected || false}
                  simulation={(priceInfo as { simulation?: boolean }).simulation || true}
                />

                {/* Signal */}
                <SignalCard signal={status?.signal || 'DISCONNECTED'} />

                {/* Bot Control */}
                <div className="bot-control">
                  <div className="bot-status-indicator">
                    <span className={`bot-dot ${status?.running ? 'running' : 'stopped'}`} />
                    <span className={`bot-status-text ${status?.running ? 'running' : 'stopped'}`}>
                      {status?.running ? 'Running' : 'Stopped'}
                    </span>
                  </div>
                  <ConnectionStatus
                    wsConnected={(priceInfo as { connected?: boolean }).connected || false}
                    botRunning={status?.running || false}
                    marketOpen={status?.market_open || false}
                    marketStatus={status?.market_status || 'Unknown'}
                  />
                  <button
                    className={`bot-btn ${status?.running ? 'stop' : 'start'}`}
                    onClick={handleStartStop}
                  >
                    {status?.running ? '⏹ Stop Bot' : '▶ Start Bot'}
                  </button>
                </div>
              </div>
            </div>

            {/* Log Viewer */}
            <LogViewer />
          </>
        )}
      </div>
    </>
  );
}
