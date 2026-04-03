import type { Trade } from '../types';

interface TradeLogProps {
  trades: Trade[];
}

const STATUS_COLORS: Record<string, string> = {
  PENDING: '#ff9100',
  FILLED: '#00c853',
  PARTIAL: '#ffab00',
  CANCELLED: '#78909c',
  ERROR: '#ff1744',
  HALTED: '#ff1744',
};

const STATUS_LABELS: Record<string, string> = {
  PENDING: '대기',
  FILLED: '체결',
  PARTIAL: '부분체결',
  CANCELLED: '취소',
  ERROR: '오류',
  HALTED: '정지',
};

export default function TradeLog({ trades }: TradeLogProps) {
  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.title}>거래 내역</h2>
        <span style={styles.count}>{trades.length}건</span>
      </div>
      <div style={styles.list}>
        {trades.length === 0 ? (
          <div style={styles.empty}>거래 내역이 없습니다</div>
        ) : (
          trades.map((trade) => (
            <div key={trade.id} style={styles.item}>
              <div style={styles.itemTop}>
                <div style={styles.itemLeft}>
                  <span style={{
                    ...styles.actionBadge,
                    backgroundColor: trade.action === 'BUY' ? '#ef5350' : '#2196f3',
                  }}>
                    {trade.action === 'BUY' ? '매수' : '매도'}
                  </span>
                  <span style={styles.ticker}>{trade.ticker}</span>
                </div>
                <span style={{
                  ...styles.statusBadge,
                  color: STATUS_COLORS[trade.status] ?? '#78909c',
                }}>
                  {STATUS_LABELS[trade.status] ?? trade.status}
                </span>
              </div>
              <div style={styles.itemBottom}>
                <span>{trade.quantity}주 x {trade.price.toLocaleString()}원</span>
                <span style={styles.total}>
                  {(trade.quantity * trade.price).toLocaleString()}원
                </span>
              </div>
              <div style={styles.meta}>
                <span>{trade.strategyName ?? '수동'}</span>
                <span>{new Date(trade.createdAt).toLocaleString('ko-KR')}</span>
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
  count: {
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
    marginBottom: '2px',
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
  ticker: {
    fontWeight: 600,
    fontSize: '14px',
  },
  statusBadge: {
    fontSize: '11px',
    fontWeight: 600,
  },
  itemBottom: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '12px',
    color: '#a0b0c0',
    marginBottom: '2px',
  },
  total: {
    fontWeight: 600,
    color: '#e0e0e0',
  },
  meta: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '11px',
    color: '#556677',
  },
  empty: {
    padding: '24px',
    textAlign: 'center',
    color: '#8899aa',
    fontSize: '14px',
  },
};
