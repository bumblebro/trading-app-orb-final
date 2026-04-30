'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Settings } from '@/lib/types';

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    api_key: '', client_id: '', pin: '', totp_secret: '',
    supertrend_period: '10', supertrend_multiplier: '3.0',
    ema_9_period: '9', ema_21_period: '21',
    adx_threshold: '20',
    max_trades_per_day: '2', max_daily_loss: '10000',
    signal_cutoff_time: '15:00', square_off_time: '15:15', lot_size: '65', 
    position_size_mode: 'fixed', fixed_lots: '2', max_capital_risk_pct: '1', 
    trading_mode: 'paper', paper_capital: '100000', 
    playback_file: 'bot/data/nifty_sample.csv', playback_speed: '1',
    playback_start_date: '', playback_period: 'all',
    initial_capital: '100000',
    position_sizing_mode: 'auto_compound',
    risk_percent_per_trade: '5.0',
    min_lots: '1',
    max_lots: '',
    max_sl_distance_pts: '50',
    trailing_sl_enabled: 'true',
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
          <div className="form-group sm:col-span-1">
            <label className="form-label">Playback Start Date</label>
            <input 
              type="date" 
              className="form-input" 
              value={settings.playback_start_date} 
              onChange={(e) => handleChange('playback_start_date', e.target.value)} 
            />
          </div>
          <div className="form-group sm:col-span-1">
            <label className="form-label">Playback End Date (Optional)</label>
            <input 
              type="date" 
              className="form-input" 
              value={settings.playback_end_date} 
              onChange={(e) => handleChange('playback_end_date', e.target.value)} 
            />
          </div>
          <p className="col-span-2 text-[10px] text-gray-400 -mt-2">Leave dates empty to process the entire file.</p>
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
          <div className="form-group sm:col-span-1">
            <label className="form-label text-indigo-400 font-bold">Initial Capital (₹)</label>
            <input 
              type="number" 
              className="form-input border-indigo-500/30" 
              value={settings.initial_capital} 
              onChange={(e) => handleChange('initial_capital', e.target.value)} 
            />
          </div>
        </div>
      </div>

      {/* 3. Strategy Parameters */}
      <div className="settings-section border-l-4 border-cyan-500">
        <h3 className="text-cyan-400">📊 Strategy Parameters (EMA + Supertrend)</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">Supertrend Period</label>
            <input type="number" className="form-input" value={settings.supertrend_period} onChange={(e) => handleChange('supertrend_period', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Supertrend Multiplier</label>
            <input type="number" step="0.1" className="form-input" value={settings.supertrend_multiplier} onChange={(e) => handleChange('supertrend_multiplier', e.target.value)} />
          </div>
          <div className="form-group border-l-2 border-blue-500/30 pl-4">
            <label className="form-label">Short EMA Period</label>
            <input type="number" className="form-input" value={settings.ema_9_period} onChange={(e) => handleChange('ema_9_period', e.target.value)} />
          </div>
          <div className="form-group border-l-2 border-blue-500/30 pl-4">
            <label className="form-label">Long EMA Period</label>
            <input type="number" className="form-input" value={settings.ema_21_period} onChange={(e) => handleChange('ema_21_period', e.target.value)} />
          </div>
          <div className="form-group col-span-2">
            <label className="form-label flex items-center gap-1">
              ADX Choppiness Filter (Threshold)
              <span className="text-[10px] bg-yellow-500/20 text-yellow-400 px-1 rounded border border-yellow-500/30 cursor-help" title="Only trades when ADX is above this value. Prevents entry in sideways/range-bound markets. (Default 20)">i</span>
            </label>
            <input type="number" className="form-input" value={settings.adx_threshold} onChange={(e) => handleChange('adx_threshold', e.target.value)} />
          </div>
        </div>
      </div>

      {/* 5. Trade Execution */}
      <div className="settings-section border-l-4 border-green-500">
        <h3 className="text-green-500">🛡️ Execution & Risk</h3>
        <div className="form-grid">
          <div className="form-group col-span-2">
            <label className="form-label">Position Sizing Mode</label>
            <select className="form-input" value={settings.position_sizing_mode} onChange={(e) => handleChange('position_sizing_mode', e.target.value)}>
              <option value="fixed_lots">📍 Fixed Lots</option>
              <option value="auto_compound">⚖️ Auto-Compounding ( compounding)</option>
            </select>
          </div>
          
          {settings.position_sizing_mode === 'fixed_lots' ? (
            <div className="form-group">
              <label className="form-label">Fixed Lots</label>
              <input type="number" className="form-input" value={settings.fixed_lots} onChange={(e) => handleChange('fixed_lots', e.target.value)} />
            </div>
          ) : (
            <>
              <div className="form-group">
                <label className="form-label text-cyan-400">Risk Per Trade (%)</label>
                <input type="number" step="0.1" className="form-input" value={settings.risk_percent_per_trade} onChange={(e) => handleChange('risk_percent_per_trade', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Min Lots</label>
                <input type="number" className="form-input" value={settings.min_lots} onChange={(e) => handleChange('min_lots', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Max Lots</label>
                <input type="number" className="form-input" value={settings.max_lots} onChange={(e) => handleChange('max_lots', e.target.value)} placeholder="Auto (₹10k/lot, min 10)" />
              </div>
            </>
          )}
          <div className="form-group">
            <label className="form-label flex items-center gap-1">
              Stop Loss Trailing
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1 rounded border border-blue-500/30 cursor-help" title="Static SL stays fixed. Trailing SL moves up with the Supertrend line on every 5-min candle close.">i</span>
            </label>
            <select className="form-input" value={settings.trailing_sl_enabled} onChange={(e) => handleChange('trailing_sl_enabled', e.target.value)}>
              <option value="false">🛡️ Static SL (Fixed Position)</option>
              <option value="true">📈 Trailing SL (Follow Supertrend)</option>
            </select>
          </div>

          <div className="form-group border-l-2 border-red-500/30 pl-4">
            <label className="form-label text-red-400 flex items-center gap-1">
              Max SL Distance Filter
              <span className="text-[10px] bg-red-500/20 text-red-400 px-1 rounded border border-red-500/30 cursor-help" title="Skips trades if the distance from entry price to Supertrend SL is wider than this value. (Default 50 pts)">i</span>
            </label>
            <input type="number" className="form-input border-red-500/20" value={settings.max_sl_distance_pts} onChange={(e) => handleChange('max_sl_distance_pts', e.target.value)} placeholder="Max SL distance in pts" />
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
          <div className="form-group bg-red-500/5 p-2 rounded border border-red-500/10">
            <label className="form-label text-red-400 font-bold">Daily Loss Kill Switch (₹)</label>
            <input type="number" className="form-input border-red-500/30" value={settings.max_daily_loss} onChange={(e) => handleChange('max_daily_loss', e.target.value)} />
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
