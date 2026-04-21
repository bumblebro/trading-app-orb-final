'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Settings } from '@/lib/types';

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    api_key: '', client_id: '', pin: '', totp_secret: '',
    orb_duration: '15', min_orb_range: '20', max_orb_range: '150', breakout_buffer: '5',
    vwap_confirmation: 'true', sideways_threshold_pct: '0.2', atr_period: '14', atr_threshold: '10',
    primary_fib_level: '61.8', secondary_fib_level: '50.0', fib_sl_level: '78.6', pullback_timeout: '45',
    macd_fast_period: '12', macd_slow_period: '26', macd_signal_period: '9',
    rsi_filter_enabled: 'false', rsi_period: '14', rsi_min_ce: '45', rsi_max_pe: '55',
    option_target_pct: '80', option_sl_pct: '40',
    trailing_sl_enabled: 'true', trailing_sl_pct: '15',
    max_trades_per_day: '3', signal_cutoff_time: '14:30', square_off_time: '15:15',
    lot_size: '65', max_capital_risk_pct: '1',
    data_source: 'smartapi', playback_file: 'bot/data/nifty_sample.csv', playback_speed: '1',
    playback_start_date: '', playback_period: 'all',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const fetchSettings = useCallback(async () => {
    try {
      const data = await api.getSettings();
      if (data.settings) {
        setSettings(prev => ({ ...prev, ...data.settings }));
      }
    } catch {
      // Bot not connected
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.saveSettings(settings);
      showToast('Settings saved successfully!', 'success');
    } catch {
      showToast('Failed to save settings', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (key: keyof Settings, value: string) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  if (loading) {
    return (
      <div className="page-container flex items-center justify-center p-32">
        <div className="animate-pulse text-gray-500">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <h1 className="page-title">⚙️ Strategy Settings</h1>
      
      {/* 1. Market Access & Credentials */}
      <div className="settings-section">
        <h3>🔐 Angel One API Integration</h3>
        <div className="form-grid">
           <div className="form-group">
            <label className="form-label">Trading Mode</label>
            <select 
              className="form-input" 
              value={settings.trading_mode}
              onChange={(e) => handleChange('trading_mode', e.target.value)}
            >
              <option value="paper">📝 Paper Trading</option>
              <option value="live">💰 Live Trading (Real Money)</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Data Source</label>
            <select 
              className="form-input" 
              value={settings.data_source}
              onChange={(e) => handleChange('data_source', e.target.value)}
            >
              <option value="smartapi">Angel One Live Feed</option>
              <option value="playback">CSV Engine (Backtest)</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Backtest Speed</label>
            <select 
              className="form-input" 
              value={settings.playback_speed}
              disabled={settings.data_source !== 'playback'}
              onChange={(e) => handleChange('playback_speed', e.target.value)}
            >
              <option value="1">1x (Real-time)</option>
              <option value="10">10x Speed</option>
              <option value="50">50x Speed</option>
              <option value="100">100x Speed</option>
              <option value="500">🚀 Ultra Max (No Delay)</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">API Key</label>
            <input type="password" title={settings.api_key} className="form-input" value={settings.api_key} onChange={(e) => handleChange('api_key', e.target.value)} placeholder="Enter API Key" />
          </div>
          <div className="form-group">
            <label className="form-label">Client ID</label>
            <input type="text" className="form-input" value={settings.client_id} onChange={(e) => handleChange('client_id', e.target.value)} placeholder="S12345678" />
          </div>
          <div className="form-group">
            <label className="form-label">MPIN</label>
            <input type="password" title={settings.pin} className="form-input" value={settings.pin} onChange={(e) => handleChange('pin', e.target.value)} placeholder="4-digit PIN" />
          </div>
          <div className="form-group">
            <label className="form-label">TOTP Secret</label>
            <input type="password" title={settings.totp_secret} className="form-input" value={settings.totp_secret} onChange={(e) => handleChange('totp_secret', e.target.value)} placeholder="Enter TOTP Secret" />
          </div>
        </div>
      </div>
      
      {/* 2. Backtest Config (only visible in playback) */}
      <div className="settings-section border-l-4 border-indigo-500">
        <h3 className="text-indigo-500">🧪 Backtest Configuration</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">Playback Start Date</label>
            <input 
              type="date" 
              className="form-input" 
              value={settings.playback_start_date} 
              onChange={(e) => handleChange('playback_start_date', e.target.value)} 
            />
            <p className="text-[10px] text-gray-400 mt-1">Leave empty to start from first row</p>
          </div>
          <div className="form-group">
            <label className="form-label">Backtest Duration</label>
            <select 
              className="form-input" 
              value={settings.playback_period} 
              onChange={(e) => handleChange('playback_period', e.target.value)}
            >
              <option value="all">📊 Full Dataset</option>
              <option value="1 month">📅 1 Month</option>
              <option value="3 months">📅 3 Months</option>
              <option value="6 months">📅 6 Months</option>
              <option value="1 year">📅 1 Year</option>
            </select>
          </div>
        </div>
      </div>

      {/* 3. ORB Parameters */}
      <div className="settings-section border-l-4 border-cyan-500">
        <h3 className="text-cyan-400">📊 1. Opening Range (ORB)</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">ORB Duration (Minutes)</label>
            <select className="form-input" value={settings.orb_duration} onChange={(e) => handleChange('orb_duration', e.target.value)}>
              <option value="5">5 Mins</option>
              <option value="15">15 Mins (Recommended)</option>
              <option value="30">30 Mins</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Breakout Buffer (Pts)</label>
            <input type="number" className="form-input" value={settings.breakout_buffer} onChange={(e) => handleChange('breakout_buffer', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Min Range Filter (Pts)</label>
            <input type="number" className="form-input" value={settings.min_orb_range} onChange={(e) => handleChange('min_orb_range', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Max Range Filter (Pts)</label>
            <input type="number" className="form-input" value={settings.max_orb_range} onChange={(e) => handleChange('max_orb_range', e.target.value)} />
          </div>
          <div className="form-group col-span-2">
            <label className="form-label flex items-center gap-1">
              VWAP Confirmation
              <span className="text-[10px] bg-yellow-500/20 text-yellow-400 px-1 rounded border border-yellow-500/30 cursor-help" title="When enabled, breakout UP requires price above VWAP (bullish bias), and breakout DOWN requires price below VWAP (bearish bias). This filters out false breakouts against the intraday trend.">i</span>
            </label>
            <select className="form-input" value={settings.vwap_confirmation} onChange={(e) => handleChange('vwap_confirmation', e.target.value)}>
              <option value="true">✅ Enabled (Recommended)</option>
              <option value="false">❌ Disabled</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label flex items-center gap-1">
              Sideways Filter (%)
              <span className="text-[10px] bg-purple-500/20 text-purple-400 px-1 rounded border border-purple-500/30 cursor-help" title="If price stays within this % of VWAP for the first 45 mins, it marks the day as 'Sideways' and skips trading (No Trade Zone).">i</span>
            </label>
            <input type="number" step="0.01" className="form-input" value={settings.sideways_threshold_pct} onChange={(e) => handleChange('sideways_threshold_pct', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label flex items-center gap-1">
              ATR Volatility Limit
              <span className="text-[10px] bg-red-500/20 text-red-400 px-1 rounded border border-red-500/30 cursor-help" title="Average True Range (14 periods). If ATR is below this value, the day is considered too low-volatility for ORB and will be skipped.">i</span>
            </label>
            <input type="number" className="form-input" value={settings.atr_threshold} onChange={(e) => handleChange('atr_threshold', e.target.value)} />
          </div>
        </div>
      </div>

      {/* 5. Trade Execution */}
      <div className="settings-section border-l-4 border-green-500">
        <h3 className="text-green-500">🛡️ Execution & Risk</h3>
        <div className="form-grid">
          <div className="form-group col-span-2">
            <label className="form-label">Position Sizing Mode</label>
            <select className="form-input" value={settings.position_size_mode} onChange={(e) => handleChange('position_size_mode', e.target.value)}>
              <option value="fixed">📍 Fixed Lots</option>
              <option value="risk">⚖️ Auto (Capital Risk %)</option>
            </select>
          </div>
          
          {settings.position_size_mode === 'fixed' ? (
            <div className="form-group">
              <label className="form-label">Fixed Lots</label>
              <input type="number" className="form-input" value={settings.fixed_lots} onChange={(e) => handleChange('fixed_lots', e.target.value)} />
            </div>
          ) : (
            <>
              <div className="form-group">
                <label className="form-label">Capital Management (₹)</label>
                <input type="number" className="form-input" value={settings.paper_capital} onChange={(e) => handleChange('paper_capital', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Risk Per Trade (%)</label>
                <input type="number" step="0.1" className="form-input" value={settings.max_capital_risk_pct} onChange={(e) => handleChange('max_capital_risk_pct', e.target.value)} />
              </div>
            </>
          )}
          <div className="form-group">
            <label className="form-label flex items-center gap-1">
              ATM Delta
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1 rounded border border-blue-500/30 cursor-help" title="How much option premium moves per 1 point Nifty move. ATM is typically 0.5.">i</span>
            </label>
            <input type="number" step="0.01" className="form-input" value={settings.atm_delta} onChange={(e) => handleChange('atm_delta', e.target.value)} />
          </div>
          <p className="col-span-2 text-xs text-gray-400 italic mt-2">
            ℹ️ Target & SL are automatically calculated: <br/>
            Target = Entry + (Range × Delta × 1.5) | SL = Entry - (Range × Delta × 0.8)
          </p>
          <div className="form-group">
            <label className="form-label flex items-center gap-1">
              Trailing SL
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1 rounded border border-blue-500/30 cursor-help" title="Static SL stays fixed. Trailing SL moves up with the price to protect profits.">i</span>
            </label>
            <select className="form-input" value={settings.trailing_sl_enabled} onChange={(e) => handleChange('trailing_sl_enabled', e.target.value)}>
              <option value="false">🛡️ Static SL (Fixed Position)</option>
              <option value="true">📈 Trailing SL (Locks in Profits)</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Trailing Step (%)</label>
            <input type="number" className="form-input" value={settings.trailing_sl_pct} onChange={(e) => handleChange('trailing_sl_pct', e.target.value)} />
          </div>
        </div>
      </div>

      {/* 6. Market Controls */}
      <div className="settings-section">
        <h3>🚨 Safety Controls</h3>
        <div className="form-grid">
           <div className="form-group">
            <label className="form-label">Max Trades / Day</label>
            <input type="number" className="form-input" value={settings.max_trades_per_day} onChange={(e) => handleChange('max_trades_per_day', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Signal Cutoff</label>
            <input type="time" className="form-input" value={settings.signal_cutoff_time} onChange={(e) => handleChange('signal_cutoff_time', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Auto Square Off</label>
            <input type="time" className="form-input" value={settings.square_off_time} onChange={(e) => handleChange('square_off_time', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Lot Size (NIFTY)</label>
            <input type="number" className="form-input" value={settings.lot_size} onChange={(e) => handleChange('lot_size', e.target.value)} />
          </div>
        </div>
      </div>

      <button className="save-btn" onClick={handleSave} disabled={saving}>
        {saving ? '⏳ Saving Configuration...' : '💾 Apply All Settings'}
      </button>

      {toast && (
        <div className={`toast ${toast.type}`}>{toast.message}</div>
      )}
    </div>
  );
}
