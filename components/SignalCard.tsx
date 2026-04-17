'use client';

interface SignalCardProps {
  signal: string;
}

export default function SignalCard({ signal }: SignalCardProps) {
  const getSignalConfig = (sig: string) => {
    switch (sig) {
      case 'BUY_CE':
        return { label: 'BUY CE', color: 'var(--green)', glow: '0 0 30px rgba(34, 197, 94, 0.4)', emoji: '🟢', desc: 'Bullish Signal — Call Option' };
      case 'BUY_PE':
        return { label: 'BUY PE', color: 'var(--red)', glow: '0 0 30px rgba(239, 68, 68, 0.4)', emoji: '🔴', desc: 'Bearish Signal — Put Option' };
      case 'ACTIVE_CE':
        return { label: 'IN TRADE (CE)', color: 'var(--green)', glow: '0 0 20px rgba(34, 197, 94, 0.3)', emoji: '📈', desc: 'Call position active' };
      case 'ACTIVE_PE':
        return { label: 'IN TRADE (PE)', color: 'var(--red)', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '📉', desc: 'Put position active' };
      case 'MARKET_CLOSED':
        return { label: 'MARKET CLOSED', color: '#6b7280', glow: 'none', emoji: '🌙', desc: 'Outside market hours' };
      case 'SQUARED_OFF':
        return { label: 'SQUARED OFF', color: '#6b7280', glow: 'none', emoji: '✅', desc: 'All positions closed' };
      case 'DISCONNECTED':
        return { label: 'DISCONNECTED', color: '#ef4444', glow: '0 0 20px rgba(239, 68, 68, 0.3)', emoji: '🔌', desc: 'Bot server not connected' };
      default:
        return { label: 'WAIT', color: 'var(--yellow)', glow: '0 0 20px rgba(234, 179, 8, 0.3)', emoji: '⏳', desc: 'Waiting for signal...' };
    }
  };

  const config = getSignalConfig(signal);

  return (
    <div className="signal-card" style={{ borderColor: config.color, boxShadow: config.glow }}>
      <div className="signal-emoji">{config.emoji}</div>
      <div className="signal-label" style={{ color: config.color }}>{config.label}</div>
      <div className="signal-desc">{config.desc}</div>
      {(signal === 'BUY_CE' || signal === 'BUY_PE') && (
        <div className="signal-pulse" style={{ backgroundColor: config.color }} />
      )}
    </div>
  );
}
