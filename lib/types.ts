export interface PriceInfo {
  price: number;
  prev_price: number;
  change: number;
  change_pct: number;
  last_update: string | null;
  connected: boolean;
  simulation: boolean;
  indicators: {
    ema_short: number | null;
    ema_long: number | null;
    supertrend: number | null;
    supertrend_direction: number | null;
    adx: number | null;
    phase: string;
    ready: boolean;
  };
}

export interface Signal {
  signal: string;
  phase: string;
  phase_description: string;
  ema_short: number | null;
  ema_long: number | null;
  supertrend: number | null;
  supertrend_direction: number | null;
  adx: number | null;
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
  supertrend_at_entry?: number;
  adx_at_entry?: number;
  ema_short_at_entry?: number;
  ema_long_at_entry?: number;
  exit_time?: string;
  trailing_sl_used?: number;
  current_price?: number;
  live_pnl?: number;
  capital_used?: number;
  total_capital?: number;
  net_pnl?: number;
  brokerage?: number;
  stt?: number;
  exc_charges?: number;
  gst?: number;
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
  total_wins: number;
  total_losses: number;
  mode: 'paper' | 'live';
  phase: string;
  market_status: string;
  market_open: boolean;
  is_trading_day: boolean;
  all_time_win_rate: number;
  backtest_capital?: number;
  capital_history?: number[];
  compounding_advantage?: number;
  backtest_start?: string;
  backtest_current?: string;
  backtest_duration?: string;
  initial_capital?: number;
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
  ema9: LineData[];
  ema21: LineData[];
  supertrend: (LineData & { color: string })[];
}

export interface Settings {
  api_key: string;
  client_id: string;
  pin: string;
  totp_secret: string;
  supertrend_period: string;
  supertrend_multiplier: string;
  ema_9_period: string;
  ema_21_period: string;
  adx_threshold: string;
  max_sl_distance_pts: string;
  max_trades_per_day: string;
  max_daily_loss: string;
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
  playback_start_date: string;
  playback_end_date: string;
  playback_period: string;
  initial_capital: string;
  position_sizing_mode: string;
  risk_percent_per_trade: string;
  min_lots: string;
  max_lots: string;
  morning_max_trades: string;
  afternoon_max_trades: string;
  trailing_sl_enabled: string;
  option_sl_pct: string;
  max_capital_per_trade_pct: string;
  max_trade_duration_mins: string;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  message: string;
  details: string | null;
}
