import { formatPrice } from '../format';

export default function WatchlistTable({ items, onRemove, onToggleHeld }) {
  if (!items || items.length === 0) {
    return (
      <div style={styles.empty}>
        Your watchlist is empty. Add a symbol above to start tracking it.
      </div>
    );
  }

  return (
    <div style={styles.tableWrap}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Symbol</th>
            <th style={styles.th}>Price</th>
            <th style={styles.th}>Change</th>
            <th style={styles.th}>Volume</th>
            <th style={styles.th}>52w range</th>
            <th style={styles.th}>Attention</th>
            <th style={styles.th}>Source</th>
            <th style={styles.th}></th>
          </tr>
        </thead>
        <tbody>
          {items.map(({ symbol, quote, is_held }) => (
            <tr key={symbol} style={styles.tr}>
              <td style={styles.tdSymbol}>
                {symbol}
                {is_held && <span style={styles.heldTag}>holding</span>}
              </td>
              {!quote.has_data ? (
                <td colSpan={6} style={styles.pending}>waiting for a quote</td>
              ) : (
                <>
                  <td className="num" style={styles.td}>
                    {quote.price != null ? formatPrice(symbol, quote.price) : '—'}
                    {quote.is_stale && <span style={styles.staleTag} title="Data may be delayed">delayed</span>}
                    {quote.flagged_conflict && (
                      <span style={styles.conflictTag} title="Yahoo and Stooq disagree by more than 1.5%">
                        sources disagree
                      </span>
                    )}
                  </td>
                  <td className={`num ${quote.change_pct >= 0 ? 'positive' : 'negative'}`} style={styles.td}>
                    {quote.change_pct != null ? `${quote.change_pct >= 0 ? '+' : ''}${quote.change_pct.toFixed(2)}%` : '—'}
                  </td>
                  <td className="num muted" style={styles.td}>
                    {quote.volume != null ? formatVolume(quote.volume) : '—'}
                  </td>
                  <td className="num muted" style={styles.td}>
                    {quote.low_52w != null && quote.high_52w != null
                      ? `${quote.low_52w.toFixed(0)}–${quote.high_52w.toFixed(0)}`
                      : '—'}
                  </td>
                  <td style={{ ...styles.td, maxWidth: 220 }}>
                    <AttentionBar score={quote.change_score} />
                    {quote.reasons?.[0] && (
                      <div className="muted" style={styles.reason}>
                        {quote.reasons[0]}
                      </div>
                    )}
                  </td>
                  <td className="muted" style={{ ...styles.td, fontSize: 12 }}>
                    {quote.source || '—'}
                  </td>
                </>
              )}
              <td style={styles.td}>
                <div style={styles.actions}>
                  <button
                    onClick={() => onToggleHeld(symbol, !is_held)}
                    style={is_held ? styles.heldBtn : styles.holdBtn}
                    aria-pressed={!!is_held}
                  >
                    {is_held ? 'Holding' : 'I hold this'}
                  </button>
                  <button onClick={() => onRemove(symbol)} style={styles.removeBtn} aria-label={`Remove ${symbol}`}>
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AttentionBar({ score }) {
  const clamped = Math.max(0, Math.min(score || 0, 10));
  const pct = (clamped / 10) * 100;
  const isNotable = score >= 2.5;
  return (
    <div style={styles.barTrack} title={`Attention score: ${score?.toFixed?.(1) ?? 0}`}>
      <div
        style={{
          ...styles.barFill,
          width: `${pct}%`,
          background: isNotable ? 'var(--amber)' : 'var(--text-faint)',
        }}
      />
    </div>
  );
}

function formatVolume(v) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return `${v}`;
}

const styles = {
  empty: {
    background: 'var(--surface)',
    border: '1px dashed var(--border)',
    borderRadius: 'var(--radius)',
    padding: '32px 24px',
    textAlign: 'center',
    color: 'var(--text-muted)',
  },
  tableWrap: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    overflow: 'hidden',
  },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13.5 },
  th: {
    textAlign: 'left',
    padding: '10px 16px',
    fontSize: 11.5,
    letterSpacing: 0.3,
    color: 'var(--text-muted)',
    borderBottom: '1px solid var(--border)',
    fontWeight: 500,
  },
  tr: { borderBottom: '1px solid var(--border)' },
  td: { padding: '12px 16px', verticalAlign: 'middle' },
  tdSymbol: { padding: '12px 16px', fontWeight: 600, letterSpacing: 0.2 },
  heldTag: {
    marginLeft: 8,
    fontSize: 10,
    fontWeight: 500,
    color: 'var(--amber)',
    border: '1px solid rgba(245,166,35,0.4)',
    borderRadius: 4,
    padding: '1px 5px',
    fontFamily: 'var(--font-ui)',
  },
  pending: { padding: '12px 16px', color: 'var(--text-faint)', fontStyle: 'italic', fontSize: 13 },
  staleTag: {
    marginLeft: 8,
    fontSize: 10,
    color: 'var(--amber)',
    border: '1px solid rgba(245,166,35,0.4)',
    borderRadius: 4,
    padding: '1px 5px',
    fontFamily: 'var(--font-ui)',
  },
  conflictTag: {
    marginLeft: 8,
    fontSize: 10,
    color: 'var(--text-muted)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '1px 5px',
    fontFamily: 'var(--font-ui)',
  },
  reason: {
    marginTop: 6,
    fontSize: 11.5,
    lineHeight: 1.35,
  },
  barTrack: {
    width: 60,
    height: 5,
    borderRadius: 3,
    background: 'var(--border)',
    overflow: 'hidden',
  },
  barFill: { height: '100%', borderRadius: 3 },
  actions: { display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' },
  holdBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 6,
    padding: '4px 8px',
    fontSize: 12,
    whiteSpace: 'nowrap',
  },
  heldBtn: {
    background: 'var(--amber-dim)',
    border: '1px solid rgba(245,166,35,0.4)',
    color: 'var(--amber)',
    borderRadius: 6,
    padding: '4px 8px',
    fontSize: 12,
    whiteSpace: 'nowrap',
  },
  removeBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-faint)',
    fontSize: 12.5,
  },
};
