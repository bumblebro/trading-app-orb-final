export interface PriceInfo {
  price: number;
  prev_price: number;
  change: number;
  change_pct: number;
  last_update: string | null;
  connected: boolean;
  simulation: boolean;
  indicators: {
    orb_high: number | null;
    orb_low: number | null;
    orb_range: number | null;
    orb_status: string | null;
    macd_line: number | null;
    signal_line: number | null;
    histogram: number | null;
    is_bullish: boolean | null;
    is_curling_up: boolean | null;
    is_curling_down: boolean | null;
    rsi: number | null;
    phase: string;
    ready: boolean;
  };
}

export interface Signal {
  signal: string;
  phase: string;
  phase_description: string;
  orb_status: string;
  orb_high: number | null;
  orb_low: number | null;
  orb_range: number | null;
  breakout_direction: 'UP' | 'DOWN' | 'NONE';
  breakout_price: number | null;
  breakout_time: string | null;
  pullback_timer_remaining: number | null;
  fibonacci_levels: FibonacciData | null;
  macd_confirms: boolean;
  timestamp: string;
}

export interface OrbData {
  orb_high: number | null;
  orb_low: number | null;
  orb_range: number | null;
  is_valid: boolean;
  skip_reason: string | null;
}

export interface FibonacciData {
  levels: {
    '23.6': number;
    '38.2': number;
    '50.0': number;
    '61.8': number;
    '78.6': number;
  } | null;
  entry_zone_high: number | null;
  entry_zone_low: number | null;
  stop_loss_level: number | null;
  direction: 'LONG' | 'SHORT' | null;
}

export interface StrategyPhase {
  phase: 'BUILDING_ORB' | 'WAITING_BREAKOUT' | 'ORDER_PLACED' | 'IN_TRADE' | 'SKIP_TODAY' | 'MAX_TRADES_DONE' | 'WATCHING' | 'CLOSED';
  phase_description: string;
  breakout_direction: 'LONG' | 'SHORT' | null;
  breakout_price: number | null;
  breakout_time: string | null;
}

export interface Trade {
  id: number;
  date: string;
  time: string;
  type: 'CE' | 'PE';
  strike_price: number;
  trading_symbol: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  lot_size: number;
  pnl: number;
  status: 'open' | 'closed' | 'win' | 'loss';
  exit_reason: string | null;
  mode: 'paper' | 'live';
  stop_loss: number | null;
  target: number | null;
  trailing_sl: number | null;
  underlying_entry_price?: number;
  token?: string;
  orb_high?: number;
  orb_low?: number;
  orb_range?: number;
  breakout_price?: number;
  fib_entry_level?: string;
  fib_entry_price?: number;
  fib_sl_price?: number;
  macd_at_entry?: number;
  trailing_sl_used?: number;
  current_price?: number;
  live_pnl?: number;
}

export interface PnLSummary {
  total_pnl: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  open_trades: number;
}

export interface BotStatus {
  running: boolean;
  signal: string;
  indicators: Record<string, any>;
  price: PriceInfo;
  active_trade: Trade | null;
  today_pnl: number;
  today_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_trades: number;
  mode: 'paper' | 'live';
  market_status: string;
  market_open: boolean;
  is_trading_day: boolean;
  phase: string;
  orb_status: string;
  all_time_win_rate: number;
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface LineData {
  time: number;
  value: number;
}

export interface ChartData {
  candles: CandleData[];
  orb_high: LineData[];
  orb_low: LineData[];
}

export interface Settings {
  api_key: string;
  client_id: string;
  pin: string;
  totp_secret: string;
  orb_duration: string;
  min_orb_range: string;
  max_orb_range: string;
  breakout_buffer: string;
  atm_delta: string;
  trailing_sl_enabled: string;
  trailing_sl_pct: string;
  max_trades_per_day: string;
  signal_cutoff_time: string;
  square_off_time: string;
  lot_size: string;
  position_size_mode: string;
  fixed_lots: string;
  max_capital_risk_pct: string;
  trading_mode: string;
  paper_capital: string;
  data_source: string;
  playback_file: string;
  playback_speed: string;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  message: string;
  details: string | null;
}
