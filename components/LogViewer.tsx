'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { LogEntry } from '@/lib/types';
import { api } from '@/lib/api';

export default function LogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const data = await api.getLogs(100, filter || undefined);
      setLogs(data.logs || []);
    } catch {
      // Bot not connected
    }
  }, [filter]);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 3000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [logs]);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'ERROR': case 'CRITICAL': return '#ef4444';
      case 'WARNING': return '#eab308';
      case 'INFO': return '#9ca3af';
      case 'DEBUG': return '#6366f1';
      default: return '#6b7280';
    }
  };

  const getCategoryBadge = (category: string) => {
    const colors: Record<string, string> = {
      SIGNAL: '#8b5cf6',
      ORDER: '#06b6d4',
      SYSTEM: '#6b7280',
      ERROR: '#ef4444',
    };
    return colors[category] || '#6b7280';
  };

  return (
    <div className={`log-viewer ${collapsed ? 'collapsed' : ''}`}>
      <div className="log-header" onClick={() => setCollapsed(!collapsed)}>
        <h3>📋 Bot Logs</h3>
        <div className="log-controls">
          {!collapsed && (
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="log-filter"
              onClick={(e) => e.stopPropagation()}
            >
              <option value="">All</option>
              <option value="SIGNAL">Signals</option>
              <option value="ORDER">Orders</option>
              <option value="SYSTEM">System</option>
              <option value="ERROR">Errors</option>
            </select>
          )}
          <span className="collapse-icon">{collapsed ? '▼' : '▲'}</span>
        </div>
      </div>
      {!collapsed && (
        <div className="log-body" ref={scrollRef}>
          {logs.length === 0 ? (
            <div className="log-empty">No logs yet. Start the bot to see activity.</div>
          ) : (
            logs.map((log) => (
              <div key={log.id} className="log-entry">
                <span className="log-time">{log.timestamp.split(' ').slice(1).join(' ').replace(' IST', '')}</span>
                <span className="log-badge" style={{ backgroundColor: getCategoryBadge(log.category) }}>
                  {log.category}
                </span>
                <span className="log-message" style={{ color: getLevelColor(log.level) }}>
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
