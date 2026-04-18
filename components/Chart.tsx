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
  const stLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const orbHighRef = useRef<ISeriesApi<'Line'> | null>(null);
  const orbLowRef = useRef<ISeriesApi<'Line'> | null>(null);
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
        scaleMargins: { top: 0.1, bottom: 0.1 },
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

          // TickMarkType: 0=Year, 1=Month, 2=Day, 3=Time, 4=TimeWithSeconds
          if (tickMarkType < 3) {
            return new Intl.DateTimeFormat(locale, {
              ...options,
              day: '2-digit',
              month: 'short',
            }).format(date);
          } else {
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
      height: 400,
    });

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    // Supertrend Line
    const stLine = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineWidth: 2,
      title: 'Supertrend',
    });

    // ORB High - Green Dashed
    const orbHigh = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: 'ORB High',
    });

    // ORB Low - Red Dashed
    const orbLow = chart.addSeries(LineSeries, {
      color: '#ef4444',
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: 'ORB Low',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    stLineRef.current = stLine;
    orbHighRef.current = orbHigh;
    orbLowRef.current = orbLow;
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
    };
  }, [initialized]);

  useEffect(() => {
    const cleanup = initChart();
    return () => {
      if (cleanup) cleanup();
      setInitialized(false);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!initialized || !data) return;

    if (data.candles && data.candles.length > 0 && candleSeriesRef.current) {
      candleSeriesRef.current.setData(data.candles as CandlestickData<Time>[]);
    }

    if (data.supertrend && data.supertrend.length > 0 && stLineRef.current) {
      stLineRef.current.setData(data.supertrend as LineData<Time>[]);
    }

    if (data.orb_high && data.orb_high.length > 0 && orbHighRef.current) {
      orbHighRef.current.setData(data.orb_high as LineData<Time>[]);
    }

    if (data.orb_low && data.orb_low.length > 0 && orbLowRef.current) {
      orbLowRef.current.setData(data.orb_low as LineData<Time>[]);
    }

    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [data, initialized]);

  return (
    <div className="chart-container">
      <div className="chart-header">
        <h3>NIFTY 50 — ORB + Supertrend</h3>
        <div className="chart-legend">
          <span className="legend-item" style={{ color: '#22c55e' }}>● Supertrend</span>
          <span className="legend-item" style={{ color: '#22c55e', borderBottom: '1px dashed #22c55e' }}>ORB High</span>
          <span className="legend-item" style={{ color: '#ef4444', borderBottom: '1px dashed #ef4444' }}>ORB Low</span>
        </div>
      </div>
      <div ref={chartContainerRef} className="chart-canvas" />
      <div className="chart-attribution">
        Powered by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a>
      </div>
    </div>
  );
}
