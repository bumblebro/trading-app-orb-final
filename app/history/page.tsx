'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Trade } from '@/lib/types';

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [yearlyStats, setYearlyStats] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modeFilter, setModeFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    api.getBotStatus().then(status => {
      if (status?.mode) setModeFilter(prev => prev !== status.mode ? status.mode : prev);
    }).catch(() => {});
  }, []);

  // Stable fetch function
  const fetchTrades = useCallback(async (isInitial = false) => {
    try {
      if (isInitial) setLoading(true);
      console.log(`[Frontend] Fetching trades:`, { mode: modeFilter, dateFrom, dateTo });
      const data = await api.getTrades({ 
        mode: modeFilter, 
        date_from: dateFrom, 
        date_to: dateTo 
      });
      console.log(`[Frontend] Got trades:`, data?.trades?.length);
      setTrades(data?.trades || []);
      setSummary(data?.summary || null);
      setYearlyStats(data?.yearly_summary || []);
      setError(null);
    } catch (err: any) {
      console.error('[Frontend] Error:', err);
      setError(err.message || 'Failed to fetch trades');
    } finally {
      setLoading(false);
    }
  }, [modeFilter, dateFrom, dateTo]);

  // Initial fetch and interval
  useEffect(() => {
    fetchTrades(true);
    const interval = setInterval(() => fetchTrades(false), 5000); // 5s to be safer
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modeFilter, dateFrom, dateTo]);

  const totalTrades = summary?.all_time_trades ?? trades.filter(t => t.status !== 'open').length;
  const wins = summary?.wins ?? trades.filter(t => t.status === 'win').length;
  const losses = summary?.losses ?? trades.filter(t => t.status === 'loss').length;
  const totalNetPnl = summary?.all_time_pnl ?? trades.reduce((sum, t) => sum + (t.net_pnl || t.pnl || 0), 0);
  const totalGrossPnl = summary?.all_time_gross_pnl ?? trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const totalCharges = summary?.all_time_charges ?? (totalGrossPnl - totalNetPnl);
  const winRate = summary?.all_time_win_rate ?? (totalTrades > 0 ? (wins / totalTrades * 100) : 0);

  // Yearly stats are now provided directly by the API to ensure synchronization with all-time data
  // and are stored in the yearlyStats state.

  if (!mounted) return (
    <div className="page-container flex items-center justify-center p-32">
      <span className="animate-pulse text-gray-500">Initializing...</span>
    </div>
  );

  return (
    <div className="page-container">
      <h1 className="page-title">📋 Trade History</h1>

      {/* Filters */}
      <div className="history-controls">
        <input
          type="date"
          className="filter-input"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          placeholder="From date"
        />
        <input
          type="date"
          className="filter-input"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          placeholder="To date"
        />
        <select
          className="filter-select"
          value={modeFilter}
          onChange={(e) => setModeFilter(e.target.value)}
        >
          <option value="">All Modes</option>
          <option value="paper">Paper Trades</option>
          <option value="live">Live Trades</option>
        </select>
        
        <button 
          className="copy-btn ml-auto"
          onClick={() => {
            const yearlyHeaders = ['Year', 'Yearly P&L', 'Trades', 'Win Rate%', 'ROI %', 'Profit Factor'];
            const yearlyRows = yearlyStats.map(s => {
               const pf = s.gross_loss > 0 ? (s.gross_profit / s.gross_loss) : (s.gross_profit > 0 ? 'Inf' : '0');
               const roi = s.starting_capital > 0 ? (s.pnl / s.starting_capital * 100) : 0;
               return [
                 s.year, 
                 s.pnl.toFixed(2), 
                 s.trades, 
                 (s.wins + s.losses > 0 ? (s.wins / (s.wins + s.losses) * 100).toFixed(1) : '0'),
                 roi.toFixed(1) + '%',
                 typeof pf === 'number' ? pf.toFixed(2) : pf
               ];
            });
            
            const headers = ['Date', 'Entry', 'Exit', 'Type', 'Strike', 'Entry Price', 'Exit Price', 'Qty', 'Capital Used', 'Cap %', 'Gross P&L', 'Charges', 'Net P&L', 'Status', 'Reason', 'ST_Entry', 'ADX_Entry'];
            const rows = trades.map(t => {
              const capUsedPct = t.capital_used && t.total_capital ? ((t.capital_used / t.total_capital) * 100).toFixed(1) + '%' : '—';
              const charges = (t.brokerage || 0) + (t.stt || 0) + (t.exc_charges || 0) + (t.gst || 0);
              const netPnl = t.net_pnl ?? (t.status !== 'open' ? (t.pnl - charges) : 0);
              return [
                t.date, t.time, t.exit_time || '', t.type, t.strike_price, t.entry_price, t.exit_price || '',
                t.quantity, t.capital_used || 0, capUsedPct, t.pnl, charges.toFixed(2), netPnl.toFixed(2), t.status, t.exit_reason || '', 
                t.supertrend_at_entry || '', t.adx_at_entry || ''
              ];
            });
            
            const csv = [
              ['OVERALL PERFORMANCE SUMMARY'],
              ['Total Gross P&L', 'Total Charges', 'Total Net P&L', 'Total Trades', 'Wins', 'Losses', 'Win Rate%'],
              [totalGrossPnl.toFixed(2), totalCharges.toFixed(2), totalNetPnl.toFixed(2), totalTrades, wins, losses, winRate.toFixed(1)],
              [],
              ['YEARLY PERFORMANCE SUMMARY'],
              yearlyHeaders,
              ...yearlyRows,
              [],
              ['DETAILED TRADE LOGS'],
              headers, 
              ...rows
            ].map(e => e.join(",")).join("\n");
            navigator.clipboard.writeText(csv);
            alert('Full trade history with yearly summary and advanced metrics copied to clipboard!');
          }}
        >
          📋 Copy all history
        </button>
      </div>

      {/* P&L Summary at Top */}
      {!loading && trades.length > 0 && (
        <div className="pnl-summary-top">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Net Performance (After Charges)</span>
            <span 
              className="text-2xl font-bold"
              style={{ color: totalNetPnl >= 0 ? 'var(--green)' : 'var(--red)', fontFamily: "'JetBrains Mono', monospace" }}
            >
              {totalNetPnl >= 0 ? '+' : ''}₹{totalNetPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
            <div className="flex items-center gap-2 mt-1">
               <span className="text-[10px] text-gray-400">Gross: ₹{totalGrossPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
               <span className="text-[10px] text-gray-600">|</span>
               <span className="text-[10px] text-red-500/70">Charges: ₹{totalCharges.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
            </div>
          </div>
          <div className="flex items-center gap-6 ml-auto bg-black/20 p-4 rounded-xl border border-white/5">
            <div className="summary-stat">
              <span className="label">Trades</span>
              <span className="value">{totalTrades}</span>
            </div>
            <div className="summary-stat">
              <span className="label text-green-500">Wins</span>
              <span className="value text-green-500">{wins}</span>
            </div>
            <div className="summary-stat">
              <span className="label text-red-500">Losses</span>
              <span className="value text-red-500">{losses}</span>
            </div>
            <div className="divider mx-2 w-[1px] h-8 bg-white/10"></div>
            <div className="summary-stat">
              <span className="label">Win Rate</span>
              <span className="value text-cyan-400">{winRate.toFixed(1)}%</span>
            </div>
          </div>
          <div className="yearly-stats-container">
            {yearlyStats.map(stat => (
              <div key={stat.year} className="yearly-stat-card border border-white/5 bg-white/5 rounded-lg p-3">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Year {stat.year}</span>
                  <span className={`text-xs font-bold ${stat.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {stat.pnl >= 0 ? '+' : ''}₹{stat.pnl.toLocaleString('en-IN', { minimumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="flex gap-4">
                   <div className="flex flex-col">
                     <span className="text-[9px] text-gray-500 uppercase">Trades</span>
                     <span className="text-sm font-bold">{stat.trades}</span>
                   </div>
                   <div className="flex flex-col">
                     <span className="text-[9px] text-gray-500 uppercase">Win Rate</span>
                     <span className="text-sm font-bold text-cyan-400">
                       {(stat.wins + stat.losses > 0 ? (stat.wins / (stat.wins + stat.losses) * 100) : 0).toFixed(1)}%
                     </span>
                   </div>
                   <div className="flex flex-col">
                     <span className="text-[9px] text-gray-500 uppercase">ROI %</span>
                     <span className={`text-sm font-bold ${stat.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                       {(stat.starting_capital > 0 ? (stat.pnl / stat.starting_capital * 100) : 0).toFixed(1)}%
                     </span>
                   </div>
                   <div className="flex flex-col">
                     <span className="text-[9px] text-gray-500 uppercase">P. Factor</span>
                     <span className="text-sm font-bold text-yellow-500">
                       {(stat.gross_loss > 0 ? (stat.gross_profit / stat.gross_loss) : (stat.gross_profit > 0 ? '∞' : '0')).toLocaleString()}
                     </span>
                   </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-500/50 text-red-200 p-4 rounded-xl mb-6 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="text-xl">⚠️</span>
            <span>{error}</span>
          </div>
          <button 
            onClick={() => fetchTrades(true)}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg text-sm flex items-center gap-2 transition-colors"
          >
            🔄 Refresh
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center p-32 text-gray-500">
           <span className="animate-pulse">Loading trade data...</span>
        </div>
      ) : (
        <div className="trades-table-container">
          <table className="trades-table">
            <thead>
              <tr>
                <th>Date / Time</th>
                <th>Type</th>
                <th>Strike</th>
                <th>Entry ST</th>
                <th>Entry ADX</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Qty</th>
                <th>Cap %</th>
                <th>Gross P&L</th>
                <th>Charges</th>
                <th>Net P&L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={12} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                    No trades found
                  </td>
                </tr>
              ) : (
                trades.map((trade) => (
                  <tr key={trade.id}>
                    <td>
                      <div className="flex flex-col">
                        <span className="font-bold">{trade.date}</span>
                        <div className="flex items-center gap-1 text-[10px] text-gray-500">
                           <span>{trade.time}</span>
                           {trade.exit_time && (
                             <>
                               <span className="text-gray-700">→</span>
                               <span>{trade.exit_time}</span>
                             </>
                           )}
                        </div>
                      </div>
                    </td>
                    <td style={{ color: trade.type === 'CE' ? 'var(--green)' : 'var(--red)', fontWeight: 800 }}>
                      {trade.type}
                    </td>
                    <td>{trade.strike_price}</td>
                    <td className="text-cyan-400">₹{typeof trade.supertrend_at_entry === 'number' ? trade.supertrend_at_entry.toFixed(2) : '—'}</td>
                    <td className="text-yellow-500">{typeof trade.adx_at_entry === 'number' ? trade.adx_at_entry.toFixed(1) : '—'}</td>
                    <td className="font-bold">₹{typeof trade.entry_price === 'number' ? trade.entry_price.toFixed(2) : '—'}</td>
                    <td>{typeof trade.exit_price === 'number' ? `₹${trade.exit_price.toFixed(2)}` : '—'}</td>
                    <td>
                      <div className="flex flex-col">
                        <span>{trade.quantity}</span>
                        <span className="text-[10px] text-gray-400">{trade.capital_used?.toLocaleString('en-IN') || '—'}</span>
                      </div>
                    </td>
                    <td className="text-gray-500 text-[11px]">
                      {trade.capital_used && trade.total_capital ? 
                        ((trade.capital_used / trade.total_capital) * 100).toFixed(1) + '%' : 
                        '—'}
                    </td>
                    <td className={`text-[12px] ${trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {trade.status !== 'open' ? `${trade.pnl >= 0 ? '+' : ''}₹${trade.pnl.toLocaleString('en-IN', { minimumFractionDigits: 0 })}` : '—'}
                    </td>
                    <td className="text-[11px] text-red-400/80">
                      {trade.status !== 'open' ? `₹${((trade.brokerage||0)+(trade.stt||0)+(trade.exc_charges||0)+(trade.gst||0)).toFixed(2)}` : '—'}
                    </td>
                    <td className={`font-bold ${ (trade.net_pnl ?? trade.pnl) >= 0 ? 'win' : 'loss'}`}>
                      {trade.status !== 'open' ? `${(trade.net_pnl ?? trade.pnl) >= 0 ? '+' : ''}₹${(trade.net_pnl ?? trade.pnl).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                    </td>
                    <td>
                      <div className="flex flex-col gap-1 items-center">
                        <span className={`status-badge ${ (trade.net_pnl ?? trade.pnl) >= 0 ? 'win' : 'loss'}`}>
                          {trade.status === 'open' ? 'open' : ((trade.net_pnl ?? trade.pnl) >= 0 ? 'win' : 'loss')}
                        </span>
                        <span className="text-[9px] uppercase text-gray-500 whitespace-nowrap">{trade.exit_reason || 'open'}</span>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
      
      <style jsx>{`
        .status-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.65rem;
          font-weight: 800;
          text-transform: uppercase;
        }
        .status-badge.win { background: #064e3b; color: #34d399; }
        .status-badge.loss { background: #450a0a; color: #f87171; }
        .status-badge.open { background: #1e3a8a; color: #93c5fd; }
        
        .summary-stat {
          display: flex;
          flex-direction: column;
        }
        .summary-stat .label {
          font-size: 0.65rem;
          font-weight: 700;
          text-transform: uppercase;
          color: var(--text-muted);
        }
        .summary-stat .value {
          font-size: 1.1rem;
          font-weight: 700;
          font-family: 'JetBrains Mono', monospace;
        }

        .pnl-summary-top {
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
          padding: 1.5rem;
          background: linear-gradient(145deg, rgba(20, 20, 20, 0.4), rgba(40, 40, 40, 0.4));
          border: 1px solid var(--border);
          border-radius: 16px;
          margin-bottom: 2rem;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        }

        .yearly-stats-container {
          display: flex;
          gap: 1rem;
          overflow-x: auto;
          padding-bottom: 0.5rem;
        }

        .yearly-stat-card {
          min-width: 140px;
        }

        .copy-btn {
          background: #1e293b;
          border: 1px solid #334155;
          color: #94a3b8;
          padding: 0.5rem 1rem;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }

        .copy-btn:hover {
          background: #334155;
          color: white;
          border-color: #475569;
        }
      `}</style>
    </div>
  );
}
