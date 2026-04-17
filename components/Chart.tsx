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
  const emaFastLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const emaSlowLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const vwapLineRef = useRef<ISeriesApi<'Line'> | null>(null);
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

    // EMA 9 (Fast) - Cyan
    const emaFastLine = chart.addSeries(LineSeries, {
      color: '#06b6d4',
      lineWidth: 2,
      title: 'EMA 9',
    });

    // EMA 21 (Slow) - Yellow
    const emaSlowLine = chart.addSeries(LineSeries, {
      color: '#eab308',
      lineWidth: 2,
      title: 'EMA 21',
    });

    // VWAP - Magenta
    const vwapLine = chart.addSeries(LineSeries, {
      color: '#d946ef',
      lineWidth: 2,
      lineStyle: 2,
      title: 'VWAP',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaFastLineRef.current = emaFastLine;
    emaSlowLineRef.current = emaSlowLine;
    vwapLineRef.current = vwapLine;
    setInitialized(true);

    // Resize handler
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

    if (data.ema_fast && data.ema_fast.length > 0 && emaFastLineRef.current) {
      emaFastLineRef.current.setData(data.ema_fast as LineData<Time>[]);
    }

    if (data.ema_slow && data.ema_slow.length > 0 && emaSlowLineRef.current) {
      emaSlowLineRef.current.setData(data.ema_slow as LineData<Time>[]);
    }

    if (data.vwap && data.vwap.length > 0 && vwapLineRef.current) {
      vwapLineRef.current.setData(data.vwap as LineData<Time>[]);
    }

    // Auto-scroll to latest
    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [data, initialized]);

  return (
    <div className="chart-container">
      <div className="chart-header">
        <h3>NIFTY 50 — 5 Min Chart</h3>
        <div className="chart-legend">
          <span className="legend-item" style={{ color: '#06b6d4' }}>● EMA 9</span>
          <span className="legend-item" style={{ color: '#eab308' }}>● EMA 21</span>
          <span className="legend-item" style={{ color: '#d946ef' }}>● VWAP</span>
        </div>
      </div>
      <div ref={chartContainerRef} className="chart-canvas" />
      <div className="chart-attribution">
        Powered by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a>
      </div>
    </div>
  );
}
