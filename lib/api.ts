import type {
  Analytics, BotStatus, CandlePayload, Settings, StrategyState, TradesResponse,
} from './types';

const BASE = '/api/bot';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(payload?.error || payload?.detail || `Request failed (${res.status})`);
  }
  return payload as T;
}

export const api = {
  status: () => call<BotStatus>('/status'),
  orb: () => call<StrategyState>('/orb'),
  candles: () => call<CandlePayload>('/candles'),
  analytics: (mode?: string) => call<Analytics>(`/analytics${mode ? `?mode=${mode}` : ''}`),

  start: () => call<{ status: string }>('/start', { method: 'POST' }),
  stop: () => call<{ status: string }>('/stop', { method: 'POST' }),
  exitTrade: () => call<{ status: string; message: string }>('/exit-trade', {
    method: 'POST',
    body: JSON.stringify({}),
  }),

  trades: (params: { mode?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.mode) query.set('mode', params.mode);
    query.set('limit', String(params.limit ?? 200));
    return call<TradesResponse>(`/trades?${query}`);
  },

  settings: () => call<{ settings: Settings; secret_keys: string[] }>('/settings'),
  saveSettings: (settings: Partial<Settings>) => call<{ status: string }>('/settings', {
    method: 'POST',
    body: JSON.stringify({ settings }),
  }),

  clearData: () => call<{ status: string }>('/clear-data', { method: 'POST' }),
  recoverPosition: () =>
    call<{ status: string; trade_id?: number; symbol?: string; message?: string }>(
      '/recover-position',
      { method: 'POST' },
    ),
  logs: (limit = 100) => call<{ logs: LogEntry[] }>(`/logs?limit=${limit}`),
};

export interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  message: string;
}

export const inr = (value: number, decimals = 0) =>
  `${value < 0 ? '-' : ''}₹${Math.abs(value).toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;

export const num = (value: number | null | undefined, decimals = 2) =>
  value === null || value === undefined ? '—' : value.toFixed(decimals);
