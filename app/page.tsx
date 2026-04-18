'use client';

import { useEffect, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import PriceDisplay from '@/components/PriceDisplay';
import SignalCard from '@/components/SignalCard';
import StatsGrid from '@/components/StatsGrid';
import ConnectionStatus from '@/components/ConnectionStatus';
import LogViewer from '@/components/LogViewer';
import TradeModeToggle from '@/components/TradeModeToggle';
import TradeCard from '@/components/TradeCard';
import StrategyFlow from '@/components/StrategyFlow';
import { api } from '@/lib/api';
import type { BotStatus, ChartData, Signal } from '@/lib/types';

// Dynamic import for Chart (client-only, uses Canvas)
const Chart = dynamic(() => import('@/components/Chart'), { ssr: false });

export default function DashboardPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [signalInfo, setSignalInfo] = useState<Signal | null>(null);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, candlesRes, signalRes] = await Promise.all([
        api.getBotStatus(),
        api.getCandles(),
        api.getSignal(),
      ]);
      setStatus(statusRes);
      setChartData(candlesRes);
      setSignalInfo(signalRes);
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
  const phase = status?.phase || 'WATCHING';

  return (
    <>
      <TradeModeToggle mode={mode} onToggle={handleModeToggle} />
      <div className="page-container">
        {loading ? (
          <div className="flex items-center justify-center p-16 text-gray-400">
            <span className="animate-pulse">Loading dashboard...</span>
          </div>
        ) : (
          <>
            <div className="dashboard-grid">
              <div className="dashboard-left">
                {/* Chart Area */}
                <div className="flex flex-col gap-4">
                  <Chart data={chartData} />
                  
                  {/* Info Cards Row */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="stat-info-card">
                       <span className="info-label">ORB RANGE</span>
                       <span className="info-value">{signalInfo?.orb_range?.toFixed(2) || '0.00'} pts</span>
                       <span className={`info-sub ${signalInfo?.orb_status === 'READY' ? 'text-green-500' : 'text-blue-400'}`}>
                         {signalInfo?.orb_status || '--'}
                       </span>
                    </div>
                    <div className="stat-info-card">
                       <span className="info-label">MACD STATUS</span>
                       <span className="info-value">
                         {signalInfo?.macd?.histogram?.toFixed(4) || '0.000'}
                       </span>
                       <span className={`info-sub ${signalInfo?.macd?.is_bullish ? 'text-green-500' : 'text-red-500'}`}>
                         {signalInfo?.macd?.is_bullish ? 'BULLISH' : 'BEARISH'}
                       </span>
                    </div>
                    <div className="stat-info-card">
                       <span className="info-label">BREAKOUT</span>
                       <span className="info-value">
                         {signalInfo?.breakout_price?.toFixed(2) || '---'}
                       </span>
                       <span className={`info-sub ${signalInfo?.breakout_direction === 'UP' ? 'text-green-500' : signalInfo?.breakout_direction === 'DOWN' ? 'text-red-500' : 'text-gray-500'}`}>
                         {signalInfo?.breakout_direction === 'UP' ? 'UPWARD' : signalInfo?.breakout_direction === 'DOWN' ? 'DOWNWARD' : 'WATCHING'}
                       </span>
                    </div>
                  </div>

                  {/* Stats Grid */}
                  <StatsGrid
                    todayPnl={status?.today_pnl || 0}
                    totalTrades={status?.today_trades || 0}
                    winRate={status?.win_rate || 0}
                    wins={status?.wins || 0}
                    losses={status?.losses || 0}
                    totalAllTimePnl={status?.total_pnl || 0}
                    totalAllTimeTrades={status?.total_trades || 0}
                    allTimeWinRate={status?.all_time_win_rate || 0}
                    mode={mode}
                  />
                </div>
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

                {/* Strategy Phase Tracker */}
                <StrategyFlow phase={phase} strategyInfo={signalInfo} />

                {/* Active Trade */}
                <TradeCard 
                  trade={status?.active_trade || null} 
                  currentPrice={(priceInfo as { price?: number }).price} 
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

      <style jsx>{`
        .stat-info-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 1rem;
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }
        .info-label {
          font-size: 0.65rem;
          font-weight: 700;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .info-value {
          font-size: 1.1rem;
          font-family: 'JetBrains Mono', monospace;
          font-weight: 700;
          color: var(--text-primary);
        }
        .info-sub {
          font-size: 0.7rem;
          font-weight: 600;
        }
      `}</style>
    </>
  );
}
