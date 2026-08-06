'use client';

import dynamic from 'next/dynamic';
import { useCallback, useState } from 'react';
import { api, inr, num } from '@/lib/api';
import { usePoll } from '@/lib/hooks';
import type { BotStatus, BrokerStatus, CandlePayload, Phase } from '@/lib/types';

const Chart = dynamic(() => import('@/components/Chart'), { ssr: false });

const PHASES: { key: Phase; label: string }[] = [
  { key: 'BUILDING_RANGE', label: 'Range' },
  { key: 'WAITING_BREAKOUT', label: 'Watching' },
  { key: 'IN_TRADE', label: 'In trade' },
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

  const initialCapital = status?.initial_capital || 0;
  const totalPnl = status?.total_pnl ?? 0;
  const totalReturnPct =
    initialCapital > 0 ? (totalPnl / initialCapital) * 100 : null;

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-4 sm:px-5 sm:py-5">
      {error && (
        <div className="card mb-4 border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-4 py-2.5 text-[0.8rem] text-[var(--red)]">
          {error}
        </div>
      )}

      {/* ---------------------------------------------------------- header */}
      <section className="card card-pad mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-4">
        <div className="flex min-w-0 flex-wrap items-baseline gap-2 sm:gap-3">
          <span className="metric text-[1.65rem] leading-none sm:text-[2rem]">{num(price?.price, 2)}</span>
          <span
            className={`metric text-[0.82rem] sm:text-[0.9rem] ${
              (price?.change ?? 0) >= 0 ? 'up' : 'down'
            }`}
          >
            {(price?.change ?? 0) >= 0 ? '+' : ''}
            {num(price?.change, 2)} ({num(price?.change_pct, 2)}%)
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2 sm:gap-2.5">
          <span className={live ? 'chip chip-live' : 'chip chip-paper'}>
            {live ? 'LIVE' : 'PAPER'}
          </span>
          <BrokerChip broker={status?.broker} running={running} />
          <span className="chip" title={status?.market_status}>
            {status?.market_open ? 'Market open' : 'Market closed'}
          </span>
          <button
            className={`btn w-full sm:w-auto ${running ? 'btn-stop' : 'btn-start'}`}
            disabled={busy}
            onClick={() => act(running ? api.stop : api.start)}
          >
            {running ? 'Stop bot' : 'Start bot'}
          </button>
        </div>
      </section>

      {status?.broker?.status === 'failed' && (
        <div className="card mb-4 border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-4 py-2.5 text-[0.8rem] text-[var(--red)]">
          {status.broker.message}. Check Settings → Broker credentials, then restart the bot.
        </div>
      )}
      {!running && status?.broker && !status.broker.credentials_configured && (
        <div className="card mb-4 border-[color-mix(in_srgb,var(--amber)_40%,transparent)] px-4 py-2.5 text-[0.8rem] text-[var(--muted)]">
          Angel One credentials are not saved yet. Add them in Settings before using the live feed.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="flex flex-col gap-4">
          <Chart data={candles} strategy={strategy} />

          <div className="grid grid-cols-2 gap-3 sm:gap-4 sm:grid-cols-3 xl:grid-cols-5">
            <Tile
              label="Today P&L"
              value={inr(status?.today_pnl ?? 0)}
              tone={(status?.today_pnl ?? 0) >= 0 ? 'up' : 'down'}
            />
            <Tile
              label="Today trades"
              value={`${status?.today_trades ?? 0}`}
              sub={`${status?.wins ?? 0}W / ${status?.losses ?? 0}L`}
            />
            <Tile
              label="All-time P&L"
              value={inr(totalPnl)}
              tone={totalPnl >= 0 ? 'up' : 'down'}
              sub={`${status?.total_trades ?? 0} trades`}
            />
            <Tile
              label="Total return"
              value={totalReturnPct === null ? '—' : `${totalReturnPct >= 0 ? '+' : ''}${num(totalReturnPct, 2)}%`}
              tone={
                totalReturnPct === null
                  ? undefined
                  : totalReturnPct >= 0
                    ? 'up'
                    : 'down'
              }
              sub={
                initialCapital > 0
                  ? `On ${inr(initialCapital)} capital`
                  : undefined
              }
            />
            <Tile
              label="Win rate"
              value={`${num(status?.all_time_win_rate, 1)}%`}
              sub={`Capital ${inr(status?.capital ?? 0)}`}
            />
          </div>
        </div>

        {/* ------------------------------------------------------- sidebar */}
        <aside className="flex flex-col gap-4">
          <section className="card card-pad">
            <div className="label mb-3">Session</div>
            <div className="mb-3 flex gap-1">
              {PHASES.map((phase, i) => (
                <div
                  key={phase.key}
                  className="flex-1 text-center"
                  title={phase.key}
                >
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
            <div className="label mb-3">Connection</div>
            <Row label="Broker" value="Angel One" />
            <Row
              label="Status"
              value={
                status?.broker?.status === 'connected'
                  ? status.broker.feed_connected
                    ? 'Connected'
                    : 'Logged in'
                  : status?.broker?.status === 'failed'
                    ? 'Login failed'
                    : status?.broker?.status === 'playback'
                      ? 'Playback (not used)'
                      : running
                        ? '—'
                        : 'Bot stopped'
              }
            />
            <Row
              label="Feed"
              value={status?.broker?.feed_connected ? 'Live' : 'Idle'}
            />
            <Row
              label="Credentials"
              value={
                status?.broker?.credentials_configured ? 'Saved' : 'Missing'
              }
            />
            <Row
              label="Available cash"
              value={
                status?.broker?.available_cash == null
                  ? '—'
                  : inr(status.broker.available_cash)
              }
            />
            {status?.broker?.message && (
              <p className="m-0 mt-2 text-[0.72rem] leading-snug text-[var(--faint)]">
                {status.broker.message}
              </p>
            )}
          </section>

          <section className="card card-pad">
            <div className="label mb-3">Opening range</div>
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
              label="Trades"
              value={`${strategy?.trades_taken ?? 0} / ${strategy?.max_trades ?? 1}`}
            />
            <Row label="Entry cutoff" value={strategy?.entry_cutoff ?? '—'} />
          </section>

          <section className="card card-pad">
            <div className="mb-3 flex items-center justify-between">
              <span className="label">Position</span>
              {position && (
                <span className={position.direction === 'LONG' ? 'chip up' : 'chip down'}>
                  {position.direction}
                </span>
              )}
            </div>

            {trade && position ? (
              <>
                <div className="mb-3">
                  <div
                    className={`metric text-[1.5rem] ${
                      (trade.live_pnl ?? 0) >= 0 ? 'up' : 'down'
                    }`}
                  >
                    {inr(trade.live_pnl ?? 0)}
                  </div>
                  <div className="text-[0.72rem] text-[var(--faint)]">
                    {trade.trading_symbol} · {trade.quantity} qty
                  </div>
                </div>
                <Row label="Premium" value={`${num(trade.entry_price)} → ${num(trade.current_price)}`} />
                <Row
                  label="Capital used"
                  value={inr(
                    trade.capital_used ??
                      (trade.entry_price && trade.quantity
                        ? trade.entry_price * trade.quantity
                        : 0),
                  )}
                />
                <Row label="Index entry" value={num(position.entry_index, 1)} />
                <Row label="Stop" value={num(position.stop_index, 1)} />
                <Row label="Target" value={num(position.target_index, 1)} />
                <Row label="Risk" value={`${num(position.risk_points, 1)} pts`} />
                {position.breakeven_done && <Row label="Stop moved" value="Breakeven" />}
                <button
                  className="btn btn-danger mt-3 w-full"
                  disabled={busy}
                  onClick={() => act(api.exitTrade)}
                >
                  Exit now
                </button>
              </>
            ) : (
              <p className="m-0 text-[0.8rem] text-[var(--faint)]">No open position.</p>
            )}
          </section>
        </aside>
      </div>
    </main>
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
    <span className={`chip ${bad ? 'chip-live' : ''}`} title={broker?.message ?? full}>
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
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'up' | 'down';
}) {
  return (
    <div className="card card-pad">
      <div className="label">{label}</div>
      <div className={`metric mt-1.5 text-[1.15rem] ${tone ?? ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[0.72rem] text-[var(--faint)]">{sub}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-[0.8rem]">
      <span className="shrink-0 text-[var(--muted)]">{label}</span>
      <span className="metric max-w-[65%] break-all text-right">{value}</span>
    </div>
  );
}
