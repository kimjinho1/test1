import { useEffect, useRef, useState, useCallback } from 'react';
import type { WSMessage } from '../types';

const STALE_TIMEOUT = 10_000; // 10 seconds
const RECONNECT_DELAY = 3_000;

interface UseWebSocketReturn {
  lastMessage: WSMessage | null;
  isConnected: boolean;
  isStale: boolean;
  send: (data: unknown) => void;
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const lastMessageTimeRef = useRef<number>(Date.now());
  const staleTimerRef = useRef<ReturnType<typeof setInterval>>();
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      setIsConnected(true);
      setIsStale(false);
      lastMessageTimeRef.current = Date.now();
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        setLastMessage(msg);
        lastMessageTimeRef.current = Date.now();
        setIsStale(false);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
      reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [url]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  // Connect on mount
  useEffect(() => {
    connect();

    // Staleness checker
    staleTimerRef.current = setInterval(() => {
      if (Date.now() - lastMessageTimeRef.current > STALE_TIMEOUT) {
        setIsStale(true);
      }
    }, 1_000);

    return () => {
      clearInterval(staleTimerRef.current);
      clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { lastMessage, isConnected, isStale, send };
}
