import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi, type CandlestickData } from 'lightweight-charts';
import type { OHLCV, PriceData } from '../types';

interface ChartProps {
  data: OHLCV[];
  ticker: string;
  currentPrice?: PriceData;
}

export default function Chart({ data, ticker, currentPrice }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  // Create chart on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#1a1a2e' },
        textColor: '#a0a0a0',
      },
      grid: {
        vertLines: { color: '#1e2d4a' },
        horzLines: { color: '#1e2d4a' },
      },
      crosshair: {
        mode: 0,
      },
      timeScale: {
        borderColor: '#2a3a5c',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#2a3a5c',
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: '#ef5350',    // Korean market: red = up
      downColor: '#2196f3',  // blue = down
      borderUpColor: '#ef5350',
      borderDownColor: '#2196f3',
      wickUpColor: '#ef5350',
      wickDownColor: '#2196f3',
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Update data
  useEffect(() => {
    if (!seriesRef.current || data.length === 0) return;

    const candleData: CandlestickData[] = data.map((d) => ({
      time: d.time as unknown as CandlestickData['time'],
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));

    seriesRef.current.setData(candleData);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  // Update last candle with real-time price
  useEffect(() => {
    if (!seriesRef.current || !currentPrice || data.length === 0) return;

    const lastCandle = data[data.length - 1];
    seriesRef.current.update({
      time: lastCandle.time as unknown as CandlestickData['time'],
      open: lastCandle.open,
      high: Math.max(lastCandle.high, currentPrice.price),
      low: Math.min(lastCandle.low, currentPrice.price),
      close: currentPrice.price,
    });
  }, [currentPrice, data]);

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.ticker}>{ticker || '종목을 선택하세요'}</span>
        {currentPrice && (
          <>
            <span style={styles.price}>{currentPrice.price.toLocaleString()}원</span>
            <span style={{
              ...styles.change,
              color: currentPrice.change >= 0 ? '#ef5350' : '#2196f3',
            }}>
              {currentPrice.change >= 0 ? '+' : ''}{currentPrice.change.toLocaleString()}
              ({currentPrice.changePercent >= 0 ? '+' : ''}{currentPrice.changePercent.toFixed(2)}%)
            </span>
          </>
        )}
      </div>
      <div ref={containerRef} style={styles.chart} />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    backgroundColor: '#1a1a2e',
    borderRadius: '8px',
    border: '1px solid #0f3460',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '8px 12px',
    borderBottom: '1px solid #0f3460',
  },
  ticker: {
    fontWeight: 700,
    fontSize: '16px',
    color: '#e0e0e0',
  },
  price: {
    fontSize: '16px',
    fontWeight: 600,
  },
  change: {
    fontSize: '14px',
    fontWeight: 500,
  },
  chart: {
    flex: 1,
  },
};
