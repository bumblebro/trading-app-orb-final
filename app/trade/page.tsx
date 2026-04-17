'use client';

import { useEffect, useState, useCallback } from 'react';
import TradeCard from '@/components/TradeCard';
import { api } from '@/lib/api';
import type { Trade } from '@/lib/types';

export default function TradePage() {
  const [trade, setTrade] = useState<Trade | null>(null);
  const [currentPrice, setCurrentPrice] = useState(0);
  const [loading, setLoading] = useState(true);
  const [exiting, setExiting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const fetchTrade = useCallback(async () => {
    try {
      const [tradeRes, priceRes] = await Promise.all([
        api.getActiveTrade(),
        api.getPrice(),
      ]);
      setTrade(tradeRes.trade || null);
      // Prioritize the simulated option price from the trade if it exists
      if (tradeRes.trade?.current_price) {
        setCurrentPrice(tradeRes.trade.current_price);
      } else {
        setCurrentPrice(priceRes.price || 0);
      }
    } catch {
      // Bot not connected
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrade();
    const interval = setInterval(fetchTrade, 1000);
    return () => clearInterval(interval);
  }, [fetchTrade]);

  const handleExit = async () => {
    setExiting(true);
    try {
      await api.exitTrade(currentPrice || undefined);
      setShowConfirm(false);
      await fetchTrade();
    } catch (e) {
      console.error('Exit error:', e);
    } finally {
      setExiting(false);
    }
  };

  return (
    <div className="page-container">
      <h1 className="page-title">⚡ Active Trade</h1>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
          Loading...
        </div>
      ) : (
        <>
          <TradeCard
            trade={trade}
            currentPrice={currentPrice}
            onExit={() => setShowConfirm(true)}
          />

          {/* Confirmation Modal */}
          {showConfirm && trade && (
            <div className="modal-overlay" onClick={() => setShowConfirm(false)}>
              <div className="modal" onClick={(e) => e.stopPropagation()}>
                <h3>⚠️ Exit Trade?</h3>
                <p>
                  Are you sure you want to exit the <strong>{trade.type}</strong> position at
                  <strong> ₹{currentPrice.toFixed(2)}</strong>?
                </p>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  Estimated P&L: <span style={{
                    color: ((currentPrice - trade.entry_price) * trade.quantity) >= 0 ? 'var(--green)' : 'var(--red)'
                  }}>
                    ₹{((currentPrice - trade.entry_price) * trade.quantity).toFixed(2)}
                  </span>
                </p>
                <div className="modal-actions">
                  <button className="btn-cancel" onClick={() => setShowConfirm(false)}>Cancel</button>
                  <button className="btn-danger" onClick={handleExit} disabled={exiting}>
                    {exiting ? 'Exiting...' : 'Confirm Exit'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
