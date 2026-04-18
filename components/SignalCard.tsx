'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface SignalCardProps {
  signal: string;
}

export default function SignalCard({ signal }: SignalCardProps) {
  const [strategyInfo, setStrategyInfo] = useState<any>(null);

  useEffect(() => {
    const fetchSignalDetails = async () => {
      try {
        const data = await api.getSignal();
        setStrategyInfo(data);
      } catch (err) {
        console.error("Failed to fetch signal details", err);
      }
    };

    fetchSignalDetails();
    const interval = setInterval(fetchSignalDetails, 5000);
    return () => clearInterval(interval);
  }, []);

  const getSignalConfig = (sig: string) => {
    switch (sig) {
      case 'BUY_CE':
        return { label: 'BUY CE', color: 'var(--green)', glow: '0 0 30px rgba(34, 197, 94, 0.4)', emoji: '🎯', desc: 'Strategy Confirmed — Call Entry' };
      case 'BUY_PE':
        return { label: 'BUY PE', color: 'var(--red)', glow: '0 0 30px rgba(239, 68, 68, 0.4)', emoji: '🎯', desc: 'Strategy Confirmed — Put Entry' };
      case 'ACTIVE_CE':
        return { label: 'IN TRADE (CE)', color: 'var(--green)', glow: '0 0 20px rgba(34, 197, 94, 0.3)', emoji: '📈', desc: 'Call position active' };
      case 'ACTIVE_PE':
        return { label: 'IN TRADE (PE)', color: 'var(--red)', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '📉', desc: 'Put position active' };
      case 'MARKET_CLOSED':
        return { label: 'MARKET CLOSED', color: '#6b7280', glow: 'none', emoji: '🌙', desc: 'Outside market hours' };
      case 'SQUARED_OFF':
        return { label: 'SQUARED OFF', color: '#6b7280', glow: 'none', emoji: '✅', desc: 'Session complete' };
      case 'DISCONNECTED':
        return { label: 'DISCONNECTED', color: '#ef4444', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '🔌', desc: 'Bot server disconnected' };
      default:
        // Handle Phases for WAIT state
        if (strategyInfo?.phase === 'WATCHING') {
            return { label: 'WATCHING', color: '#6b7280', glow: 'none', emoji: '⏳', desc: 'Premarket / Waiting for 9:15' };
        }
        if (strategyInfo?.phase === 'ORB_BUILDING') {
            return { label: 'BUILDING ORB', color: 'var(--blue)', glow: '0 0 20px rgba(59, 130, 246, 0.3)', emoji: '📊', desc: 'Analyzing opening range...' };
        }
        return { label: 'WAITING', color: 'var(--yellow)', glow: '0 0 20px rgba(234, 179, 8, 0.3)', emoji: '⏳', desc: 'Waiting for breakout...' };
    }
  };

  const config = getSignalConfig(signal);
  const conditions = strategyInfo?.conditions || {};

  return (
    <div className="signal-card" style={{ borderColor: config.color, boxShadow: config.glow }}>
      <div className="signal-emoji">{config.emoji}</div>
      <div className="signal-label" style={{ color: config.color }}>{config.label}</div>
      <div className="signal-desc">{config.desc}</div>
      
      {(signal === 'BUY_CE' || signal === 'BUY_PE' || signal === 'WAIT') && strategyInfo?.phase === 'TRADING' && (
        <div className="signal-checklist">
          <div className={`check-item ${conditions.orb_breakout ? 'checked' : ''}`}>
            {conditions.orb_breakout ? '✅' : '⚪'} ORB Breakout
          </div>
          <div className={`check-item ${conditions.supertrend_confirms ? 'checked' : ''}`}>
            {conditions.supertrend_confirms ? '✅' : '⚪'} Supertrend Confirmed
          </div>
          <div className={`check-item ${conditions.rsi_confirms ? 'checked' : ''}`}>
            {conditions.rsi_confirms ? '✅' : '⚪'} RSI Momentum
          </div>
        </div>
      )}

      {strategyInfo?.orb_range && (
          <div className="orb-stats">
              <span>Range: <strong>{strategyInfo.orb_range} pts</strong></span>
              <span className={`status-pill ${strategyInfo.orb_status}`}>
                  {strategyInfo.orb_status}
              </span>
          </div>
      )}

      {(signal === 'BUY_CE' || signal === 'BUY_PE') && (
        <div className="signal-pulse" style={{ backgroundColor: config.color }} />
      )}

      <style jsx>{`
        .signal-checklist {
          margin-top: 1.5rem;
          padding-top: 1rem;
          border-top: 1px solid #ffffff10;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          width: 100%;
          text-align: left;
        }
        .check-item {
          font-size: 0.85rem;
          color: #9ca3af;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        .check-item.checked {
          color: #fff;
          font-weight: 500;
        }
        .orb-stats {
           margin-top: 1rem;
           font-size: 0.8rem;
           display: flex;
           justify-content: space-between;
           width: 100%;
           color: #9ca3af;
        }
        .status-pill {
            padding: 2px 8px;
            border-radius: 99px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-pill.READY { background: #064e3b; color: #34d399; }
        .status-pill.BUILDING { background: #1e3a8a; color: #93c5fd; }
        .status-pill.TOO_FLAT { background: #450a0a; color: #f87171; }
        .status-pill.TOO_WIDE { background: #422006; color: #fbbf24; }
      `}</style>
    </div>
  );
}
