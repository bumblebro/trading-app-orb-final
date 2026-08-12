'use client';

import { useCallback, useState } from 'react';
import { api } from '@/lib/api';
import { useLoad } from '@/lib/hooks';
import type { Settings } from '@/lib/types';

type FieldType = 'text' | 'number' | 'password' | 'time' | 'select';

interface Field {
  key: string;
  label: string;
  type?: FieldType;
  options?: { value: string; label: string }[];
  hint?: string;
  step?: string;
}

interface Group {
  title: string;
  blurb: string;
  fields: Field[];
}

/**
 * Live defaults for a larger account (~₹1L).
 * Credentials and playback paths are left alone.
 */
const LIVE_DEFAULTS_1L: Settings = {
  trading_mode: 'live',
  data_source: 'smartapi',

  orb_or_minutes: '60',
  orb_min_range_pct: '0.25',
  orb_max_range_pct: '2.00',
  orb_entry_trigger: 'close',
  orb_confirm_interval_mins: '3',
  orb_breakout_buffer_pct: '0.05',
  orb_entry_cutoff: '13:30',
  orb_sl_mode: 'or_opposite',
  orb_sl_fraction: '0.50',
  orb_target_r: '2.0',
  orb_breakeven_after_r: '1.0',
  orb_trail_r: '0',
  orb_max_trades_per_day: '1',
  orb_allow_reversal: 'false',
  option_sl_pct: '100.0',
  square_off_time: '15:15',

  position_sizing_mode: 'risk_percent',
  fixed_lots: '1',
  lot_size: '65',
  min_lots: '1',
  max_lots: '5',
  risk_percent_per_trade: '2.0',
  max_capital_per_trade_pct: '15.0',
  max_daily_loss: '10000',
  initial_capital: '100000',
};

const GROUPS: Group[] = [
  {
    title: 'Mode',
    blurb: 'Paper trades are simulated end to end. Live requires BOT_API_TOKEN on the server.',
    fields: [
      {
        key: 'trading_mode',
        label: 'Trading mode',
        type: 'select',
        options: [
          { value: 'paper', label: 'Paper' },
          { value: 'live', label: 'Live' },
        ],
      },
      {
        key: 'data_source',
        label: 'Price source',
        type: 'select',
        options: [
          { value: 'smartapi', label: 'Angel One live feed' },
          { value: 'playback', label: 'CSV playback' },
        ],
      },
    ],
  },
  {
    title: 'Opening range',
    blurb: 'How the range is built and what counts as a valid breakout.',
    fields: [
      { key: 'orb_or_minutes', label: 'Range length (minutes)', type: 'number', hint: 'Minutes from 09:15 used to set the high/low.' },
      { key: 'orb_min_range_pct', label: 'Min range %', type: 'number', step: '0.01', hint: 'Skip the day if the range is narrower — usually noise.' },
      { key: 'orb_max_range_pct', label: 'Max range %', type: 'number', step: '0.01', hint: 'Skip gap days where the stop would be too wide.' },
      {
        key: 'orb_entry_trigger',
        label: 'Breakout trigger',
        type: 'select',
        options: [
          { value: 'close', label: 'Candle close beyond the level' },
          { value: 'touch', label: 'Any touch of the level' },
        ],
      },
      { key: 'orb_confirm_interval_mins', label: 'Confirmation timeframe (min)', type: 'number', hint: 'Aggregate 1-min bars into this timeframe before confirming.' },
      { key: 'orb_breakout_buffer_pct', label: 'Breakout buffer %', type: 'number', step: '0.01', hint: 'Extra distance past the level to filter false breaks.' },
      { key: 'orb_entry_cutoff', label: 'Last entry time', type: 'time' },
    ],
  },
  {
    title: 'Exits',
    blurb: 'Where the stop sits and how profits are taken.',
    fields: [
      {
        key: 'orb_sl_mode',
        label: 'Stop loss',
        type: 'select',
        options: [
          { value: 'or_opposite', label: 'Opposite side of the range' },
          { value: 'or_fraction', label: 'Fraction of the range' },
        ],
      },
      { key: 'orb_sl_fraction', label: 'Stop fraction', type: 'number', step: '0.05', hint: 'Used only when the stop mode is a fraction of the range.' },
      { key: 'orb_target_r', label: 'Target (R multiple)', type: 'number', step: '0.1' },
      { key: 'orb_breakeven_after_r', label: 'Move to breakeven at (R)', type: 'number', step: '0.1', hint: '0 disables the breakeven move.' },
      { key: 'orb_trail_r', label: 'Trail stop every (R)', type: 'number', step: '0.1', hint: '0 disables trailing.' },
      { key: 'option_sl_pct', label: 'Hard premium stop (%)', type: 'number', step: '1', hint: 'Backstop on the option premium regardless of the index stop.' },
      { key: 'square_off_time', label: 'Square off time', type: 'time' },
    ],
  },
  {
    title: 'Risk & sizing',
    blurb: 'Position size and the daily kill switch.',
    fields: [
      {
        key: 'position_sizing_mode',
        label: 'Sizing mode',
        type: 'select',
        options: [
          { value: 'fixed_lots', label: 'Fixed lots' },
          { value: 'risk_percent', label: 'Risk % of capital' },
        ],
      },
      { key: 'fixed_lots', label: 'Fixed lots', type: 'number' },
      { key: 'risk_percent_per_trade', label: 'Risk per trade (%)', type: 'number', step: '0.1' },
      { key: 'lot_size', label: 'Lot size', type: 'number' },
      { key: 'min_lots', label: 'Min lots', type: 'number' },
      { key: 'max_lots', label: 'Max lots', type: 'number' },
      { key: 'max_capital_per_trade_pct', label: 'Max capital per trade (%)', type: 'number', step: '0.5' },
      { key: 'max_daily_loss', label: 'Max daily loss (₹)', type: 'number', hint: 'Bot flattens and stops trading for the day when hit.' },
      { key: 'orb_max_trades_per_day', label: 'Max trades per day', type: 'number' },
      {
        key: 'orb_allow_reversal',
        label: 'Allow reversal trade',
        type: 'select',
        options: [
          { value: 'false', label: 'No' },
          { value: 'true', label: 'Yes — trade the other side after a stop' },
        ],
      },
      { key: 'initial_capital', label: 'Capital (₹)', type: 'number' },
    ],
  },
  {
    title: 'Broker credentials',
    blurb: 'Stored server-side and never sent back to the browser. Leave masked fields alone to keep the saved value.',
    fields: [
      { key: 'api_key', label: 'API key', type: 'password' },
      { key: 'client_id', label: 'Client ID' },
      { key: 'pin', label: 'PIN', type: 'password' },
      { key: 'totp_secret', label: 'TOTP secret', type: 'password' },
    ],
  },
  {
    title: 'Playback',
    blurb: 'Replay historical CSV data through the exact same strategy code as live.',
    fields: [
      { key: 'playback_file', label: 'CSV file' },
      { key: 'playback_speed', label: 'Speed (bars/sec)', type: 'number' },
      { key: 'playback_start_date', label: 'Start date', hint: 'YYYY-MM-DD, blank for the beginning.' },
      { key: 'playback_end_date', label: 'End date', hint: 'YYYY-MM-DD, blank for the end.' },
    ],
  },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [secretKeys, setSecretKeys] = useState<string[]>([]);
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.settings();
      setSettings(data.settings ?? {});
      setSecretKeys(data.secret_keys ?? []);
      setStatus(null);
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : 'Cannot load settings', ok: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useLoad(load);

  const set = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty((prev) => ({ ...prev, [key]: value }));
  };

  const save = async () => {
    if (!Object.keys(dirty).length) return;
    setSaving(true);
    try {
      await api.saveSettings(dirty);
      setDirty({});
      setStatus({ text: 'Saved. Restart the bot to apply credential or data-source changes.', ok: true });
      await load();
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : 'Save failed', ok: false });
    } finally {
      setSaving(false);
    }
  };

  const clearData = async () => {
    if (
      !confirm(
        'Clear all trades, signals and logs?\n\nSettings and Angel credentials are kept. Stop the bot first if it is running.',
      )
    ) {
      return;
    }
    try {
      await api.clearData();
      setStatus({ text: 'All trades and logs cleared. Settings kept.', ok: true });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : 'Clear failed', ok: false });
    }
  };

  const applyLiveDefaults = async () => {
    if (
      !confirm(
        'Apply live defaults for ~₹1L capital?\n\n' +
          '• Live + Angel feed\n' +
          '• Risk 2% per trade, max 5 lots, lot size 65\n' +
          '• Max capital / trade 15%\n' +
          '• Max daily loss ₹10,000, capital ₹1,00,000\n' +
          '• Standard ORB strategy exits\n\n' +
          'Broker credentials and playback paths are kept.\n' +
          'Not for ₹15k Phase 0 — use Fixed 1 lot / max capital 100% there.\n' +
          'Stop → Start the bot after save.',
      )
    ) {
      return;
    }

    setSettings((prev) => ({ ...prev, ...LIVE_DEFAULTS_1L }));
    setDirty((prev) => ({ ...prev, ...LIVE_DEFAULTS_1L }));
    setSaving(true);
    try {
      await api.saveSettings(LIVE_DEFAULTS_1L);
      setDirty({});
      setStatus({
        text: 'Live defaults (~₹1L) saved. Stop → Start the bot to apply.',
        ok: true,
      });
      await load();
    } catch (err) {
      setStatus({
        text: err instanceof Error ? err.message : 'Could not save live defaults',
        ok: false,
      });
    } finally {
      setSaving(false);
    }
  };

  const dirtyCount = Object.keys(dirty).length;

  return (
    <main className="page-shell py-4 pb-28 sm:py-5 sm:pb-24">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="m-0 text-[1.05rem] font-semibold">Settings</h1>
          <p className="m-0 mt-0.5 text-[0.78rem] text-[var(--faint)]">
            Strategy changes apply on the next candle; credentials need a restart.
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <button className="btn w-full sm:w-auto" onClick={applyLiveDefaults} disabled={saving}>
            Apply ₹1L live defaults
          </button>
          <button className="btn btn-danger w-full sm:w-auto" onClick={clearData}>
            Clear trades &amp; logs
          </button>
        </div>
      </div>

      {status && (
        <div
          className={`card mb-4 px-4 py-2.5 text-[0.8rem] ${
            status.ok
              ? 'border-[color-mix(in_srgb,var(--green)_40%,transparent)] text-[var(--green)]'
              : 'border-[color-mix(in_srgb,var(--red)_40%,transparent)] text-[var(--red)]'
          }`}
        >
          {status.text}
        </div>
      )}

      {loading ? (
        <div className="card card-pad text-[0.85rem] text-[var(--faint)]">Loading settings…</div>
      ) : (
        <div className="flex flex-col gap-4">
          {GROUPS.map((group) => (
            <section key={group.title} className="card card-pad">
              <h2 className="m-0 text-[0.9rem] font-semibold">{group.title}</h2>
              <p className="m-0 mt-0.5 mb-4 text-[0.75rem] text-[var(--faint)]">{group.blurb}</p>
              <div className="grid gap-4 sm:grid-cols-2">
                {group.fields.map((field) => (
                  <FieldInput
                    key={field.key}
                    field={field}
                    value={settings[field.key] ?? ''}
                    secret={secretKeys.includes(field.key)}
                    onChange={(value) => set(field.key, value)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <div className="fixed inset-x-0 bottom-0 border-t border-[var(--border)] bg-[var(--bg)]/92 backdrop-blur pb-[env(safe-area-inset-bottom)]">
        <div className="page-shell flex items-center justify-between gap-3 py-3 sm:gap-4">
          <span className="min-w-0 truncate text-[0.78rem] text-[var(--muted)]">
            {dirtyCount ? `${dirtyCount} unsaved change${dirtyCount > 1 ? 's' : ''}` : 'All changes saved'}
          </span>
          <button className="btn btn-start shrink-0" onClick={save} disabled={saving || !dirtyCount}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </main>
  );
}

function FieldInput({
  field,
  value,
  secret,
  onChange,
}: {
  field: Field;
  value: string;
  secret: boolean;
  onChange: (value: string) => void;
}) {
  const masked = secret && /^\*+$/.test(value);

  return (
    <label className="flex flex-col gap-1.5">
      <span className="label">{field.label}</span>
      {field.type === 'select' ? (
        <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          className="field"
          type={field.type === 'password' && !masked ? 'password' : field.type === 'number' ? 'number' : field.type === 'time' ? 'time' : 'text'}
          step={field.step}
          value={value}
          placeholder={masked ? 'Stored — type to replace' : undefined}
          onChange={(e) => onChange(e.target.value)}
          onFocus={(e) => {
            if (masked) {
              e.target.select();
            }
          }}
        />
      )}
      {field.hint && <span className="text-[0.7rem] leading-snug text-[var(--faint)]">{field.hint}</span>}
    </label>
  );
}
