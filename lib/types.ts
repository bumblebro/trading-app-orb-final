export interface PriceInfo {
  price: number;
  prev_price: number;
  change: number;
  change_pct: number;
  last_update: string | null;
  connected: boolean;
  simulation: boolean;
  indicators: {
  indicators: {
    orb_high: number | null;
    orb_low: number | null;
    orb_range: number | null;
    orb_status: string | null;
    supertrend_value: number | null;
    supertrend_direction: 'UP' | 'DOWN' | 'NEUTRAL';
    rsi: number | null;
    phase: string;
    ready: boolean;
  };
  };
}

export interface Signal {
  signal: string;
  indicators: Record<string, unknown>;
  timestamp: string;
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
  indicators: Record<string, unknown>;
  price: PriceInfo;
  active_trade: Trade | null;
  today_pnl: number;
  today_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_trades: number;
  consecutive_losses: number;
  mode: 'paper' | 'live';
  market_status: string;
  market_open: boolean;
  is_trading_day: boolean;
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
  supertrend: (LineData & { color?: string })[];
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
  supertrend_period: string;
  supertrend_multiplier: string;
  rsi_period: string;
  rsi_buy_level: string;
  rsi_sell_level: string;
  target_multiplier: string;
  sl_multiplier: string;
  option_target_pct: string;
  option_sl_pct: string;
  trailing_sl_enabled: string;
  trailing_sl_pct: string;
  max_trades_per_day: string;
  square_off_time: string;
  signal_cutoff_time: string;
  lot_size: string;
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
