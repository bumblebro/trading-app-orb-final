'use client';

import { useEffect } from 'react';

/**
 * Run an async task on mount, then repeatedly, each run scheduled only after
 * the previous one settles. Unlike setInterval this cannot stack up requests
 * when the bot server is slow to answer.
 */
export function usePoll(task: () => Promise<unknown>, intervalMs: number) {
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const run = async () => {
      try {
        await task();
      } finally {
        if (!stopped) timer = setTimeout(run, intervalMs);
      }
    };

    timer = setTimeout(run, 0);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [task, intervalMs]);
}

/** Run an async task once whenever it changes identity. */
export function useLoad(task: () => Promise<unknown>) {
  useEffect(() => {
    let stopped = false;
    const timer = setTimeout(() => {
      if (!stopped) void task();
    }, 0);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [task]);
}
