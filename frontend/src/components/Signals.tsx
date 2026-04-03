import type { Signal } from '../types';

interface SignalsProps {
  signals: Signal[];
  onAction: (signalId: number, action: 'execute' | 'ignore') => void;
  mode: 'auto' | 'manual';
}

const ACTION_COLORS: Record<string, string> = {
  BUY: '#ef5350',
  SELL: '#2196f3',
  HOLD: '#78909c',
};

const ACTION_LABELS: Record<string, string> = {
  BUY: '매수',
  SELL: '매도',
  HOLD: '관망',
};

export default function Signals({ signals, onAction, mode }: SignalsProps) {
  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.title}>전략 시그널</h2>
        <span style={styles.modeLabel}>
          {mode === 'auto' ? '자동실행' : '수동확인'}
        </span>
      </div>
      <div style={styles.list}>
        {signals.length === 0 ? (
          <div style={styles.empty}>시그널이 없습니다</div>
        ) : (
          signals.map((sig) => (
            <div key={sig.id} style={styles.item}>
              <div style={styles.itemTop}>
                <div style={styles.itemLeft}>
                  <span style={{
                    ...styles.actionBadge,
                    backgroundColor: ACTION_COLORS[sig.action] ?? '#78909c',
                  }}>
                    {ACTION_LABELS[sig.action] ?? sig.action}
                  </span>
                  <span style={styles.itemTicker}>{sig.ticker}</span>
                  <span style={styles.confidence}>
                    신뢰도 {(sig.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <span style={styles.time}>
                  {new Date(sig.createdAt).toLocaleTimeString('ko-KR')}
                </span>
              </div>
              <div style={styles.reason}>{sig.reason}</div>
              <div style={styles.meta}>
                <span style={styles.strategy}>{sig.strategyName}</span>
                {sig.actedOn === 0 && sig.action !== 'HOLD' && mode === 'manual' && (
                  <div style={styles.actions}>
                    <button
                      style={styles.execButton}
                      onClick={() => onAction(sig.id, 'execute')}
                    >
                      실행
                    </button>
                    <button
                      style={styles.ignoreButton}
                      onClick={() => onAction(sig.id, 'ignore')}
                    >
                      무시
                    </button>
                  </div>
                )}
                {sig.actedOn === 1 && <span style={styles.executedBadge}>실행됨</span>}
                {sig.actedOn === 2 && <span style={styles.ignoredBadge}>무시됨</span>}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    backgroundColor: '#16213e',
    borderRadius: '8px',
    border: '1px solid #0f3460',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 12px',
    borderBottom: '1px solid #0f3460',
  },
  title: {
    margin: 0,
    fontSize: '14px',
    fontWeight: 700,
  },
  modeLabel: {
    fontSize: '12px',
    color: '#8899aa',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
  },
  item: {
    padding: '8px 12px',
    borderBottom: '1px solid #0f3460',
  },
  itemTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '4px',
  },
  itemLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  actionBadge: {
    padding: '1px 6px',
    borderRadius: '3px',
    fontSize: '11px',
    fontWeight: 700,
    color: '#fff',
  },
  itemTicker: {
    fontWeight: 600,
    fontSize: '14px',
  },
  confidence: {
    fontSize: '12px',
    color: '#8899aa',
  },
  time: {
    fontSize: '11px',
    color: '#667788',
  },
  reason: {
    fontSize: '12px',
    color: '#a0b0c0',
    marginBottom: '4px',
  },
  meta: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  strategy: {
    fontSize: '11px',
    color: '#556677',
  },
  actions: {
    display: 'flex',
    gap: '4px',
  },
  execButton: {
    padding: '2px 10px',
    border: 'none',
    borderRadius: '3px',
    backgroundColor: '#00c853',
    color: '#fff',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  ignoreButton: {
    padding: '2px 10px',
    border: 'none',
    borderRadius: '3px',
    backgroundColor: '#546e7a',
    color: '#fff',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  executedBadge: {
    fontSize: '11px',
    color: '#00c853',
    fontWeight: 600,
  },
  ignoredBadge: {
    fontSize: '11px',
    color: '#78909c',
  },
  empty: {
    padding: '24px',
    textAlign: 'center',
    color: '#8899aa',
    fontSize: '14px',
  },
};
