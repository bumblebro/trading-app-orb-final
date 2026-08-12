'use client';

import { useCallback, useMemo, useState } from 'react';
import { api, type LogEntry } from '@/lib/api';
import { usePoll } from '@/lib/hooks';

const POLL_MS = 3000;
const LEVELS = ['ALL', 'ERROR', 'WARNING', 'INFO'] as const;
type LevelFilter = (typeof LEVELS)[number];

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [level, setLevel] = useState<LevelFilter>('ALL');
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await api.logs(200);
      setLogs(data.logs ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot load logs');
    } finally {
      setLoading(false);
    }
  }, []);

  usePoll(load, POLL_MS);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return logs.filter((row) => {
      if (level !== 'ALL' && row.level !== level) return false;
      if (!q) return true;
      return (
        row.message.toLowerCase().includes(q) ||
        (row.category || '').toLowerCase().includes(q)
      );
    });
  }, [logs, level, query]);

  return (
    <main className="page-shell py-4 sm:py-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="m-0 text-[1.05rem] font-semibold">Bot logs</h1>
          <p className="m-0 mt-0.5 text-[0.78rem] text-[var(--faint)]">
            Live feed from the bot — sizing skips, WebSocket, orders, errors.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="field min-w-0 flex-1 sm:w-52 sm:flex-none"
            placeholder="Filter message…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex shrink-0 gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1">
            {LEVELS.map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLevel(l)}
                className={`rounded-md px-2.5 py-1 text-[0.72rem] font-medium transition-colors ${
                  level === l
                    ? 'bg-[var(--surface-2)] text-[var(--text)]'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                }`}
              >
                {l === 'ALL' ? 'All' : l.charAt(0) + l.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="card mb-4 border-[color-mix(in_srgb,var(--red)_40%,transparent)] px-4 py-2.5 text-[0.8rem] text-[var(--red)]">
          {error}
        </div>
      )}

      <section className="card overflow-hidden">
        <div className="scroll-x scroll-y max-h-[calc(100vh-11rem)]">
          <table className="table min-w-[720px]">
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Category</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id}>
                  <td className="whitespace-nowrap text-[var(--faint)]">{row.timestamp}</td>
                  <td>
                    <span className={levelClass(row.level)}>{row.level}</span>
                  </td>
                  <td className="text-[var(--muted)]">{row.category || '—'}</td>
                  <td className="break-words">{row.message}</td>
                </tr>
              ))}
              {!filtered.length && (
                <tr>
                  <td colSpan={4} className="text-center text-[var(--faint)]">
                    {loading ? 'Loading…' : 'No matching logs.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function levelClass(level: string) {
  const base = 'metric text-[0.75rem]';
  if (level === 'ERROR') return `${base} down`;
  if (level === 'WARNING') return `${base} warn`;
  return `${base} text-[var(--muted)]`;
}
