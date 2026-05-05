'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import PriceDisplay from '@/components/PriceDisplay';
import SignalCard from '@/components/SignalCard';
import StatsGrid from '@/components/StatsGrid';
import ConnectionStatus from '@/components/ConnectionStatus';
import LogViewer from '@/components/LogViewer';
import MarginLogViewer from '@/components/MarginLogViewer';
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
  const [mounted, setMounted] = useState(false);
  const isFetching = useRef(false);

  const fetchData = useCallback(async () => {
    if (isFetching.current) return;
    try {
      isFetching.current = true;
      const [statusRes, candlesRes, signalRes] = await Promise.all([
        api.getBotStatus(),
        api.getCandles(),
        api.getSignal(),
      ]);
      setStatus(statusRes);
      setChartData(candlesRes);
      setSignalInfo(signalRes);
    } catch (err) {
      console.error('[Dashboard] Fetch error:', err);
    } finally {
      isFetching.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    fetchData();
    const interval = setInterval(fetchData, 1000); // 1s for real-time feel
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

  if (!mounted) return (
    <div className="page-container flex items-center justify-center p-32">
      <span className="animate-pulse text-gray-500">Initializing Dashboard...</span>
    </div>
  );

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
                  
                  {/* Indicator & Backtest Info Cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {status?.backtest_capital && status.backtest_capital !== (status.initial_capital || 100000) ? (
                      <>
                        <div className="stat-info-card border-cyan-500/20">
                           <span className="info-label text-cyan-400">Backtest Capital</span>
                           <span className="info-value">₹{status.backtest_capital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                           <span className="info-sub text-gray-400 font-mono text-[10px]">
                             📅 {status.backtest_start} → {status.backtest_current} {status.backtest_duration ? `(${status.backtest_duration})` : ''}
                           </span>
                        </div>
                        <div className="stat-info-card border-purple-500/20">
                           <span className="info-label text-purple-400">Total Return</span>
                           <span className="info-value">
                             {(((status.backtest_capital - (status.initial_capital || 100000)) / (status.initial_capital || 100000)) * 100).toFixed(1)}%
                           </span>
                           <span className={`info-sub ${status.compounding_advantage && status.compounding_advantage > 0 ? 'text-green-500' : 'text-gray-500'}`}>
                             Advantage: +₹{status.compounding_advantage?.toLocaleString() || '0'}
                           </span>
                        </div>
                        <div className="stat-info-card">
                           <span className="info-label">Max Drawdown</span>
                           <span className="info-value text-red-400">
                             {/* Calculated purely on capital history */}
                             {status.capital_history && status.capital_history.length > 0 ? 
                               (Math.min(...status.capital_history) < (status.initial_capital || 100000) ? 
                                 ((1 - Math.min(...status.capital_history) / Math.max(...status.capital_history)) * 100).toFixed(1) : '0.0') : '0.0'}%
                           </span>
                           <span className="info-sub text-gray-500">Peak to Trough</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="stat-info-card">
                           <span className="info-label">Supertrend</span>
                           <span className="info-value">{status?.indicators?.supertrend?.toFixed(2) || '0.00'}</span>
                           <span className={`info-sub ${status?.indicators?.supertrend_direction === 1 ? 'text-green-500' : 'text-red-500'}`}>
                             {status?.indicators?.supertrend_direction === 1 ? '🟢 BULLISH TREND' : status?.indicators?.supertrend_direction === -1 ? '🔴 BEARISH TREND' : '--'}
                           </span>
                        </div>
                        <div className="stat-info-card">
                           <span className="info-label">EMA 9 / 21</span>
                           <span className="info-value">
                             {status?.indicators?.ema_short?.toFixed(1) || '0.0'} / {status?.indicators?.ema_long?.toFixed(1) || '0.0'}
                           </span>
                           <span className={`info-sub ${status?.indicators?.ema_short > status?.indicators?.ema_long ? 'text-green-500' : 'text-red-500'}`}>
                             {status?.indicators?.ema_short > status?.indicators?.ema_long ? 'UPWARD CROSS' : 'DOWNWARD CROSS'}
                           </span>
                        </div>
                        <div className="stat-info-card">
                           <span className="info-label">ADX Filter</span>
                           <span className="info-value">
                             {status?.indicators?.adx?.toFixed(1) || '0.0'}
                           </span>
                           <span className={`info-sub ${status?.indicators?.adx > 20 ? 'text-green-400 font-bold' : 'text-yellow-500'}`}>
                             {status?.indicators?.adx > 20 ? '🔥 STRONG TREND' : '❄️ CHOPPY MARKET'}
                           </span>
                        </div>
                      </>
                    )}
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
                    totalAllTimeWins={status?.total_wins || 0}
                    totalAllTimeLosses={status?.total_losses || 0}
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
                  tick_count={(priceInfo as { tick_count?: number }).tick_count}
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

                  <button
                    className="w-full mt-4 py-2 px-4 rounded-xl border border-blue-500/30 bg-blue-500/10 text-blue-400 font-bold hover:bg-blue-500/20 transition-all text-sm flex items-center justify-center gap-2"
                    onClick={async () => {
                        try {
                            const [tradesData, logsData, settingsData] = await Promise.all([
                                api.getTrades({ mode: status?.mode || 'paper' }),
                                api.getLogs(50),
                                api.getSettings()
                            ]);
                            
                            // Sanitize settings (remove secrets)
                            const sanitizedSettings = { ...settingsData.settings };
                            delete sanitizedSettings.api_key;
                            delete sanitizedSettings.pin;
                            delete sanitizedSettings.totp_secret;

                            const report = {
                                export_time: new Date().toLocaleString(),
                                bot_status: {
                                    running: status?.running,
                                    mode: status?.mode,
                                    phase: status?.phase,
                                    signal: status?.signal,
                                    backtest_range: status?.backtest_start ? `${status.backtest_start} to ${status.backtest_current} (${status.backtest_duration})` : 'N/A'
                                },
                                strategy_config: sanitizedSettings,
                                performance: {
                                    today_pnl: status?.today_pnl,
                                    total_pnl: status?.total_pnl,
                                    win_rate: status?.all_time_win_rate,
                                    yearly_breakdown: tradesData.yearly_summary || []
                                },
                                latest_indicators: status?.indicators,
                                active_trade: status?.active_trade,
                                recent_trades: (tradesData.trades || []).slice(0, 50),
                                recent_logs: (logsData.logs || []).slice(0, 30)
                            };
                            
                            await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
                            alert('📑 Trading Intelligence copied to clipboard!');
                        } catch (e) {
                            alert('Failed to copy trading data.');
                        }
                    }}
                  >
                    📋 Copy History for Analysis
                  </button>
                </div>
              </div>
            </div>

            {/* Log Viewers */}
            <LogViewer />
            <MarginLogViewer />
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
