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
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>Loading...</div>
      ) : (
        <div className="trades-table-container">
          <table className="trades-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Type</th>
                <th>Strike</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Qty</th>
                <th>P&L</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={11} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                    No trades found
                  </td>
                </tr>
              ) : (
                trades.map((trade) => (
                  <tr key={trade.id}>
                    <td>{trade.date}</td>
                    <td>{trade.time}</td>
                    <td style={{ color: trade.type === 'CE' ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                      {trade.type}
                    </td>
                    <td>{trade.strike_price}</td>
                    <td>₹{trade.entry_price.toFixed(2)}</td>
                    <td>{trade.exit_price ? `₹${trade.exit_price.toFixed(2)}` : '—'}</td>
                    <td>{trade.quantity}</td>
                    <td className={trade.pnl >= 0 ? 'win' : 'loss'}>
                      {trade.status !== 'open' ? `${trade.pnl >= 0 ? '+' : ''}₹${trade.pnl.toFixed(2)}` : '—'}
                    </td>
                    <td>
                      <span style={{
                        color: trade.status === 'win' ? 'var(--green)' :
                               trade.status === 'loss' ? 'var(--red)' :
                               trade.status === 'open' ? 'var(--yellow)' : 'var(--text-muted)',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        fontSize: '0.75rem'
                      }}>
                        {trade.status}
                      </span>
                    </td>
                    <td style={{ textTransform: 'capitalize', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {trade.exit_reason || '—'}
                    </td>
                    <td>
                      <span style={{
                        padding: '1px 6px',
                        borderRadius: '3px',
                        fontSize: '0.65rem',
                        fontWeight: 600,
                        background: trade.mode === 'paper' ? 'var(--yellow-dim)' : 'var(--red-dim)',
                        color: trade.mode === 'paper' ? 'var(--yellow)' : 'var(--red)'
                      }}>
                        {trade.mode.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* P&L Summary */}
          {trades.length > 0 && (
            <div className="pnl-summary">
              <span>
                Total P&L:{' '}
                <span style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)', fontFamily: "'JetBrains Mono', monospace" }}>
                  {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toFixed(2)}
                </span>
              </span>
              <span>Trades: {trades.length}</span>
              <span style={{ color: 'var(--green)' }}>Wins: {wins}</span>
              <span style={{ color: 'var(--red)' }}>Losses: {losses}</span>
              <span>Win Rate: {wins + losses > 0 ? ((wins / (wins + losses)) * 100).toFixed(1) : 0}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
