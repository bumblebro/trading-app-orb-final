'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { 
  createChart, 
  ColorType, 
  IChartApi, 
  ISeriesApi, 
  CandlestickData, 
  LineData, 
  Time,
  CandlestickSeries,
  LineSeries
} from 'lightweight-charts';
import type { ChartData } from '@/lib/types';

interface ChartProps {
  data: ChartData | null;
}

export default function Chart({ data }: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const ema9Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const ema21Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const supertrendRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [initialized, setInitialized] = useState(false);

  const initChart = useCallback(() => {
    if (!chartContainerRef.current || initialized) return;

    const chart = createChart(chartContainerRef.current, {
     layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#9ca3af',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: '#1a1a2e' },
        horzLines: { color: '#1a1a2e' },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: '#6366f1',
          labelBackgroundColor: '#6366f1',
        },
        horzLine: {
          color: '#6366f1',
          labelBackgroundColor: '#6366f1',
        },
      },
      rightPriceScale: {
        borderColor: '#1a1a2e',
      },
      timeScale: {
        borderColor: '#1a1a2e',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: number, tickMarkType: number, locale: string) => {
          const date = new Date(time * 1000);
          const options: Intl.DateTimeFormatOptions = {
            timeZone: 'Asia/Kolkata',
            hour12: false,
          };

          if (tickMarkType < 3) { // Day, Month, Year
            return new Intl.DateTimeFormat(locale, {
              ...options,
              day: '2-digit',
              month: 'short',
            }).format(date);
          } else { // Time
            return new Intl.DateTimeFormat(locale, {
              ...options,
              hour: '2-digit',
              minute: '2-digit',
            }).format(date);
          }
        },
      },
      localization: {
        locale: 'en-IN',
        timeFormatter: (time: number) => {
          const date = new Date(time * 1000);
          return date.toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: 'Asia/Kolkata'
          });
        },
        priceFormatter: (price: number) => price.toFixed(2),
      },
      width: chartContainerRef.current.clientWidth,
      height: 500,
    });

    // Main series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    // EMA Lines
    const ema9Line = chart.addSeries(LineSeries, {
      color: '#60a5fa',
      lineWidth: 1,
      title: 'EMA 9',
    });

    const ema21Line = chart.addSeries(LineSeries, {
      color: '#f472b6',
      lineWidth: 1,
      title: 'EMA 21',
    });

    // Supertrend Line
    const supertrendLine = chart.addSeries(LineSeries, {
      lineWidth: 2,
      lineStyle: 0,
      title: 'Supertrend',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    ema9Ref.current = ema9Line;
    ema21Ref.current = ema21Line;
    supertrendRef.current = supertrendLine;
    setInitialized(true);

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      setInitialized(false);
      chartRef.current = null;
    };
  }, []); // Remove initialized dependency

  useEffect(() => {
    const cleanup = initChart();
    return () => {
      if (cleanup) cleanup();
    };
  }, [initChart]);

  useEffect(() => {
    if (!initialized || !data) return;

    if (candleSeriesRef.current) {
      if (data.candles && data.candles.length > 0) {
        candleSeriesRef.current.setData(data.candles as CandlestickData<Time>[]);
      } else {
        candleSeriesRef.current.setData([]);
      }
    }

    if (ema9Ref.current) {
      const filtered = data.ema9 ? (data.ema9 as LineData<Time>[]).filter(d => d.value !== null) : [];
      ema9Ref.current.setData(filtered);
    }

    if (ema21Ref.current) {
      const filtered = data.ema21 ? (data.ema21 as LineData<Time>[]).filter(d => d.value !== null) : [];
      ema21Ref.current.setData(filtered);
    }

    if (supertrendRef.current) {
      const filtered = data.supertrend ? (data.supertrend as LineData<Time>[]).filter(d => d.value !== null) : [];
      supertrendRef.current.setData(filtered);
    }

    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }

    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [data, initialized]);

  return (
    <div className="chart-container">
      <div className="chart-header">
        <div className="flex flex-col gap-1">
          <h3>NIFTY 50 — Supertrend Strategy</h3>
          <p className="text-xs text-gray-500">
            EMA Crossover + Supertrend + ADX Filter
          </p>
        </div>
        <div className="chart-legend flex flex-wrap gap-x-4 gap-y-1 justify-end max-w-[50%]">
          <span className="legend-item flex items-center gap-1" style={{ color: '#60a5fa' }}>
            <span className="w-3 h-1 bg-[#60a5fa]"></span> EMA 9
          </span>
          <span className="legend-item flex items-center gap-1" style={{ color: '#f472b6' }}>
            <span className="w-3 h-1 bg-[#f472b6]"></span> EMA 21
          </span>
          <span className="legend-item flex items-center gap-1" style={{ color: '#10b981' }}>
            <span className="w-3 h-1 bg-[#10b981]"></span> Supertrend (Long)
          </span>
          <span className="legend-item flex items-center gap-1" style={{ color: '#ef4444' }}>
            <span className="w-3 h-1 bg-[#ef4444]"></span> Supertrend (Short)
          </span>
        </div>
      </div>
      <div ref={chartContainerRef} className="chart-canvas" />
      <div className="chart-attribution">
        Powered by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a>
      </div>
    </div>
  );
}
