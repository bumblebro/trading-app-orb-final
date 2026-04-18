'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Trade } from '@/lib/types';

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [modeFilter, setModeFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const fetchTrades = useCallback(async () => {
    try {
      const data = await api.getTrades({
        mode: modeFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setTrades(data.trades || []);
    } catch {
      // Bot not connected
    } finally {
      setLoading(false);
    }
  }, [modeFilter, dateFrom, dateTo]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  const totalPnl = trades.reduce((sum, t) => sum + (t.status !== 'open' ? t.pnl : 0), 0);
  const wins = trades.filter(t => t.status === 'win').length;
  const losses = trades.filter(t => t.status === 'loss').length;

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
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-32 text-gray-500">
           <span className="animate-pulse">Loading trade data...</span>
        </div>
      ) : (
        <div className="trades-table-container">
          <table className="trades-table">
            <thead>
              <tr>
                <th>Date/Time</th>
                <th>Type</th>
                <th>Strike</th>
                <th>Breakout</th>
                <th>Fib %</th>
                <th>MACD</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Qty</th>
                <th>P&L</th>
                <th>SL</th>
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
                        <span className="text-[10px] text-gray-500">{trade.time}</span>
                      </div>
                    </td>
                    <td style={{ color: trade.type === 'CE' ? 'var(--green)' : 'var(--red)', fontWeight: 800 }}>
                      {trade.type}
                    </td>
                    <td>{trade.strike_price}</td>
                    <td className="text-cyan-400">₹{trade.breakout_price?.toFixed(2) || '—'}</td>
                    <td className="text-yellow-500">{trade.fib_entry_level || '—'}%</td>
                    <td className={trade.macd_at_entry && trade.macd_at_entry >= 0 ? 'text-green-500' : 'text-red-500'}>
                      {trade.macd_at_entry?.toFixed(4) || '—'}
                    </td>
                    <td className="font-bold">₹{trade.entry_price.toFixed(2)}</td>
                    <td>{trade.exit_price ? `₹${trade.exit_price.toFixed(2)}` : '—'}</td>
                    <td>
                      <div className="flex flex-col">
                        <span>{trade.quantity}</span>
                        <span className="text-[10px] text-gray-500">{trade.mode.toUpperCase()}</span>
                      </div>
                    </td>
                    <td className={`font-bold ${trade.pnl >= 0 ? 'win' : 'loss'}`}>
                      {trade.status !== 'open' ? `${trade.pnl >= 0 ? '+' : ''}₹${trade.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                    </td>
                    <td>
                      <div className="flex flex-col gap-0.5">
                         {trade.trailing_sl_used ? (
                           <span className="text-[8px] bg-purple-500/20 text-purple-400 px-1 rounded border border-purple-500/30 font-bold w-fit">TRAILING</span>
                         ) : null}
                         <span className="text-[11px] text-red-500">₹{trade.stop_loss?.toFixed(2) || '—'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-col gap-1 items-center">
                        <span className={`status-badge ${trade.status}`}>
                          {trade.status}
                        </span>
                        <span className="text-[9px] uppercase text-gray-500 whitespace-nowrap">{trade.exit_reason || 'open'}</span>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* P&L Summary */}
          {trades.length > 0 && (
            <div className="pnl-summary">
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Total Realized P&L</span>
                <span style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)', fontFamily: "'JetBrains Mono', monospace", fontSize: '1.2rem', fontWeight: 700 }}>
                  {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div className="flex gap-8 ml-auto">
                <div className="summary-stat">
                  <span className="label">Trades</span>
                  <span className="value">{trades.length}</span>
                </div>
                <div className="summary-stat">
                  <span className="label text-green-500">Wins</span>
                  <span className="value text-green-500">{wins}</span>
                </div>
                <div className="summary-stat">
                  <span className="label text-red-500">Losses</span>
                  <span className="value text-red-500">{losses}</span>
                </div>
                <div className="summary-stat">
                  <span className="label">Win Rate</span>
                  <span className="value">{wins + losses > 0 ? ((wins / (wins + losses)) * 100).toFixed(1) : 0}%</span>
                </div>
              </div>
            </div>
          )}
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
          font-size: 1rem;
          font-weight: 700;
          font-family: 'JetBrains Mono', monospace;
        }
      `}</style>
    </div>
  );
}
