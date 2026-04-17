'use client';

import { useEffect, useState, useCallback } from 'react';
import TradeModeToggle from '@/components/TradeModeToggle';
import { api } from '@/lib/api';
import type { Settings } from '@/lib/types';

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    api_key: '', client_id: '', pin: '', totp_secret: '',
    ema_fast: '9', ema_slow: '21', stop_loss_pct: '0.5', target_pct: '1.0',
    max_trades_per_day: '3', square_off_time: '15:15', lot_size: '65',
    trading_mode: 'paper', paper_capital: '100000',
    rsi_period: '14', rsi_overbought: '55', rsi_oversold: '45',
    rsi_bull_threshold: '55', rsi_bear_threshold: '45', pullback_threshold: '0.001', crossover_window: '10',
    data_source: 'auto', playback_file: 'bot/data/nifty_sample.csv', playback_speed: '1',
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

  const handleModeToggle = (newMode: string) => {
    handleChange('trading_mode', newMode);
  };

  if (loading) {
    return (
      <div className="page-container">
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <h1 className="page-title">⚙️ Settings</h1>

      {/* Trading Mode */}
      <div className="settings-section">
        <h3>🔄 Trading Mode</h3>
        <TradeModeToggle mode={settings.trading_mode} onToggle={handleModeToggle} />
        {settings.trading_mode === 'paper' && (
          <div className="form-grid" style={{ marginTop: '1rem' }}>
            <div className="form-group">
              <label className="form-label">Paper Trading Capital (₹)</label>
              <input
                type="text"
                className="form-input"
                value={settings.paper_capital}
                onChange={(e) => handleChange('paper_capital', e.target.value)}
              />
            </div>
          </div>
        )}
      </div>
      
      {/* Data Source */}
      <div className="settings-section">
        <h3>📡 Data Source</h3>
        <p className="section-desc" style={{ marginBottom: '1rem', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Choose where the bot gets its price data. Use <strong>Playback</strong> for historical testing.
        </p>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">Source Type</label>
            <select 
              className="form-input" 
              value={settings.data_source}
              onChange={(e) => handleChange('data_source', e.target.value)}
            >
              <option value="auto">Auto (SmartAPI or Simulated)</option>
              <option value="simulated">Forced Simulated (Random Walk)</option>
              <option value="playback">CSV Playback (Historical Data)</option>
            </select>
          </div>
          {settings.data_source === 'playback' && (
            <div className="form-group">
              <label className="form-label">CSV File Path</label>
              <input
                type="text"
                className="form-input"
                value={settings.playback_file}
                onChange={(e) => handleChange('playback_file', e.target.value)}
                placeholder="e.g., bot/data/nifty_sample.csv"
              />
            </div>
          )}
          {settings.data_source === 'playback' && (
            <div className="form-group">
              <label className="form-label">Playback Speed</label>
              <select 
                className="form-input" 
                value={settings.playback_speed}
                onChange={(e) => handleChange('playback_speed', e.target.value)}
              >
                <option value="1">1x (Real-time)</option>
                <option value="2">2x Speed</option>
                <option value="5">5x Speed</option>
                <option value="10">10x Speed</option>
                <option value="20">20x Speed</option>
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Angel One Credentials */}
      <div className="settings-section">
        <h3>🔐 Angel One API Credentials</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">API Key</label>
            <input
              type="password"
              className="form-input"
              value={settings.api_key}
              onChange={(e) => handleChange('api_key', e.target.value)}
              placeholder="Enter API Key"
            />
          </div>
          <div className="form-group">
            <label className="form-label">Client ID</label>
            <input
              type="text"
              className="form-input"
              value={settings.client_id}
              onChange={(e) => handleChange('client_id', e.target.value)}
              placeholder="e.g., S12345678"
            />
          </div>
          <div className="form-group">
            <label className="form-label">Trading PIN (MPIN)</label>
            <input
              type="password"
              className="form-input"
              value={settings.pin}
              onChange={(e) => handleChange('pin', e.target.value)}
              placeholder="Enter 4 or 6 digit PIN"
            />
          </div>
          <div className="form-group">
            <label className="form-label">TOTP Secret</label>
            <input
              type="password"
              className="form-input"
              value={settings.totp_secret}
              onChange={(e) => handleChange('totp_secret', e.target.value)}
              placeholder="Enter TOTP Secret"
            />
          </div>
        </div>
      </div>

      {/* Strategy Parameters */}
      <div className="settings-section">
        <h3>📐 Strategy Parameters</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">EMA Fast Period</label>
            <input
              type="number"
              className="form-input"
              value={settings.ema_fast}
              onChange={(e) => handleChange('ema_fast', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">EMA Slow Period</label>
            <input
              type="number"
              className="form-input"
              value={settings.ema_slow}
              onChange={(e) => handleChange('ema_slow', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Period</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_period}
              onChange={(e) => handleChange('rsi_period', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Overbought (CE Signal)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_overbought}
              onChange={(e) => handleChange('rsi_overbought', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Oversold (PE Signal)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_oversold}
              onChange={(e) => handleChange('rsi_oversold', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Bull Threshold (Rising)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_bull_threshold}
              onChange={(e) => handleChange('rsi_bull_threshold', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Bear Threshold (Falling)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_bear_threshold}
              onChange={(e) => handleChange('rsi_bear_threshold', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Pullback Threshold (Decimal %)</label>
            <input
              type="number"
              step="0.0001"
              className="form-input"
              value={settings.pullback_threshold}
              onChange={(e) => handleChange('pullback_threshold', e.target.value)}
              placeholder="e.g., 0.001 for 0.1%"
            />
          </div>
          <div className="form-group">
            <label className="form-label">Crossover Window (Candles)</label>
            <input
              type="number"
              className="form-input"
              value={settings.crossover_window}
              onChange={(e) => handleChange('crossover_window', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Stop Loss %</label>
            <input
              type="number"
              step="0.1"
              className="form-input"
              value={settings.stop_loss_pct}
              onChange={(e) => handleChange('stop_loss_pct', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Target %</label>
            <input
              type="number"
              step="0.1"
              className="form-input"
              value={settings.target_pct}
              onChange={(e) => handleChange('target_pct', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Max Trades Per Day</label>
            <input
              type="number"
              className="form-input"
              value={settings.max_trades_per_day}
              onChange={(e) => handleChange('max_trades_per_day', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Auto Square Off Time</label>
            <input
              type="time"
              className="form-input"
              value={settings.square_off_time}
              onChange={(e) => handleChange('square_off_time', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Lot Size</label>
            <input
              type="number"
              className="form-input"
              value={settings.lot_size}
              onChange={(e) => handleChange('lot_size', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Save Button */}
      <button className="save-btn" onClick={handleSave} disabled={saving}>
        {saving ? '⏳ Saving...' : '💾 Save Settings'}
      </button>

      {/* Toast */}
      {toast && (
        <div className={`toast ${toast.type}`}>{toast.message}</div>
      )}
    </div>
  );
}
