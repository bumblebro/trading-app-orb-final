'use client';

import dynamic from 'next/dynamic';
import { useCallback, useState } from 'react';
import { api, inr, num } from '@/lib/api';
import { usePoll } from '@/lib/hooks';
import type { BotStatus, BrokerStatus, CandlePayload, Phase } from '@/lib/types';

const Chart = dynamic(() => import('@/components/Chart'), { ssr: false });

const PHASES: { key: Phase; label: string }[] = [
  { key: 'BUILDING_RANGE', label: 'Range' },
  { key: 'WAITING_BREAKOUT', label: 'Watch' },
  { key: 'IN_TRADE', label: 'Trade' },
  { key: 'DONE', label: 'Done' },
];

const POLL_MS = 2000;

export default function DashboardPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [candles, setCandles] = useState<CandlePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextCandles] = await Promise.all([api.status(), api.candles()]);
      setStatus(nextStatus);
      setCandles(nextCandles);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot reach the bot server');
    }
  }, []);

  usePoll(refresh, POLL_MS);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setBusy(false);
    }
  };

  const strategy = status?.strategy;
  const price = status?.price;
  const position = strategy?.position;
  const trade = status?.active_trade;
  const running = status?.running ?? false;
  const live = status?.mode === 'live';
  const activeIndex = PHASES.findIndex((p) => p.key === strategy?.phase);
  const inTrade = Boolean(trade && position);

  const initialCapital = status?.initial_capital || 0;
  const totalPnl = status?.total_pnl ?? 0;
  const totalReturnPct =
    initialCapital > 0 ? (totalPnl / initialCapital) * 100 : null;

  const brokerStatusLabel =
    status?.broker?.status === 'connected'
      ? status.broker.feed_connected
        ? 'Connected'
        : 'Logged in'
      : status?.broker?.status === 'failed'
        ? 'Login failed'
        : status?.broker?.status === 'playback'
          ? 'Playback'
          : running
            ? '—'
            : 'Stopped';

  return (
    <main className="page-shell overflow-x-hidden py-3 sm:py-5">
      {error && (
        <div className="card mb-3 break-words border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-3 py-2.5 text-[0.78rem] text-[var(--red)] sm:mb-4 sm:px-4">
          {error}
        </div>
      )}

      {/* Header: stacked on phone, single row on laptop */}
      <section className="card card-pad mb-3 sm:mb-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between md:gap-4">
          <div className="flex min-w-0 items-start justify-between gap-3 md:items-center md:justify-start md:gap-4">
            <div className="flex min-w-0 flex-col gap-1 md:flex-row md:items-baseline md:gap-3">
              <div className="metric text-[1.75rem] leading-none tracking-tight sm:text-[2rem]">
                {num(price?.price, 2)}
              </div>
              <div
                className={`metric text-[0.8rem] ${
                  (price?.change ?? 0) >= 0 ? 'up' : 'down'
                }`}
              >
                {(price?.change ?? 0) >= 0 ? '+' : ''}
                {num(price?.change, 2)} ({num(price?.change_pct, 2)}%)
              </div>
            </div>
            <div className="flex shrink-0 gap-1.5 md:hidden">
              <span className={live ? 'chip chip-live' : 'chip chip-paper'}>
                {live ? 'LIVE' : 'PAPER'}
              </span>
              <span className="chip text-[0.65rem]">
                {status?.market_open ? 'Open' : 'Closed'}
              </span>
            </div>
          </div>

          <div className="flex min-w-0 flex-col gap-2 md:flex-row md:flex-wrap md:items-center md:justify-end md:gap-2.5">
            <div className="hidden md:contents">
              <span className={live ? 'chip chip-live' : 'chip chip-paper'}>
                {live ? 'LIVE' : 'PAPER'}
              </span>
              <span className="chip">
                {status?.market_open ? 'Market open' : 'Market closed'}
              </span>
            </div>
            <BrokerChip broker={status?.broker} running={running} />
            <span className="chip max-w-full truncate" title={status?.broker?.message}>
              <span className={`dot ${status?.broker?.feed_connected ? 'dot-on' : 'dot-off'}`} />
              Cash{' '}
              {status?.broker?.available_cash == null
                ? '—'
                : inr(status.broker.available_cash)}
            </span>
            <button
              className={`btn w-full md:w-auto ${running ? 'btn-stop' : 'btn-start'}`}
              disabled={busy}
              onClick={() => act(running ? api.stop : api.start)}
            >
              {running ? 'Stop bot' : 'Start bot'}
            </button>
          </div>
        </div>
      </section>

      {status?.broker?.status === 'failed' && (
        <div className="card mb-3 break-words border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-3 py-2.5 text-[0.78rem] text-[var(--red)] sm:mb-4">
          {status.broker.message}. Check Settings → credentials, then restart.
        </div>
      )}
      {!running && status?.broker && !status.broker.credentials_configured && (
        <div className="card mb-3 break-words border-[color-mix(in_srgb,var(--amber)_40%,transparent)] px-3 py-2.5 text-[0.78rem] text-[var(--muted)] sm:mb-4">
          Angel One credentials missing — add them in Settings.
        </div>
      )}

      {/* Position first on mobile when live in a trade */}
      <div className="mb-3 sm:mb-4 lg:hidden">
        <PositionCard
          trade={trade}
          position={position}
          busy={busy}
          onExit={() => act(api.exitTrade)}
        />
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:mb-4 sm:grid-cols-3 sm:gap-3 xl:grid-cols-5">
        <Tile
          label="Today P&L"
          value={inr(status?.today_pnl ?? 0)}
          tone={(status?.today_pnl ?? 0) >= 0 ? 'up' : 'down'}
        />
        <Tile
          label="Trades"
          value={`${status?.today_trades ?? 0}`}
          sub={`${status?.wins ?? 0}W / ${status?.losses ?? 0}L`}
        />
        <Tile
          label="All-time"
          value={inr(totalPnl)}
          tone={totalPnl >= 0 ? 'up' : 'down'}
          className={inTrade ? 'hidden sm:block' : ''}
        />
        <Tile
          label="Return"
          value={
            totalReturnPct === null
              ? '—'
              : `${totalReturnPct >= 0 ? '+' : ''}${num(totalReturnPct, 1)}%`
          }
          tone={
            totalReturnPct === null
              ? undefined
              : totalReturnPct >= 0
                ? 'up'
                : 'down'
          }
        />
        <Tile
          label="Win rate"
          value={`${num(status?.all_time_win_rate, 0)}%`}
          className="col-span-2 sm:col-span-1"
        />
      </div>

      <div className="grid min-w-0 gap-3 sm:gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <div className="flex min-w-0 flex-col gap-3 sm:gap-4">
          <div className="min-w-0 overflow-hidden">
            <Chart data={candles} strategy={strategy} />
          </div>

          <section className="card card-pad lg:hidden">
            <div className="label mb-2">Session</div>
            <div className="mb-2 flex gap-1">
              {PHASES.map((phase, i) => (
                <div key={phase.key} className="min-w-0 flex-1 text-center">
                  <div
                    className={`h-1 rounded-full ${
                      activeIndex >= 0 && i <= activeIndex
                        ? 'bg-[var(--blue)]'
                        : 'bg-[var(--border)]'
                    }`}
                  />
                  <div
                    className={`mt-1 truncate text-[0.62rem] ${
                      i === activeIndex ? 'text-[var(--text)]' : 'text-[var(--faint)]'
                    }`}
                  >
                    {phase.label}
                  </div>
                </div>
              ))}
            </div>
            <p className="m-0 text-[0.78rem] leading-snug text-[var(--muted)]">
              {strategy?.phase_description || status?.market_status || 'Waiting for the bot.'}
            </p>
          </section>
        </div>

        <aside className="flex min-w-0 flex-col gap-3 sm:gap-4">
          <div className="hidden lg:block">
            <PositionCard
              trade={trade}
              position={position}
              busy={busy}
              onExit={() => act(api.exitTrade)}
            />
          </div>

          <section className="card card-pad hidden lg:block">
            <div className="label mb-3">Session</div>
            <div className="mb-3 flex gap-1">
              {PHASES.map((phase, i) => (
                <div key={phase.key} className="flex-1 text-center" title={phase.key}>
                  <div
                    className={`h-1 rounded-full ${
                      activeIndex >= 0 && i <= activeIndex
                        ? 'bg-[var(--blue)]'
                        : 'bg-[var(--border)]'
                    }`}
                  />
                  <div
                    className={`mt-1.5 text-[0.66rem] ${
                      i === activeIndex ? 'text-[var(--text)]' : 'text-[var(--faint)]'
                    }`}
                  >
                    {phase.label}
                  </div>
                </div>
              ))}
            </div>
            <p className="m-0 text-[0.8rem] leading-snug text-[var(--muted)]">
              {strategy?.phase_description || status?.market_status || 'Waiting for the bot.'}
            </p>
            {strategy?.skip_reason && (
              <p className="m-0 mt-2 text-[0.75rem] warn">{strategy.skip_reason}</p>
            )}
          </section>

          <section className="card card-pad">
            <div className="label mb-2">Connection</div>
            <Row label="Status" value={brokerStatusLabel} />
            <Row
              label="Feed"
              value={status?.broker?.feed_connected ? 'Live' : 'Idle'}
            />
            <Row
              label="Cash"
              value={
                status?.broker?.available_cash == null
                  ? '—'
                  : inr(status.broker.available_cash)
              }
            />
            <Row
              label="Credentials"
              value={status?.broker?.credentials_configured ? 'Saved' : 'Missing'}
            />
          </section>

          <section className="card card-pad">
            <div className="label mb-2">Opening range</div>
            <Row label="High" value={num(strategy?.orb_high, 1)} />
            <Row label="Low" value={num(strategy?.orb_low, 1)} />
            <Row
              label="Range"
              value={
                strategy?.orb_range
                  ? `${num(strategy.orb_range, 1)} (${num(strategy.orb_range_pct, 2)}%)`
                  : '—'
              }
            />
            <Row
              label="Range check"
              value={formatRangeCheck(strategy)}
            />
            <Row
              label="Trades"
              value={`${strategy?.trades_taken ?? 0} / ${strategy?.max_trades ?? 1}`}
            />
          </section>
        </aside>
      </div>
    </main>
  );
}

function PositionCard({
  trade,
  position,
  busy,
  onExit,
}: {
  trade?: BotStatus['active_trade'];
  position?: NonNullable<BotStatus['strategy']>['position'];
  busy: boolean;
  onExit: () => void;
}) {
  return (
    <section className="card card-pad">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="label">Position</span>
        {position && (
          <span className={position.direction === 'LONG' ? 'chip up' : 'chip down'}>
            {position.direction}
          </span>
        )}
      </div>

      {trade && position ? (
        <>
          <div className="mb-2">
            <div
              className={`metric text-[1.45rem] leading-none sm:text-[1.5rem] ${
                (trade.live_pnl ?? 0) >= 0 ? 'up' : 'down'
              }`}
            >
              {inr(trade.live_pnl ?? 0)}
            </div>
            <div className="mt-1 truncate text-[0.72rem] text-[var(--faint)]">
              {trade.trading_symbol} · {trade.quantity} qty
            </div>
          </div>
          <Row label="Premium" value={`${num(trade.entry_price)} → ${num(trade.current_price)}`} />
          <Row
            label="Capital"
            value={inr(
              trade.capital_used ??
                (trade.entry_price && trade.quantity
                  ? trade.entry_price * trade.quantity
                  : 0),
            )}
          />
          <Row label="Stop" value={num(position.stop_index, 1)} />
          <Row label="Target" value={num(position.target_index, 1)} />
          <button className="btn btn-danger mt-3 w-full" disabled={busy} onClick={onExit}>
            Exit now
          </button>
        </>
      ) : (
        <p className="m-0 text-[0.8rem] text-[var(--faint)]">No open position.</p>
      )}
    </section>
  );
}

function BrokerChip({
  broker,
  running,
}: {
  broker?: BrokerStatus;
  running: boolean;
}) {
  const status = running ? broker?.status ?? 'stopped' : 'stopped';
  const feedOn = broker?.feed_connected ?? false;

  let short = 'Stopped';
  let full = 'Angel One · Bot stopped';
  let on = false;
  let bad = false;

  if (status === 'connected') {
    on = feedOn;
    short = feedOn ? 'Connected' : 'Logged in';
    full = feedOn ? 'Angel One · Connected' : 'Angel One · Logged in, feed idle';
  } else if (status === 'failed') {
    bad = true;
    short = 'Login failed';
    full = 'Angel One · Login failed';
  } else if (status === 'playback') {
    short = 'Playback';
    full = 'Angel One · Not used (playback)';
  } else if (!running && broker && !broker.credentials_configured) {
    bad = true;
    short = 'No credentials';
    full = 'Angel One · Credentials missing';
  } else if (!running && broker?.credentials_configured) {
    short = 'Ready';
    full = 'Angel One · Ready (bot stopped)';
  }

  return (
    <span className={`chip max-w-full ${bad ? 'chip-live' : ''}`} title={broker?.message ?? full}>
      <span className={`dot ${on ? 'dot-on' : 'dot-off'}`} />
      <span className="sm:hidden">{short}</span>
      <span className="hidden sm:inline">{full}</span>
    </span>
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
    <div className={`card card-pad min-w-0 ${className}`}>
      <div className="label truncate">{label}</div>
      <div className={`metric mt-1 truncate text-[1rem] sm:mt-1.5 sm:text-[1.1rem] ${tone ?? ''}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[0.68rem] text-[var(--faint)]">{sub}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-[0.78rem] sm:text-[0.8rem]">
      <span className="shrink-0 text-[var(--muted)]">{label}</span>
      <span className="metric max-w-[60%] break-all text-right">{value}</span>
    </div>
  );
}

function formatRangeCheck(strategy: BotStatus['strategy'] | null | undefined): string {
  const min = strategy?.min_or_pct ?? 0.25;
  const max = strategy?.max_or_pct ?? 2;
  const band = `${num(min, 2)}–${num(max, 2)}%`;
  const pct = strategy?.orb_range_pct;

  if (strategy?.phase === 'BUILDING_RANGE' || pct == null) {
    return `Building · allow ${band}`;
  }
  if (strategy?.phase === 'SKIP_DAY') {
    return `Skip · ${num(pct, 2)}% (need ${band})`;
  }
  if (pct < min) return `Too narrow · ${num(pct, 2)}% < ${num(min, 2)}%`;
  if (pct > max) return `Too wide · ${num(pct, 2)}% > ${num(max, 2)}%`;
  return `OK · ${num(pct, 2)}% in ${band}`;
}
