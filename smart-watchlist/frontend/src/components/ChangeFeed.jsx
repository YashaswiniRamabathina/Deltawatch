import { formatPrice, parseInstant } from '../format';

function fmtTimeSince(dateStr) {
  if (!dateStr) return null;
  const instant = parseInstant(dateStr);
  if (!instant || Number.isNaN(instant.getTime())) return null;
  const diffMs = Date.now() - instant.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export default function ChangeFeed({ entries, loading, onAcknowledge }) {
  if (loading) {
    return <div style={styles.empty}>Checking for changes…</div>;
  }

  if (!entries || entries.length === 0) {
    return (
      <div style={styles.empty}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Nothing needs your attention</div>
        <div className="muted" style={{ fontSize: 13 }}>
          This isn't a 5% move alert. Nothing unusual for these stocks since you last looked.
        </div>
      </div>
    );
  }

  return (
    <div style={styles.list}>
      {entries.map((entry) => (
        <div key={entry.symbol} style={styles.card}>
          <div style={styles.cardTop}>
            <div style={styles.symbolBlock}>
              <span style={styles.symbol}>{entry.symbol}</span>
              {entry.is_held && <span style={styles.heldTag}>in your holdings</span>}
              {entry.since && (
                <span className="muted" style={styles.since}>since {fmtTimeSince(entry.since)}</span>
              )}
            </div>
            <div style={styles.priceBlock}>
              {entry.price != null && (
                <span className="num" style={{ fontWeight: 600 }}>{formatPrice(entry.symbol, entry.price)}</span>
              )}
              {entry.change_pct != null && (
                <span className={`num ${entry.change_pct >= 0 ? 'positive' : 'negative'}`} style={styles.changePct}>
                  {entry.change_pct >= 0 ? '+' : ''}{entry.change_pct.toFixed(2)}%
                </span>
              )}
            </div>
          </div>

          <ul style={styles.reasons}>
            {entry.reasons.map((r, i) => (
              <li key={i} style={styles.reasonItem}>{r}</li>
            ))}
          </ul>

          <button style={styles.ackButton} onClick={() => onAcknowledge(entry.symbol)}>
            Mark as seen
          </button>
        </div>
      ))}
    </div>
  );
}

const styles = {
  empty: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '28px 24px',
    color: 'var(--text)',
  },
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  card: {
    background: 'var(--surface)',
    border: '1px solid rgba(245, 166, 35, 0.35)',
    borderLeft: '3px solid var(--amber)',
    borderRadius: 'var(--radius)',
    padding: '16px 18px',
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginBottom: 8,
    flexWrap: 'wrap',
    gap: 8,
  },
  symbolBlock: { display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' },
  symbol: { fontWeight: 700, fontSize: 16, letterSpacing: 0.3 },
  heldTag: {
    fontSize: 10,
    fontWeight: 500,
    letterSpacing: 0.2,
    color: 'var(--amber)',
    border: '1px solid rgba(245,166,35,0.4)',
    borderRadius: 4,
    padding: '1px 6px',
    fontFamily: 'var(--font-ui)',
  },
  since: { fontSize: 12 },
  priceBlock: { display: 'flex', alignItems: 'baseline', gap: 10 },
  changePct: { fontSize: 14 },
  reasons: { margin: '0 0 12px', paddingLeft: 18, fontSize: 13.5, color: 'var(--text)', lineHeight: 1.7 },
  reasonItem: {},
  ackButton: {
    background: 'transparent',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 6,
    padding: '5px 12px',
    fontSize: 12.5,
  },
};
