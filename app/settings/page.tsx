'use client';

import { useEffect, useState, useCallback } from 'react';
import TradeModeToggle from '@/components/TradeModeToggle';
import { api } from '@/lib/api';
import type { Settings } from '@/lib/types';

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    api_key: '', client_id: '', pin: '', totp_secret: '',
    orb_duration: '15', min_orb_range: '30', max_orb_range: '300',
    supertrend_period: '7', supertrend_multiplier: '3.0',
    rsi_period: '14', rsi_buy_level: '55', rsi_sell_level: '45',
    target_multiplier: '2.0', sl_multiplier: '1.0',
    max_trades_per_day: '3', square_off_time: '15:15', signal_cutoff_time: '14:30',
    lot_size: '65', trading_mode: 'paper', paper_capital: '100000',
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
              <option value="smartapi">Angel One SmartAPI</option>
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
        <h3>📊 Strategy Parameters (ORB + ST + RSI)</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">ORB Duration (mins)</label>
            <input
              type="number"
              className="form-input"
              value={settings.orb_duration}
              onChange={(e) => handleChange('orb_duration', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Min ORB Range (pts)</label>
            <input
              type="number"
              className="form-input"
              value={settings.min_orb_range}
              onChange={(e) => handleChange('min_orb_range', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Max ORB Range (pts)</label>
            <input
              type="number"
              className="form-input"
              value={settings.max_orb_range}
              onChange={(e) => handleChange('max_orb_range', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Supertrend Period</label>
            <input
              type="number"
              className="form-input"
              value={settings.supertrend_period}
              onChange={(e) => handleChange('supertrend_period', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Supertrend Multiplier</label>
            <input
              type="number"
              step="0.1"
              className="form-input"
              value={settings.supertrend_multiplier}
              onChange={(e) => handleChange('supertrend_multiplier', e.target.value)}
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
            <label className="form-label">RSI Buy Level (CE)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_buy_level}
              onChange={(e) => handleChange('rsi_buy_level', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">RSI Sell Level (PE)</label>
            <input
              type="number"
              className="form-input"
              value={settings.rsi_sell_level}
              onChange={(e) => handleChange('rsi_sell_level', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Trade Management */}
      <div className="settings-section">
        <h3>🛡️ Trade Management</h3>
        <div className="form-grid">
          <div className="form-group">
            <label className="form-label">Target Multiplier (x Range)</label>
            <input
              type="number"
              step="0.5"
              className="form-input"
              value={settings.target_multiplier}
              onChange={(e) => handleChange('target_multiplier', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">SL Multiplier (x Range)</label>
            <input
              type="number"
              step="0.5"
              className="form-input"
              value={settings.sl_multiplier}
              onChange={(e) => handleChange('sl_multiplier', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Option Target %</label>
            <input
              type="number"
              className="form-input"
              value={settings.option_target_pct}
              onChange={(e) => handleChange('option_target_pct', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Option SL %</label>
            <input
              type="number"
              className="form-input"
              value={settings.option_sl_pct}
              onChange={(e) => handleChange('option_sl_pct', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Trailing SL</label>
            <select 
              className="form-input" 
              value={settings.trailing_sl_enabled}
              onChange={(e) => handleChange('trailing_sl_enabled', e.target.value)}
            >
              <option value="false">OFF</option>
              <option value="true">ON</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Trailing SL %</label>
            <input
              type="number"
              className="form-input"
              value={settings.trailing_sl_pct}
              onChange={(e) => handleChange('trailing_sl_pct', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Risk Management */}
      <div className="settings-section">
        <h3>⚠️ Risk Management</h3>
        <div className="form-grid">
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
            <label className="form-label">Signal Cutoff Time</label>
            <input
              type="time"
              className="form-input"
              value={settings.signal_cutoff_time}
              onChange={(e) => handleChange('signal_cutoff_time', e.target.value)}
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
          <div className="form-group">
            <label className="form-label">Max Capital Risk %</label>
            <input
              type="number"
              step="0.1"
              className="form-input"
              value={settings.max_capital_risk_pct}
              onChange={(e) => handleChange('max_capital_risk_pct', e.target.value)}
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
