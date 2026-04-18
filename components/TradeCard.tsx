'use client';

import type { Trade } from '@/lib/types';

interface TradeCardProps {
  trade: Trade | null;
  onExit?: () => void;
  currentPrice?: number;
}

export default function TradeCard({ trade, onExit, currentPrice }: TradeCardProps) {
  if (!trade) {
    return (
      <div className="trade-card empty">
        <div className="trade-empty-icon">📭</div>
        <h3>No Active Trade</h3>
        <p>Waiting for the bot to enter a position...</p>
      </div>
    );
  }

  const livePnl = trade.live_pnl || (currentPrice ? (currentPrice - trade.entry_price) * trade.quantity : 0);
  const isProfit = livePnl >= 0;
  
  // Distances
  const slPrice = trade.trailing_sl || trade.stop_loss || 0;
  const targetPrice = trade.target || trade.entry_price;
  const slDistance = slPrice ? ((trade.entry_price - slPrice) / trade.entry_price * 100) : 0;
  const targetDistance = targetPrice ? ((targetPrice - trade.entry_price) / trade.entry_price * 100) : 0;

  // Progress bar: position between SL and Target
  const priceForProgress = currentPrice || trade.entry_price;
  const range = targetPrice - slPrice;
  const progress = range > 0 ? Math.min(100, Math.max(0,
    ((priceForProgress - slPrice) / range) * 100
  )) : 50;

  return (
    <div className={`trade-card ${trade.type === 'CE' ? 'bullish' : 'bearish'}`}>
      <div className="trade-header">
        <div className="trade-type-badge" data-type={trade.type}>
          {trade.type === 'CE' ? '📈 CALL' : '📉 PUT'} — {trade.trading_symbol || `NIFTY ${trade.strike_price}${trade.type}`}
        </div>
        <div className="flex items-center gap-2">
          {trade.trailing_sl_used ? (
            <span className="text-[10px] bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded border border-purple-500/30 font-bold">TRAILING</span>
          ) : null}
          <span className={`trade-mode-badge ${trade.mode}`}>
            {trade.mode === 'paper' ? '📝 Paper' : '💰 Live'}
          </span>
        </div>
      </div>

      <div className="trade-grid">
        <div className="trade-stat">
          <span className="stat-label">Entry Premium</span>
          <span className="stat-value">₹{trade.entry_price.toFixed(2)}</span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Current Premium</span>
          <span className="stat-value" style={{ color: isProfit ? 'var(--green)' : 'var(--red)' }}>
            ₹{(currentPrice || trade.entry_price).toFixed(2)}
          </span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Stop Loss (Trailing)</span>
          <span className="stat-value sl">₹{slPrice.toFixed(2)} ({slDistance.toFixed(1)}%)</span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Target (80%)</span>
          <span className="stat-value tgt">₹{targetPrice.toFixed(2)} (+{targetDistance.toFixed(1)}%)</span>
        </div>
        
        {/* New Strategy Specific Stats */}
        <div className="trade-stat border-t border-white/5 pt-2 mt-1">
          <span className="stat-label">Breakout Point</span>
          <span className="stat-value text-cyan-400">₹{trade.breakout_price?.toFixed(2) || '—'}</span>
        </div>
        <div className="trade-stat border-t border-white/5 pt-2 mt-1">
          <span className="stat-label">Fib Level</span>
          <span className="stat-value text-yellow-500">{trade.fib_entry_level || '—'}%</span>
        </div>

        <div className="trade-stat pnl full">
          <div className="flex justify-between items-end w-full">
            <div className="flex flex-col">
              <span className="stat-label">Position P&L</span>
              <span className="stat-value" style={{ color: isProfit ? 'var(--green)' : 'var(--red)', fontSize: '1.4rem' }}>
                {isProfit ? '+' : ''}₹{livePnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
            <div className="flex flex-col items-end">
               <span className="stat-label">Size</span>
               <span className="text-sm font-mono text-gray-400">{trade.quantity} ({trade.quantity / trade.lot_size} Lots)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="trade-progress mt-4">
        <div className="progress-labels">
          <span className="sl-label">SL</span>
          <span className="entry-label">Entry</span>
          <span className="tgt-label">TGT</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{
            width: `${progress}%`,
            backgroundColor: progress > 50 ? 'var(--green)' : 'var(--red)'
          }} />
          <div className="progress-marker entry-marker" style={{ left: `${range > 0 ? ((trade.entry_price - slPrice) / range * 100) : 50}%` }} />
        </div>
      </div>

      {onExit && (
        <button className="exit-btn mt-4 w-full" onClick={onExit}>
          🚨 Emergency Square Off
        </button>
      )}

      <style jsx>{`
        .full { grid-column: 1 / -1; }
        .trade-stat.pnl {
          background: #ffffff05;
          padding: 0.75rem;
          border-radius: 8px;
          margin-top: 0.5rem;
        }
      `}</style>
    </div>
  );
}
