'use client';

import { useEffect, useState } from 'react';

interface PriceDisplayProps {
  price: number;
  change: number;
  changePct: number;
  connected: boolean;
  simulation: boolean;
  tick_count?: number;
}

export default function PriceDisplay({ price, change, changePct, connected, simulation, tick_count }: PriceDisplayProps) {
  const [flash, setFlash] = useState(false);
  const [prevDisplayPrice, setPrevDisplayPrice] = useState(0);

  useEffect(() => {
    if (price !== prevDisplayPrice && price > 0) {
      setFlash(true);
      setPrevDisplayPrice(price);
      const timer = setTimeout(() => setFlash(false), 300);
      return () => clearTimeout(timer);
    }
  }, [price, prevDisplayPrice]);

  const isUp = change >= 0;
  const priceColor = isUp ? 'var(--green)' : 'var(--red)';

  return (
    <div className={`price-display ${flash ? 'flash' : ''}`}>
      <div className="price-label">
        <div className="flex items-center gap-2">
          <span className="price-title">NIFTY 50</span>
          <span className={`connection-dot ${connected ? 'connected' : 'disconnected'}`} />
          {tick_count !== undefined && (
            <span className="text-[10px] text-gray-500 font-mono opacity-60">
              #{tick_count}
            </span>
          )}
        </div>
        {simulation && <span className="sim-badge">SIM</span>}
      </div>
      <div className="price-value" style={{ color: price > 0 ? priceColor : '#6b7280' }}>
        {price > 0 ? price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
      </div>
      <div className="price-change" style={{ color: priceColor }}>
        <span>{isUp ? '▲' : '▼'}</span>
        <span>{Math.abs(change).toFixed(2)}</span>
        <span>({Math.abs(changePct).toFixed(2)}%)</span>
      </div>
    </div>
  );
}
