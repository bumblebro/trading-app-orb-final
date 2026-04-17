export interface PriceInfo {
  price: number;
  prev_price: number;
  change: number;
  change_pct: number;
  last_update: string | null;
  connected: boolean;
  simulation: boolean;
  indicators: {
    ema_fast: number | null;
    ema_slow: number | null;
    vwap: number | null;
    rsi: number | null;
    crossover: string | null;
    ready: boolean;
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
  consecutive_losses: number;
  mode: string;
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
  ema_fast: LineData[];
  ema_slow: LineData[];
  vwap: LineData[];
}

export interface Settings {
  api_key: string;
  client_id: string;
  pin: string;
  totp_secret: string;
  ema_fast: string;
  ema_slow: string;
  stop_loss_pct: string;
  target_pct: string;
  max_trades_per_day: string;
  square_off_time: string;
  lot_size: string;
  trading_mode: string;
  paper_capital: string;
  rsi_period: string;
  rsi_overbought: string;
  rsi_oversold: string;
  rsi_bull_threshold: string;
  rsi_bear_threshold: string;
  pullback_threshold: string;
  crossover_window: string;
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
