'use client';

import { useState } from 'react';

interface TradeModeToggleProps {
  mode: string;
  onToggle: (newMode: string) => void;
}

export default function TradeModeToggle({ mode, onToggle }: TradeModeToggleProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const handleToggle = () => {
    if (mode === 'paper') {
      // Switching to live — need confirmation
      setShowConfirm(true);
    } else {
      // Switching to paper — no confirmation needed
      onToggle('paper');
    }
  };

  const confirmLive = () => {
    if (confirmText === 'CONFIRM') {
      onToggle('live');
      setShowConfirm(false);
      setConfirmText('');
    }
  };

  return (
    <>
      {/* Mode Banner */}
      <div className={`mode-banner ${mode}`}>
        {mode === 'paper' ? (
          <>📝 PAPER TRADING MODE — No real orders placed</>
        ) : (
          <>🔴 LIVE TRADING — Real money at risk</>
        )}
      </div>

      {/* Toggle on Settings page */}
      <div className="mode-toggle-container">
        <span className={`mode-label ${mode === 'paper' ? 'active' : ''}`}>Paper</span>
        <button
          className={`mode-toggle ${mode}`}
          onClick={handleToggle}
          aria-label="Toggle trading mode"
        >
          <span className="toggle-thumb" />
        </button>
        <span className={`mode-label ${mode === 'live' ? 'active' : ''}`}>Live</span>
      </div>

      {/* Confirmation Modal */}
      {showConfirm && (
        <div className="modal-overlay" onClick={() => setShowConfirm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>⚠️ Switch to Live Trading?</h3>
            <p>This will place <strong>real orders</strong> with <strong>real money</strong> through Angel One.</p>
            <p>Type <strong>CONFIRM</strong> to proceed:</p>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type CONFIRM"
              className="confirm-input"
              autoFocus
            />
            <div className="modal-actions">
              <button className="btn-cancel" onClick={() => { setShowConfirm(false); setConfirmText(''); }}>Cancel</button>
              <button
                className="btn-danger"
                onClick={confirmLive}
                disabled={confirmText !== 'CONFIRM'}
              >
                Enable Live Trading
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
