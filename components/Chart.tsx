'use client';

import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import type { CandlePayload, StrategyState } from '@/lib/types';

interface ChartProps {
  data: CandlePayload | null;
  strategy?: StrategyState | null;
}

interface LineSpec {
  price: number;
  color: string;
  title: string;
  dashed?: boolean;
}

function chartHeight(width: number) {
  if (width < 480) return 260;
  if (width < 768) return 320;
  return 420;
}

const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export default function Chart({ data, strategy }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const barCountRef = useRef(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b90a0',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(35, 38, 47, 0.6)' },
        horzLines: { color: 'rgba(35, 38, 47, 0.6)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: '#23262f' },
      timeScale: {
        borderColor: '#23262f',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: number) => IST_TIME.format(new Date(time * 1000)),
      },
      localization: {
        timeFormatter: (time: number) => IST_TIME.format(new Date(time * 1000)),
        priceFormatter: (price: number) => price.toFixed(1),
      },
      width: container.clientWidth,
      height: chartHeight(container.clientWidth),
    });

    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#f2555a',
      borderUpColor: '#22c55e',
      borderDownColor: '#f2555a',
      wickUpColor: '#22c55e',
      wickDownColor: '#f2555a',
    });
    chartRef.current = chart;

    const observer = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: chartHeight(container.clientWidth),
      });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      priceLinesRef.current = [];
      barCountRef.current = 0;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !data) return;

    series.setData((data.candles ?? []) as CandlestickData<Time>[]);

    // Only auto-fit on the first load of a session; afterwards the user's zoom wins.
    const count = data.candles?.length ?? 0;
    if (count && count < barCountRef.current) chartRef.current?.timeScale().fitContent();
    if (!barCountRef.current && count) chartRef.current?.timeScale().fitContent();
    barCountRef.current = count;

    for (const line of priceLinesRef.current) series.removePriceLine(line);

    const specs: LineSpec[] = [];
    if (data.orb) {
      specs.push({ price: data.orb.high, color: '#4c8dff', title: 'OR High' });
      specs.push({ price: data.orb.low, color: '#4c8dff', title: 'OR Low' });
    }
    const position = strategy?.position;
    if (position) {
      specs.push({ price: position.entry_index, color: '#e8eaed', title: 'Entry', dashed: true });
      specs.push({ price: position.stop_index, color: '#f2555a', title: 'Stop', dashed: true });
      specs.push({ price: position.target_index, color: '#22c55e', title: 'Target', dashed: true });
    }

    priceLinesRef.current = specs.map((spec) =>
      series.createPriceLine({
        price: spec.price,
        color: spec.color,
        lineWidth: 1,
        lineStyle: spec.dashed ? 2 : 0,
        axisLabelVisible: true,
        title: spec.title,
      }),
    );
  }, [data, strategy]);

  const orb = data?.orb;

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div>
          <h2 className="m-0 text-[0.9rem] font-semibold">NIFTY 50 · 1 min</h2>
          <p className="m-0 mt-0.5 text-[0.72rem] text-[var(--faint)]">
            Opening range · first {data?.or_minutes ?? 15} minutes
          </p>
        </div>
        {orb ? (
          <div className="flex gap-4 text-[0.75rem]">
            <span className="text-[var(--muted)]">
              High <span className="metric text-[var(--text)]">{orb.high.toFixed(1)}</span>
            </span>
            <span className="text-[var(--muted)]">
              Low <span className="metric text-[var(--text)]">{orb.low.toFixed(1)}</span>
            </span>
            <span className="text-[var(--muted)]">
              Range <span className="metric text-[var(--text)]">{orb.range.toFixed(1)}</span>
            </span>
          </div>
        ) : (
          <span className="label">Range not set</span>
        )}
      </div>
      <div ref={containerRef} className="px-1 py-2" />
    </div>
  );
}
