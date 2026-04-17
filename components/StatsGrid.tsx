'use client';

import PnLCard from './PnLCard';

interface StatsGridProps {
  todayPnl: number;
  totalTrades: number;
  winRate: number;
  wins: number;
  losses: number;
  mode: string;
}

export default function StatsGrid({ todayPnl, totalTrades, winRate, wins, losses, mode }: StatsGridProps) {
  return (
    <div className="stats-grid">
      <PnLCard
        label="Today's P&L"
        value={todayPnl}
        icon="💰"
        type="auto"
        numericValue={todayPnl}
        subValue={mode === 'paper' ? 'Paper Trading' : 'Live Trading'}
      />
      <PnLCard
        label="Trades Today"
        value={String(totalTrades)}
        icon="📊"
        type="neutral"
        subValue={`${wins}W / ${losses}L`}
      />
      <PnLCard
        label="Win Rate"
        value={`${winRate}%`}
        icon="🎯"
        type={winRate >= 50 ? 'profit' : winRate > 0 ? 'loss' : 'neutral'}
        subValue={totalTrades > 0 ? `${wins} of ${wins + losses} trades` : 'No closed trades'}
      />
    </div>
  );
}
