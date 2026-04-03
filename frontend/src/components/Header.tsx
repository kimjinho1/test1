import type { SystemStatus } from '../types';

interface HeaderProps {
  status: SystemStatus;
  isStale: boolean;
  onModeToggle: () => void;
  onEmergencyStop: () => void;
}

export default function Header({ status, isStale, onModeToggle, onEmergencyStop }: HeaderProps) {
  return (
    <header style={styles.header}>
      <div style={styles.left}>
        <h1 style={styles.title}>주식 자동매매 대시보드</h1>
        <span style={{
          ...styles.badge,
          backgroundColor: status.marketOpen ? '#00c853' : '#ff5252',
        }}>
          {status.marketOpen ? '장 운영중' : '장 마감'}
        </span>
        <span style={{
          ...styles.badge,
          backgroundColor: status.apiConnected ? '#00c853' : '#ff5252',
        }}>
          API {status.apiConnected ? '연결됨' : '끊김'}
        </span>
        {isStale && (
          <span style={{ ...styles.badge, backgroundColor: '#ff9100' }}>
            데이터 지연
          </span>
        )}
        {status.halted && (
          <span style={{ ...styles.badge, backgroundColor: '#ff1744' }}>
            긴급 정지됨
          </span>
        )}
      </div>
      <div style={styles.right}>
        <button
          onClick={onModeToggle}
          style={{
            ...styles.modeButton,
            backgroundColor: status.mode === 'auto' ? '#00c853' : '#546e7a',
          }}
        >
          {status.mode === 'auto' ? '자동매매 ON' : '수동모드'}
        </button>
        <button
          onClick={onEmergencyStop}
          style={styles.emergencyButton}
        >
          긴급 정지
        </button>
      </div>
    </header>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 16px',
    backgroundColor: '#16213e',
    borderBottom: '1px solid #0f3460',
  },
  left: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  right: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  title: {
    fontSize: '18px',
    fontWeight: 700,
    margin: 0,
    color: '#e94560',
  },
  badge: {
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#fff',
  },
  modeButton: {
    padding: '6px 16px',
    border: 'none',
    borderRadius: '4px',
    color: '#fff',
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: '13px',
  },
  emergencyButton: {
    padding: '6px 16px',
    border: '2px solid #ff1744',
    borderRadius: '4px',
    backgroundColor: 'transparent',
    color: '#ff1744',
    fontWeight: 700,
    cursor: 'pointer',
    fontSize: '13px',
  },
};
