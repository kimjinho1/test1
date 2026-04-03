import type { Position, PriceData } from '../types';

interface PortfolioProps {
  positions: Position[];
  prices: Record<string, PriceData>;
  onTickerSelect: (ticker: string) => void;
  selectedTicker: string;
}

export default function Portfolio({ positions, prices, onTickerSelect, selectedTicker }: PortfolioProps) {
  const totalValue = positions.reduce((sum, p) => {
    const price = prices[p.ticker]?.price ?? p.currentPrice;
    return sum + price * p.quantity;
  }, 0);

  const totalPnl = positions.reduce((sum, p) => {
    const price = prices[p.ticker]?.price ?? p.currentPrice;
    return sum + (price - p.avgPrice) * p.quantity;
  }, 0);

  const totalCost = positions.reduce((sum, p) => sum + p.avgPrice * p.quantity, 0);
  const totalPnlPercent = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.title}>포트폴리오</h2>
        <div style={styles.summary}>
          <span style={styles.totalValue}>{totalValue.toLocaleString()}원</span>
          <span style={{
            ...styles.totalPnl,
            color: totalPnl >= 0 ? '#ef5350' : '#2196f3',
          }}>
            {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString()}원
            ({totalPnlPercent >= 0 ? '+' : ''}{totalPnlPercent.toFixed(2)}%)
          </span>
        </div>
      </div>
      <div style={styles.list}>
        {positions.length === 0 ? (
          <div style={styles.empty}>보유 종목이 없습니다</div>
        ) : (
          positions.map((pos) => {
            const price = prices[pos.ticker]?.price ?? pos.currentPrice;
            const pnl = (price - pos.avgPrice) * pos.quantity;
            const pnlPct = ((price - pos.avgPrice) / pos.avgPrice) * 100;
            const isSelected = pos.ticker === selectedTicker;

            return (
              <div
                key={pos.ticker}
                style={{
                  ...styles.item,
                  backgroundColor: isSelected ? '#1e2d4a' : 'transparent',
                  borderLeft: isSelected ? '3px solid #e94560' : '3px solid transparent',
                }}
                onClick={() => onTickerSelect(pos.ticker)}
              >
                <div style={styles.itemTop}>
                  <span style={styles.itemTicker}>{pos.ticker}</span>
                  <span style={{
                    color: pnl >= 0 ? '#ef5350' : '#2196f3',
                    fontWeight: 600,
                    fontSize: '13px',
                  }}>
                    {pnl >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                  </span>
                </div>
                <div style={styles.itemBottom}>
                  <span style={styles.itemDetail}>{pos.quantity}주 | 평균 {pos.avgPrice.toLocaleString()}원</span>
                  <span style={styles.itemDetail}>{price.toLocaleString()}원</span>
                </div>
              </div>
            );
          })
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
    padding: '10px 12px',
    borderBottom: '1px solid #0f3460',
  },
  title: {
    margin: '0 0 4px 0',
    fontSize: '14px',
    fontWeight: 700,
    color: '#e0e0e0',
  },
  summary: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  totalValue: {
    fontSize: '18px',
    fontWeight: 700,
  },
  totalPnl: {
    fontSize: '13px',
    fontWeight: 600,
  },
  list: {
    flex: 1,
    overflowY: 'auto',
  },
  item: {
    padding: '8px 12px',
    cursor: 'pointer',
    borderBottom: '1px solid #0f3460',
    transition: 'background-color 0.15s',
  },
  itemTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '2px',
  },
  itemTicker: {
    fontWeight: 600,
    fontSize: '14px',
  },
  itemBottom: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '12px',
    color: '#8899aa',
  },
  itemDetail: {
    fontSize: '12px',
  },
  empty: {
    padding: '24px',
    textAlign: 'center',
    color: '#8899aa',
    fontSize: '14px',
  },
};
