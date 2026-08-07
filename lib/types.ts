export type Phase =
  | 'PREOPEN'
  | 'BUILDING_RANGE'
  | 'WAITING_BREAKOUT'
  | 'IN_TRADE'
  | 'SKIP_DAY'
  | 'DONE'
  | 'CLOSED'
  | 'DAILY_LOSS_LIMIT';

export interface PriceInfo {
  price: number;
  change: number;
  change_pct: number;
  connected: boolean;
  last_update: string | null;
  tick_count?: number;
  playback?: boolean;
}

export interface StrategyState {
  phase: Phase;
  phase_description: string;
  orb_high: number | null;
  orb_low: number | null;
  orb_range: number | null;
  orb_range_pct: number | null;
  orb_locked_at: string | null;
  skip_reason: string | null;
  trades_taken: number;
  max_trades: number;
  entry_cutoff: string;
  or_minutes: number;
  signal?: string;
  last_breakout: { direction: string; price: number; time: string } | null;
  position?: {
    direction: 'LONG' | 'SHORT';
    entry_index: number;
    stop_index: number;
    target_index: number;
    risk_points: number;
    breakeven_done: boolean;
  };
}

export interface Trade {
  id: number;
  date: string;
  time: string;
  type: 'CE' | 'PE';
  direction: 'LONG' | 'SHORT' | null;
  strike_price: number;
  trading_symbol: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  status: 'open' | 'win' | 'loss';
  exit_reason: string | null;
  mode: 'paper' | 'live';
  capital_used: number | null;
  total_capital: number | null;
  orb_high: number | null;
  orb_low: number | null;
  orb_range: number | null;
  underlying_entry_price: number | null;
  underlying_exit_price: number | null;
  stop_index: number | null;
  target_index: number | null;
  risk_points: number | null;
  pnl: number;
  net_pnl: number | null;
  exit_time: string | null;
  current_price?: number;
  live_pnl?: number;
}

export interface BrokerStatus {
  name: string;
  status: 'stopped' | 'playback' | 'connected' | 'failed' | string;
  message: string;
  connected: boolean;
  feed_connected: boolean;
  credentials_configured: boolean;
  available_cash?: number | null;
}

export interface BotStatus {
  running: boolean;
  mode: 'paper' | 'live';
  signal: string;
  strategy: StrategyState;
  price: PriceInfo;
  today_pnl: number;
  today_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_trades: number;
  all_time_win_rate: number;
  total_charges: number;
  capital: number;
  initial_capital: number;
  market_open: boolean;
  market_status: string;
  is_trading_day: boolean;
  is_playback: boolean;
  session_date: string | null;
  data_source?: string;
  broker?: BrokerStatus;
  active_trade?: Trade;
  error?: string;
  offline?: boolean;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface CandlePayload {
  candles: Candle[];
  orb: { high: number; low: number; range: number; bars: number; date: string } | null;
  or_minutes: number;
}

export interface EquityPoint {
  date: string;
  pnl: number;
  trades: number;
  cumulative_pnl: number;
}

export interface ExitReasonRow {
  reason: string;
  count: number;
  net_pnl: number;
}

export interface YearlyPnlRow {
  year: string;
  net_pnl: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
}

export interface Analytics {
  equity_curve: EquityPoint[];
  exit_reasons: ExitReasonRow[];
  yearly_pnl?: YearlyPnlRow[];
}

export interface TradesResponse {
  trades: Trade[];
  summary: {
    all_time_pnl: number;
    all_time_gross_pnl: number;
    all_time_charges: number;
    all_time_trades: number;
    all_time_win_rate: number;
    wins: number;
    losses: number;
    month_pnl: number;
    month_trades: number;
    month_label: string;
    year_pnl: number;
    year_trades: number;
    year_label: string;
  };
}

export type Settings = Record<string, string>;
