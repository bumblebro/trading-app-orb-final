'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { LogEntry } from '@/lib/types';
import { api } from '@/lib/api';

export default function MarginLogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const data = await api.getMarginLogs(50);
      setLogs(data.logs || []);
    } catch {
      // Bot not connected
    }
  }, []);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  const copyLogs = () => {
    const logText = logs
      .map(log => {
        const details = log.details ? JSON.parse(log.details) : {};
        return `[${log.timestamp}] Available: ₹${details.available?.toFixed(2) || '0'}, Required: ₹${details.required?.toFixed(2) || '0'}`;
      })
      .join('\n');
    
    navigator.clipboard.writeText(logText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className={`margin-log-viewer ${collapsed ? 'collapsed' : ''} mt-4`}>
      <div className="log-header" style={{ borderLeft: '4px solid #ef4444' }} onClick={() => setCollapsed(!collapsed)}>
        <div className="flex items-center gap-2">
          <span className="text-lg">🚫</span>
          <h3>Margin Failure History</h3>
        </div>
        <div className="log-controls">
          {!collapsed && logs.length > 0 && (
            <button 
              className={`copy-logs-btn ${copied ? 'success' : ''}`}
              onClick={(e) => { e.stopPropagation(); copyLogs(); }}
            >
              {copied ? '✅ Copied!' : '📋 Copy All'}
            </button>
          )}
          <span className="collapse-icon">{collapsed ? '▼' : '▲'}</span>
        </div>
      </div>
      
      {!collapsed && (
        <div className="log-body max-h-[300px] overflow-y-auto" ref={scrollRef}>
          {logs.length === 0 ? (
            <div className="log-empty text-gray-500 py-8 italic">No margin issues recorded. Your capital is within limits.</div>
          ) : (
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="py-2 px-3">Time</th>
                  <th className="py-2 px-3">Available</th>
                  <th className="py-2 px-3">Required</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => {
                  const details = log.details ? JSON.parse(log.details) : {};
                  return (
                    <tr key={log.id} className="border-b border-gray-800/30 hover:bg-red-500/5">
                      <td className="py-2 px-3 text-gray-500 whitespace-nowrap">
                        {log.timestamp.split(' ')[1]}
                      </td>
                      <td className="py-2 px-3 font-mono text-red-400">
                        ₹{details.available?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-2 px-3 font-mono text-orange-400 font-bold">
                        ₹{details.required?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      <style jsx>{`
        .margin-log-viewer {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
        }
        .log-header {
          padding: 1rem;
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
          background: rgba(239, 68, 68, 0.05);
        }
        .log-header h3 {
          font-size: 0.9rem;
          font-weight: 700;
          color: #ef4444;
        }
        .log-body {
          padding: 0;
          background: #0a0a0a;
        }
        .copy-logs-btn {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: #9ca3af;
          padding: 0.25rem 0.75rem;
          border-radius: 6px;
          font-size: 0.7rem;
          font-weight: 600;
          transition: all 0.2s;
        }
        .copy-logs-btn:hover {
          background: rgba(255, 255, 255, 0.1);
          color: white;
        }
        .copy-logs-btn.success {
          border-color: #10b981;
          color: #10b981;
          background: rgba(16, 185, 129, 0.1);
        }
        .log-empty {
          text-align: center;
          font-size: 0.8rem;
        }
      `}</style>
    </div>
  );
}
