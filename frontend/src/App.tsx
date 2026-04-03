import { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import Header from './components/Header';
import Chart from './components/Chart';
import Portfolio from './components/Portfolio';
import Signals from './components/Signals';
import TradeLog from './components/TradeLog';
import type { Position, Signal, Trade, SystemStatus, PriceData, OHLCV, WSMessage } from './types';

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/dashboard`;

const defaultStatus: SystemStatus = {
  marketOpen: false,
  mode: 'manual',
  apiConnected: false,
  halted: false,
};

function App() {
  const { lastMessage, isConnected, isStale, send } = useWebSocket(WS_URL);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [status, setStatus] = useState<SystemStatus>(defaultStatus);
  const [prices, setPrices] = useState<Record<string, PriceData>>({});
  const [chartData, setChartData] = useState<OHLCV[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>('');

  // Handle incoming WebSocket messages
  useEffect(() => {
    if (!lastMessage) return;

    const { type, data } = lastMessage as WSMessage;

    switch (type) {
      case 'portfolio':
        setPositions(data as Position[]);
        break;
      case 'signal':
        setSignals((prev) => [data as Signal, ...prev].slice(0, 100));
        break;
      case 'trade':
        setTrades((prev) => [data as Trade, ...prev].slice(0, 200));
        break;
      case 'status':
        setStatus((prev) => ({ ...prev, ...(data as Partial<SystemStatus>) }));
        break;
      case 'price': {
        const priceData = data as PriceData;
        setPrices((prev) => ({ ...prev, [priceData.ticker]: priceData }));
        break;
      }
    }
  }, [lastMessage]);

  // Update connection status
  useEffect(() => {
    setStatus((prev) => ({ ...prev, apiConnected: isConnected }));
  }, [isConnected]);

  // Load initial data
  useEffect(() => {
    const loadInitial = async () => {
      try {
        const [posRes, sigRes, tradeRes, statusRes] = await Promise.all([
          fetch('/api/portfolio'),
          fetch('/api/signals'),
          fetch('/api/trades'),
          fetch('/api/status'),
        ]);
        if (posRes.ok) setPositions(await posRes.json());
        if (sigRes.ok) setSignals(await sigRes.json());
        if (tradeRes.ok) setTrades(await tradeRes.json());
        if (statusRes.ok) setStatus(await statusRes.json());
      } catch {
        // API not available yet
      }
    };
    loadInitial();
  }, []);

  // Load chart data when ticker changes
  useEffect(() => {
    if (!selectedTicker) return;
    const loadChart = async () => {
      try {
        const res = await fetch(`/api/chart/${selectedTicker}`);
        if (res.ok) setChartData(await res.json());
      } catch {
        // ignore
      }
    };
    loadChart();
  }, [selectedTicker]);

  // Auto-select first position's ticker
  useEffect(() => {
    if (!selectedTicker && positions.length > 0) {
      setSelectedTicker(positions[0].ticker);
    }
  }, [positions, selectedTicker]);

  const handleModeToggle = useCallback(() => {
    const newMode = status.mode === 'auto' ? 'manual' : 'auto';
    fetch('/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newMode }),
    });
  }, [status.mode]);

  const handleEmergencyStop = useCallback(() => {
    fetch('/api/emergency-stop', { method: 'POST' });
  }, []);

  const handleSignalAction = useCallback(
    (signalId: number, action: 'execute' | 'ignore') => {
      fetch(`/api/signals/${signalId}/${action}`, { method: 'POST' });
      send({ type: 'signal_action', signalId, action });
    },
    [send],
  );

  const handleTickerSelect = useCallback((ticker: string) => {
    setSelectedTicker(ticker);
  }, []);

  return (
    <div style={styles.container}>
      <Header
        status={status}
        isStale={isStale}
        onModeToggle={handleModeToggle}
        onEmergencyStop={handleEmergencyStop}
      />
      <div style={styles.dashboard}>
        <div style={styles.topRow}>
          <div style={styles.chartPanel}>
            <Chart
              data={chartData}
              ticker={selectedTicker}
              currentPrice={prices[selectedTicker]}
            />
          </div>
          <div style={styles.portfolioPanel}>
            <Portfolio
              positions={positions}
              prices={prices}
              onTickerSelect={handleTickerSelect}
              selectedTicker={selectedTicker}
            />
          </div>
        </div>
        <div style={styles.bottomRow}>
          <div style={styles.signalsPanel}>
            <Signals
              signals={signals}
              onAction={handleSignalAction}
              mode={status.mode}
            />
          </div>
          <div style={styles.tradeLogPanel}>
            <TradeLog trades={trades} />
          </div>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    backgroundColor: '#1a1a2e',
    color: '#e0e0e0',
    fontFamily: "'Segoe UI', -apple-system, sans-serif",
    overflow: 'hidden',
  },
  dashboard: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    padding: '8px',
    gap: '8px',
    overflow: 'hidden',
  },
  topRow: {
    flex: 3,
    display: 'flex',
    gap: '8px',
    minHeight: 0,
  },
  bottomRow: {
    flex: 2,
    display: 'flex',
    gap: '8px',
    minHeight: 0,
  },
  chartPanel: {
    flex: 2,
    minWidth: 0,
  },
  portfolioPanel: {
    flex: 1,
    minWidth: 0,
  },
  signalsPanel: {
    flex: 1,
    minWidth: 0,
  },
  tradeLogPanel: {
    flex: 1,
    minWidth: 0,
  },
};

export default App;
