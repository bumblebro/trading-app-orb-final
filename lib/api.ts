import type { Settings } from './types';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

async function fetchBot(path: string, options?: RequestInit) {
  const res = await fetch(`${BOT_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`Bot API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// --- Client-side API helpers (call Next.js API routes) ---

const API_BASE = '/api';

async function fetchAPI(path: string, options?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error: ${res.status} - ${text}`);
  }
  return res.json();
}

// Public API functions for frontend components
export const api = {
  // Price & Market Data
  getPrice: () => fetchAPI('/price'),
  getSignal: () => fetchAPI('/signal'),
  getCandles: () => fetchAPI('/candles'),

  // Bot Control
  getBotStatus: () => fetchAPI('/bot/status'),
  startBot: () => fetchAPI('/bot/start', { method: 'POST' }),
  stopBot: () => fetchAPI('/bot/stop', { method: 'POST' }),

  // Trades
  getTrades: (params?: { mode?: string; date_from?: string; date_to?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.mode) searchParams.set('mode', params.mode);
    if (params?.date_from) searchParams.set('date_from', params.date_from);
    if (params?.date_to) searchParams.set('date_to', params.date_to);
    const query = searchParams.toString();
    return fetchAPI(`/trades${query ? `?${query}` : ''}`);
  },
  getActiveTrade: () => fetchAPI('/trades/active'),
  exitTrade: (price?: number) => fetchAPI('/exit-trade', {
    method: 'POST',
    body: JSON.stringify({ price }),
  }),

  // P&L
  getPnL: (mode?: string) => {
    const query = mode ? `?mode=${mode}` : '';
    return fetchAPI(`/pnl${query}`);
  },

  // Settings
  getSettings: () => fetchAPI('/settings'),
  saveSettings: (settings: Partial<Settings> | Record<string, string>) => fetchAPI('/settings', {
    method: 'POST',
    body: JSON.stringify({ settings }),
  }),

  // Logs
  getLogs: (limit?: number, category?: string) => {
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (category) params.set('category', category);
    const query = params.toString();
    return fetchAPI(`/logs${query ? `?${query}` : ''}`);
  },

  // Margin
  getMargin: () => fetchAPI('/margin'),
};

// Server-side bot API (used by Next.js API routes)
export const botApi = {
  get: (path: string) => fetchBot(path),
  post: (path: string, body?: unknown) => fetchBot(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  }),
};
