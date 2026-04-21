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
  const orbHighRef = useRef<ISeriesApi<'Line'> | null>(null);
  const orbLowRef = useRef<ISeriesApi<'Line'> | null>(null);
  const vwapRef = useRef<ISeriesApi<'Line'> | null>(null);
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

    // ORB Lines - Cyan
    const orbHigh = chart.addSeries(LineSeries, {
      color: '#06b6d4',
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: 'ORB High',
    });

    const orbLow = chart.addSeries(LineSeries, {
      color: '#06b6d4',
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: 'ORB Low',
    });

    // VWAP Line - Yellow/Amber
    const vwapLine = chart.addSeries(LineSeries, {
      color: '#eab308',
      lineWidth: 2,
      lineStyle: 0, // Solid
      title: 'VWAP',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    orbHighRef.current = orbHigh;
    orbLowRef.current = orbLow;
    vwapRef.current = vwapLine;
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

    if (orbHighRef.current) {
      if (data.orb_high && data.orb_high.length > 0) {
        orbHighRef.current.setData(data.orb_high as LineData<Time>[]);
      } else {
        orbHighRef.current.setData([]);
      }
    }

    if (orbLowRef.current) {
      if (data.orb_low && data.orb_low.length > 0) {
        orbLowRef.current.setData(data.orb_low as LineData<Time>[]);
      } else {
        orbLowRef.current.setData([]);
      }
    }

    if (vwapRef.current) {
      if (data.vwap && data.vwap.length > 0) {
        vwapRef.current.setData(data.vwap as LineData<Time>[]);
      } else {
        vwapRef.current.setData([]);
      }
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
          <h3>NIFTY 50 — Natural ORB Strategy</h3>
          <p className="text-xs text-gray-500">
            Strategy: Standard 15-Minute Opening Range Breakout
          </p>
        </div>
        <div className="chart-legend flex flex-wrap gap-x-4 gap-y-1 justify-end max-w-[50%]">
          <span className="legend-item flex items-center gap-1" style={{ color: '#06b6d4' }}>
            <span className="w-3 h-1 bg-[#06b6d4]"></span> ORB High/Low
          </span>
          <span className="legend-item flex items-center gap-1" style={{ color: '#eab308' }}>
            <span className="w-3 h-1 bg-[#eab308]"></span> VWAP
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
