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
  const slDistance = trade.stop_loss ? ((trade.entry_price - trade.stop_loss) / trade.entry_price * 100) : 0;
  const targetDistance = trade.target ? ((trade.target - trade.entry_price) / trade.entry_price * 100) : 0;

  // Progress bar: position between SL and Target
  const priceForProgress = currentPrice || trade.entry_price;
  const range = (trade.target || trade.entry_price) - (trade.stop_loss || trade.entry_price);
  const progress = range > 0 ? Math.min(100, Math.max(0,
    ((priceForProgress - (trade.stop_loss || trade.entry_price)) / range) * 100
  )) : 50;

  return (
    <div className={`trade-card ${trade.type === 'CE' ? 'bullish' : 'bearish'}`}>
      <div className="trade-header">
        <div className="trade-type-badge" data-type={trade.type}>
          {trade.type === 'CE' ? '📈 CALL' : '📉 PUT'} — {trade.trading_symbol || `NIFTY ${trade.strike_price}${trade.type}`}
        </div>
        <span className={`trade-mode-badge ${trade.mode}`}>
          {trade.mode === 'paper' ? '📝 Paper' : '💰 Live'}
        </span>
      </div>

      <div className="trade-grid">
        <div className="trade-stat">
          <span className="stat-label">Entry</span>
          <span className="stat-value">₹{trade.entry_price.toFixed(2)}</span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Current</span>
          <span className="stat-value" style={{ color: isProfit ? 'var(--green)' : 'var(--red)' }}>
            ₹{(currentPrice || trade.entry_price).toFixed(2)}
          </span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Stop Loss</span>
          <span className="stat-value sl">₹{trade.stop_loss?.toFixed(2) || '—'} ({slDistance.toFixed(1)}%)</span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Target</span>
          <span className="stat-value tgt">₹{trade.target?.toFixed(2) || '—'} (+{targetDistance.toFixed(1)}%)</span>
        </div>
        <div className="trade-stat">
          <span className="stat-label">Qty</span>
          <span className="stat-value">{trade.quantity} (Lot: {trade.lot_size})</span>
        </div>
        <div className="trade-stat pnl">
          <span className="stat-label">Live P&L</span>
          <span className="stat-value" style={{ color: isProfit ? 'var(--green)' : 'var(--red)', fontSize: '1.3rem' }}>
            {isProfit ? '+' : ''}₹{livePnl.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="trade-progress">
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
          <div className="progress-marker entry-marker" style={{ left: `${range > 0 ? ((trade.entry_price - (trade.stop_loss || 0)) / range * 100) : 50}%` }} />
        </div>
      </div>

      {onExit && (
        <button className="exit-btn" onClick={onExit}>
          ⚠️ Exit Trade
        </button>
      )}
    </div>
  );
}
