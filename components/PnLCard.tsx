'use client';

interface PnLCardProps {
  label: string;
  value: string | number;
  subValue?: string;
  icon: string;
  type?: 'profit' | 'loss' | 'neutral' | 'auto';
  numericValue?: number;
}

export default function PnLCard({ label, value, subValue, icon, type = 'neutral', numericValue }: PnLCardProps) {
  let effectiveType: 'profit' | 'loss' | 'neutral' = (type === 'auto') ? 'neutral' : type;
  if (type === 'auto' && numericValue !== undefined) {
    effectiveType = numericValue > 0 ? 'profit' : numericValue < 0 ? 'loss' : 'neutral';
  }

  const colorMap = {
    profit: 'var(--green)',
    loss: 'var(--red)',
    neutral: 'var(--yellow)',
  };

  return (
    <div className={`pnl-card ${effectiveType}`}>
      <div className="pnl-icon">{icon}</div>
      <div className="pnl-content">
        <div className="pnl-label">{label}</div>
        <div className="pnl-value" style={{ color: colorMap[effectiveType] }}>
          {typeof value === 'number'
            ? (value >= 0 ? '+' : '') + '₹' + Math.abs(value).toLocaleString('en-IN', { minimumFractionDigits: 2 })
            : value}
        </div>
        {subValue && <div className="pnl-sub">{subValue}</div>}
      </div>
    </div>
  );
}
