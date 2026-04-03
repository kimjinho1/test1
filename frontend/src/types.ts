export interface PriceData {
  ticker: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  timestamp: string;
}

export interface OHLCV {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Position {
  ticker: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  updatedAt: string;
}

export interface Signal {
  id: number;
  ticker: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  reason: string;
  strategyName: string;
  actedOn: number; // 0=pending, 1=executed, 2=ignored
  createdAt: string;
}

export interface Trade {
  id: number;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  brokerOrderId: string | null;
  strategyName: string | null;
  signalConfidence: number | null;
  status: string;
  createdAt: string;
}

export interface SystemStatus {
  marketOpen: boolean;
  mode: 'auto' | 'manual';
  apiConnected: boolean;
  halted: boolean;
}

export type WSMessageType = 'price' | 'signal' | 'portfolio' | 'trade' | 'status';

export interface WSMessage {
  type: WSMessageType;
  data: unknown;
}
