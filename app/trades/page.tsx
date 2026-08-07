'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, inr, num } from '@/lib/api';
import { usePoll } from '@/lib/hooks';
import type { Analytics, Trade, TradesResponse } from '@/lib/types';

const MODES = ['paper', 'live'] as const;
type Mode = (typeof MODES)[number];
const POLL_MS = 3000;

function modeFromSettings(value: unknown): Mode {
  return value === 'live' ? 'live' : 'paper';
}

export default function TradesPage() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [data, setData] = useState<TradesResponse | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [initialCapital, setInitialCapital] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [clearing, setClearing] = useState(false);

  // Match Settings → Trading mode on first visit (user can still toggle).
  useEffect(() => {
    let cancelled = false;
    api
      .settings()
      .then((res) => {
        if (cancelled) return;
        setMode(modeFromSettings(res.settings?.trading_mode));
        setInitialCapital(Number(res.settings?.initial_capital) || 0);
      })
      .catch(() => {
        if (!cancelled) setMode('paper');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    if (!mode) return;
    try {
      const [trades, stats, settingsRes] = await Promise.all([
        api.trades({ mode, limit: 300 }),
        api.analytics(mode),
        api.settings(),
      ]);
      setData(trades);
      setAnalytics(stats);
      setInitialCapital(Number(settingsRes.settings?.initial_capital) || 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot reach the bot server');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  usePoll(load, POLL_MS);

  const clearHistory = async () => {
    if (
      !confirm(
        'Clear all trades, signals and logs?\n\nSettings and Angel credentials are kept. Stop the bot first if it is running.',
      )
    ) {
      return;
    }
    setClearing(true);
    try {
      await api.clearData();
      setLoading(true);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clear failed');
    } finally {
      setClearing(false);
    }
  };

  const summary = data?.summary;
  const trades = data?.trades ?? [];
  const netPnl = summary?.all_time_pnl ?? 0;
  const totalReturnPct =
    initialCapital > 0 ? (netPnl / initialCapital) * 100 : null;

  const drawdown = useMemo(() => {
    const curve = analytics?.equity_curve ?? [];
    let peak = 0;
    let worst = 0;
    for (const point of curve) {
      peak = Math.max(peak, point.cumulative_pnl);
      worst = Math.min(worst, point.cumulative_pnl - peak);
    }
    return worst;
  }, [analytics]);

  return (
    <main className="page-shell py-4 sm:py-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0 text-[1.05rem] font-semibold">Trade history</h1>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn btn-danger"
            disabled={clearing}
            onClick={clearHistory}
          >
            {clearing ? 'Clearing…' : 'Clear history'}
          </button>
          <div className="flex shrink-0 gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1">
            {MODES.map((m) => (
              <button
                key={m}
                disabled={!mode}
                onClick={() => {
                  if (!mode || m === mode) return;
                  setMode(m);
                  setLoading(true);
                }}
                className={`rounded-md px-3 py-1 text-[0.78rem] font-medium capitalize transition-colors ${
                  mode === m
                    ? 'bg-[var(--surface-2)] text-[var(--text)]'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="card mb-4 border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-4 py-2.5 text-[0.8rem] text-[var(--red)]">
          {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-8">
        <Tile
          label="This month"
          value={inr(summary?.month_pnl ?? 0)}
          tone={(summary?.month_pnl ?? 0) >= 0 ? 'up' : 'down'}
          sub={`${summary?.month_label ?? '—'} · ${summary?.month_trades ?? 0} trades`}
        />
        <Tile
          label="This year"
          value={inr(summary?.year_pnl ?? 0)}
          tone={(summary?.year_pnl ?? 0) >= 0 ? 'up' : 'down'}
          sub={`${summary?.year_label ?? '—'} · ${summary?.year_trades ?? 0} trades`}
        />
        <Tile
          label="All-time P&L"
          value={inr(netPnl)}
          tone={netPnl >= 0 ? 'up' : 'down'}
        />
        <Tile
          label="Total return"
          value={
            totalReturnPct === null
              ? '—'
              : `${totalReturnPct >= 0 ? '+' : ''}${num(totalReturnPct, 2)}%`
          }
          tone={
            totalReturnPct === null
              ? undefined
              : totalReturnPct >= 0
                ? 'up'
                : 'down'
          }
          sub={initialCapital > 0 ? `On ${inr(initialCapital)}` : undefined}
        />
        <Tile label="Gross P&L" value={inr(summary?.all_time_gross_pnl ?? 0)} className="hidden sm:block" />
        <Tile label="Charges" value={inr(summary?.all_time_charges ?? 0)} tone="down" className="hidden sm:block" />
        <Tile
          label="Win rate"
          value={`${num(summary?.all_time_win_rate, 1)}%`}
          sub={`${summary?.wins ?? 0}W / ${summary?.losses ?? 0}L`}
        />
        <Tile label="Max drawdown" value={inr(drawdown)} tone="down" />
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px_280px]">
        <section className="card card-pad min-w-0">
          <div className="label mb-3">Equity curve · cumulative net P&L</div>
          <EquityCurve points={analytics?.equity_curve ?? []} />
        </section>

        <section className="card card-pad">
          <div className="label mb-3">Year-wise P&L</div>
          {analytics?.yearly_pnl?.length ? (
            <div className="flex flex-col gap-2">
              {analytics.yearly_pnl.map((row) => (
                <div
                  key={row.year}
                  className="flex items-center justify-between gap-3 text-[0.8rem]"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-[var(--text)]">{row.year}</div>
                    <div className="text-[0.72rem] text-[var(--faint)]">
                      {row.trades} trades · {num(row.win_rate, 0)}% WR
                    </div>
                  </div>
                  <span className={`metric shrink-0 ${row.net_pnl >= 0 ? 'up' : 'down'}`}>
                    {inr(row.net_pnl)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="m-0 text-[0.8rem] text-[var(--faint)]">No closed trades yet.</p>
          )}
        </section>

        <section className="card card-pad">
          <div className="label mb-3">Exit reasons</div>
          {analytics?.exit_reasons?.length ? (
            <div className="flex flex-col gap-2">
              {analytics.exit_reasons.map((row) => (
                <div key={row.reason} className="flex items-center justify-between gap-3 text-[0.8rem]">
                  <span className="min-w-0 truncate text-[var(--muted)]">{row.reason.replace(/_/g, ' ')}</span>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className="text-[var(--faint)]">{row.count}</span>
                    <span className={`metric ${row.net_pnl >= 0 ? 'up' : 'down'}`}>
                      {inr(row.net_pnl)}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="m-0 text-[0.8rem] text-[var(--faint)]">No closed trades yet.</p>
          )}
        </section>
      </div>

      {/* Mobile trade cards */}
      <section className="flex flex-col gap-3 md:hidden">
        {trades.map((trade) => (
          <TradeCard key={trade.id} trade={trade} />
        ))}
        {!trades.length && (
          <div className="card card-pad text-center text-[0.8rem] text-[var(--faint)]">
            {loading ? 'Loading…' : `No ${mode} trades recorded.`}
          </div>
        )}
      </section>

      {/* Desktop table */}
      <section className="card hidden overflow-hidden md:block">
        <div className="scroll-x scroll-y max-h-[540px]">
          <table className="table min-w-[920px]">
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Dir</th>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Capital used</th>
                <th>Index in/out</th>
                <th>Exit reason</th>
                <th className="text-right">Net P&L</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <TradeRow key={trade.id} trade={trade} />
              ))}
              {!trades.length && (
                <tr>
                  <td colSpan={11} className="text-center text-[var(--faint)]">
                    {loading ? 'Loading…' : `No ${mode} trades recorded.`}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function tradeMeta(trade: Trade) {
  const pnl = trade.net_pnl ?? trade.pnl ?? 0;
  const open = trade.status === 'open';
  const capitalUsed =
    trade.capital_used ??
    (trade.entry_price && trade.quantity
      ? trade.entry_price * trade.quantity
      : null);
  return { pnl, open, capitalUsed };
}

function TradeCard({ trade }: { trade: Trade }) {
  const { pnl, open, capitalUsed } = tradeMeta(trade);
  return (
    <article className="card card-pad">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[0.85rem] font-medium">{trade.trading_symbol}</div>
          <div className="mt-0.5 text-[0.72rem] text-[var(--faint)]">
            {trade.date} · {trade.time?.slice(0, 5)} ·{' '}
            <span className={trade.direction === 'LONG' ? 'up' : 'down'}>
              {trade.direction ?? '—'}
            </span>
          </div>
        </div>
        <div className={`metric shrink-0 text-[0.95rem] ${open ? 'warn' : pnl >= 0 ? 'up' : 'down'}`}>
          {open ? 'OPEN' : inr(pnl)}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[0.75rem]">
        <Meta label="Qty" value={String(trade.quantity)} />
        <Meta label="Capital" value={capitalUsed == null ? '—' : inr(capitalUsed)} />
        <Meta label="Entry" value={num(trade.entry_price)} />
        <Meta label="Exit" value={trade.exit_price === null ? '—' : num(trade.exit_price)} />
        <Meta
          label="Index"
          value={`${num(trade.underlying_entry_price, 0)} → ${num(trade.underlying_exit_price, 0)}`}
        />
        <Meta label="Reason" value={trade.exit_reason?.replace(/_/g, ' ') ?? '—'} />
      </div>
    </article>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[0.66rem] uppercase tracking-wide text-[var(--faint)]">{label}</div>
      <div className="metric truncate text-[var(--text)]">{value}</div>
    </div>
  );
}

function TradeRow({ trade }: { trade: Trade }) {
  const { pnl, open, capitalUsed } = tradeMeta(trade);
  return (
    <tr>
      <td className="text-[var(--muted)]">{trade.date}</td>
      <td className="text-[var(--muted)]">{trade.time?.slice(0, 5)}</td>
      <td className={trade.direction === 'LONG' ? 'up' : 'down'}>{trade.direction ?? '—'}</td>
      <td>{trade.trading_symbol}</td>
      <td>{trade.quantity}</td>
      <td>{num(trade.entry_price)}</td>
      <td>{trade.exit_price === null ? '—' : num(trade.exit_price)}</td>
      <td>{capitalUsed == null ? '—' : inr(capitalUsed)}</td>
      <td className="text-[var(--muted)]">
        {num(trade.underlying_entry_price, 0)} → {num(trade.underlying_exit_price, 0)}
      </td>
      <td className="text-[var(--muted)]">{trade.exit_reason?.replace(/_/g, ' ') ?? '—'}</td>
      <td className={`text-right ${open ? 'warn' : pnl >= 0 ? 'up' : 'down'}`}>
        {open ? 'OPEN' : inr(pnl)}
      </td>
    </tr>
  );
}

function EquityCurve({ points }: { points: { date: string; cumulative_pnl: number }[] }) {
  if (points.length < 2) {
    return (
      <div className="flex h-[200px] items-center justify-center text-[0.8rem] text-[var(--faint)]">
        Not enough closed trades to plot a curve.
      </div>
    );
  }

  const width = 800;
  const height = 200;
  const values = points.map((p) => p.cumulative_pnl);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;

  const x = (i: number) => (i / (points.length - 1)) * width;
  const y = (value: number) => height - ((value - min) / span) * height;

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.cumulative_pnl).toFixed(1)}`).join(' ');
  const area = `${line} L${width},${y(min)} L0,${y(min)} Z`;
  const positive = values[values.length - 1] >= 0;
  const stroke = positive ? 'var(--green)' : 'var(--red)';

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[200px] w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" y1={y(0)} x2={width} y2={y(0)} stroke="var(--border)" strokeWidth="1" />
        <path d={area} fill="url(#equity-fill)" />
        <path d={line} fill="none" stroke={stroke} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-2 flex justify-between text-[0.7rem] text-[var(--faint)]">
        <span>{points[0].date}</span>
        <span className="metric">{inr(values[values.length - 1])}</span>
        <span>{points[points.length - 1].date}</span>
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  tone,
  className = '',
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'up' | 'down';
  className?: string;
}) {
  return (
    <div className={`card card-pad ${className}`}>
      <div className="label">{label}</div>
      <div className={`metric mt-1.5 text-[1.05rem] sm:text-[1.1rem] ${tone ?? ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[0.72rem] text-[var(--faint)]">{sub}</div>}
    </div>
  );
}
