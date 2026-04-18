'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Signal } from '@/lib/types';

interface SignalCardProps {
  signal: string;
}

export default function SignalCard({ signal }: SignalCardProps) {
  const [strategyInfo, setStrategyInfo] = useState<Signal | null>(null);

  useEffect(() => {
    const fetchSignalDetails = async () => {
      try {
        const data = await api.getSignal();
        setStrategyInfo(data as Signal);
      } catch (err) {
        console.error("Failed to fetch signal details", err);
      }
    };

    fetchSignalDetails();
    const interval = setInterval(fetchSignalDetails, 2000);
    return () => clearInterval(interval);
  }, []);

  const getSignalConfig = (sig: string, phase: string) => {
    if (phase === 'DISCONNECTED') {
      return { label: 'DISCONNECTED', color: '#ef4444', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '🔌', desc: 'Bot server disconnected' };
    }

    switch (sig) {
      case 'BUY_CE':
        return { label: 'BUY CE', color: 'var(--green)', glow: '0 0 30px rgba(34, 197, 94, 0.5)', emoji: '🎯', desc: 'All conditions met — LONG' };
      case 'BUY_PE':
        return { label: 'BUY PE', color: 'var(--red)', glow: '0 0 30px rgba(239, 68, 68, 0.5)', emoji: '🎯', desc: 'All conditions met — SHORT' };
      case 'ACTIVE_CE':
        return { label: 'IN TRADE (CE)', color: 'var(--green)', glow: '0 0 20px rgba(34, 197, 94, 0.3)', emoji: '📈', desc: 'Call position active' };
      case 'ACTIVE_PE':
        return { label: 'IN TRADE (PE)', color: 'var(--red)', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '📉', desc: 'Put position active' };
      case 'MARKET_CLOSED':
        return { label: 'MARKET CLOSED', color: '#6b7280', glow: 'none', emoji: '🌙', desc: 'Outside market hours' };
      case 'SQUARED_OFF':
        return { label: 'SQUARED OFF', color: '#6b7280', glow: 'none', emoji: '✅', desc: 'Session complete' };
      default:
        // Phase-based WAIT states
        switch (phase) {
          case 'WATCHING':
            return { label: 'WATCHING', color: '#6b7280', glow: 'none', emoji: '⏳', desc: 'Waiting for 9:15 AM' };
          case 'BUILDING_ORB':
            return { label: 'BUILDING ORB', color: 'var(--blue)', glow: '0 0 20px rgba(59, 130, 246, 0.3)', emoji: '📊', desc: 'Analyzing opening 15m range' };
          case 'WAITING_BREAKOUT':
            return { label: 'WAITING BREAKOUT', color: '#06b6d4', glow: '0 0 20px rgba(6, 182, 212, 0.3)', emoji: '👀', desc: 'Watching high/low levels' };
          case 'BREAKOUT_DETECTED':
            return { label: 'BREAKOUT!', color: 'var(--yellow)', glow: '0 0 25px rgba(234, 179, 8, 0.4)', emoji: '⚡', desc: 'Price broke range — Calculating Fibs' };
          case 'WAITING_PULLBACK':
            return { label: 'WAITING PULLBACK', color: 'var(--yellow)', glow: '0 0 20px rgba(234, 179, 8, 0.3)', emoji: '⏳', desc: 'Price must return to entry zone' };
          case 'IN_ENTRY_ZONE':
            return { label: 'IN ENTRY ZONE', color: 'var(--purple)', glow: '0 0 25px rgba(168, 85, 247, 0.4)', emoji: '💎', desc: 'Pullback reached! Checking MACD...' };
          case 'MACD_CONFIRMING':
            return { label: 'CONFIRMING...', color: 'var(--purple)', glow: '0 0 25px rgba(168, 85, 247, 0.5)', emoji: '🔄', desc: 'Waiting for MACD momentum/curl' };
          case 'SKIP_TODAY':
            return { label: 'SKIP TODAY', color: '#ef4444', glow: 'none', emoji: '🚫', desc: 'ORB range invalid or too wide' };
          case 'MAX_TRADES_DONE':
            return { label: 'LIMIT REACHED', color: '#6b7280', glow: 'none', emoji: '🛑', desc: 'Max daily trades completed' };
          default:
            return { label: 'WAITING', color: 'var(--yellow)', glow: '0 0 20px rgba(234, 179, 8, 0.3)', emoji: '⏳', desc: 'Initializing system...' };
        }
    }
  };

  const currentPhase = strategyInfo?.phase || 'INITIALIZING';
  const config = getSignalConfig(signal, currentPhase);
  const conditions = strategyInfo?.conditions || { orb_breakout: false, fibonacci_pullback: false, macd_confirms: false };

  return (
    <div className="signal-card" style={{ 
      borderColor: config.color, 
      boxShadow: config.glow,
      background: (signal === 'BUY_CE' || signal === 'BUY_PE') ? `linear-gradient(135deg, var(--bg-card), ${config.color}20)` : undefined
    }}>
      <div className="signal-emoji">{config.emoji}</div>
      <div className="signal-label" style={{ color: config.color }}>{config.label}</div>
      <div className="signal-desc">{config.desc}</div>
      
      {/* Logic Checklist */}
      {currentPhase !== 'WATCHING' && currentPhase !== 'CLOSED' && currentPhase !== 'SKIP_TODAY' && (
        <div className="signal-checklist">
          <div className={`check-item ${strategyInfo?.breakout_direction !== 'NONE' ? 'checked' : ''}`}>
            {strategyInfo?.breakout_direction !== 'NONE' ? '✅' : '⚪'} 1. ORB Breakout Detected
          </div>
        </div>
      )}

      {/* ORB Info Pill */}
      {strategyInfo?.orb_range && (
          <div className="orb-stats">
              <span>ORB Range: <strong>{strategyInfo.orb_range.toFixed(2)}</strong></span>
              <span className={`status-pill ${strategyInfo.orb_status}`}>
                  {strategyInfo.orb_status}
              </span>
          </div>
      )}

      {/* Pulse effect for signals */}
      {(signal === 'BUY_CE' || signal === 'BUY_PE') && (
        <div className="signal-pulse" style={{ backgroundColor: config.color }} />
      )}

      <style jsx>{`
        .pullback-timer {
          margin-top: 1rem;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.25rem;
          padding: 0.5rem;
          background: #ffffff05;
          border-radius: 8px;
          border: 1px solid #ffffff10;
          width: 100%;
        }
        .signal-checklist {
          margin-top: 1.25rem;
          padding-top: 1rem;
          border-top: 1px solid #ffffff10;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          width: 100%;
          text-align: left;
        }
        .check-item {
          font-size: 0.8rem;
          color: #6b7280;
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
           font-size: 0.75rem;
           display: flex;
           justify-content: space-between;
           width: 100%;
           color: #9ca3af;
           padding: 4px 8px;
           background: #ffffff05;
           border-radius: 4px;
        }
        .status-pill {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .status-pill.READY { background: #064e3b; color: #34d399; }
        .status-pill.BUILDING { background: #1e3a8a; color: #93c5fd; }
        .status-pill.TOO_FLAT { background: #450a0a; color: #f87171; }
        .status-pill.TOO_WIDE { background: #422006; color: #fbbf24; }
        
        .signal-pulse {
          position: absolute;
          width: 100%;
          height: 100%;
          border-radius: 16px;
          top: 0;
          left: 0;
          z-index: -1;
          opacity: 0.2;
          animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }

        @keyframes pulse {
          0% { transform: scale(1); opacity: 0.2; }
          50% { transform: scale(1.05); opacity: 0.1; }
          100% { transform: scale(1); opacity: 0.2; }
        }
      `}</style>
    </div>
  );
}
